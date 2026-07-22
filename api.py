import json
import asyncio
from typing import Optional
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.schema import CampaignBrief, Channel, EmailType, ContentClassification, Severity
from core.llm_client import LLMClient
from pipeline.pipeline_langgraph import build_graph

app = FastAPI(title="MLR Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    return HTMLResponse(Path("static/index.html").read_text(encoding="utf-8"))


class GenerateRequest(BaseModel):
    channel: str
    email_type: Optional[str] = None
    market: str
    audience: str
    brand: str
    objective: str
    classification: str
    run_soft_review: bool = True
    images: dict[str, str] = {}

def get_recent_drafts():
    records = []
    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        return records
    for json_file in outputs_dir.glob("*.json"):
        try:
            records.append(json.loads(json_file.read_text(encoding="utf-8")))
        except Exception:
            continue
    records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return records

@app.get("/api/history")
async def get_history():
    return get_recent_drafts()

def _serialize_update(update: dict) -> dict:
    safe = {}
    for k, v in update.items():
        if hasattr(v, "model_dump"):
            safe[k] = v.model_dump()
        elif hasattr(v, "__dict__"):
            safe[k] = v.__dict__
        elif type(v) in [str, int, float, bool, list, dict, type(None)]:
            safe[k] = v
        else:
            safe[k] = str(v)
    return safe

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    async def event_stream():
        try:
            client = LLMClient()
            brief = CampaignBrief(
                channel=Channel(req.channel),
                email_type=EmailType(req.email_type) if req.email_type else None,
                market=req.market,
                audience=req.audience,
                brand=req.brand,
                objective=req.objective,
                classification=ContentClassification(req.classification),
                uploaded_images=req.images
            )
            
            graph = build_graph()
            final_state = {}
            
            for step in graph.stream({
                "brief": brief,
                "client": client,
                "run_soft_review": req.run_soft_review,
                "iteration": 0,
                "prev_failed_ids": None,
            }):
                node_name = list(step.keys())[0]
                update = step[node_name]
                final_state.update(update)
                
                yield f"data: {json.dumps({'node': node_name, 'update': _serialize_update(update)})}\n\n"
                await asyncio.sleep(0.01)
            
            html_raw = final_state.get("html", "")
            report = final_state.get("grade_report")
            meta = {}
            if report:
                passed_count = sum(1 for i in report.items if i.passed)
                failed_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.BLOCKING)
                warn_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.WARNING)
                
                output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
                output_path = Path("outputs") / output_filename
                output_path.parent.mkdir(exist_ok=True)
                output_path.write_text(html_raw, encoding="utf-8")
                
                meta = {
                    "id": output_filename.replace(".html", ""),
                    "channel": brief.channel,
                    "market": brief.market,
                    "audience": brief.audience,
                    "brand": brief.brand,
                    "objective": brief.objective,
                    "iterations": final_state.get("iteration", 0),
                    "passed": passed_count,
                    "failed": failed_count,
                    "warned": warn_count,
                    "all_passed": report.all_passed,
                    "created_at": datetime.now().isoformat()
                }
                (Path("outputs") / f"{output_filename}.json").write_text(json.dumps(meta), encoding="utf-8")
                
            yield f"data: {json.dumps({'done': True, 'html': html_raw, 'report': report.model_dump() if report else {}, 'meta': meta})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
