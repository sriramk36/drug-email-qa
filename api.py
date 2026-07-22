import json
import asyncio
import time
import re
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

import enum

def highlight_flagged_claims(html: str, report) -> str:
    highlighted = html
    for item in report.items:
        if item.passed:
            continue
        css_class = "mlr-flag-fail" if item.severity.value == "blocking" else "mlr-flag-warn"
        quotes = re.findall(r'"([^"\n]{3,80})"', item.detail or "")
        for q in quotes:
            if q and q in highlighted:
                highlighted = highlighted.replace(
                    q, f'<mark class="{css_class}" title="{item.label}">{q}</mark>', 1
                )
    style_snippet = """
    <style>
    mark.mlr-flag-fail{background:rgba(244,63,94,0.25);color:#f43f5e;padding:0 2px;border-radius:3px;border-bottom:2px solid #f43f5e;}
    mark.mlr-flag-warn{background:rgba(245,158,11,0.25);color:#f59e0b;padding:0 2px;border-radius:3px;border-bottom:2px solid #f59e0b;}
    </style>
    """
    return style_snippet + highlighted

def custom_encoder(obj):
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        # Don't try to serialize deep complex objects like AzureOpenAI clients
        if obj.__class__.__name__ in ("AzureOpenAI", "AsyncAzureOpenAI", "Client", "LLMClient"):
            return f"<{obj.__class__.__name__}>"
        return obj.__dict__
    return str(obj)

def filter_update(update: dict) -> dict:
    """Remove backend-only objects that the frontend doesn't need and can't be cleanly serialized."""
    return {k: v for k, v in update.items() if k not in ("client", "brief")}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    async def event_stream():
        t0 = time.time()
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
            prev_failed_ids = []
            iteration_history = []
            
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
                
                delta_info = {}
                if node_name == "grade" and "grade_report" in update:
                    report = update["grade_report"]
                    current_iteration = final_state.get("iteration", 0)
                    warn_count = sum(1 for i in report.items if not i.passed and i.severity.value == "warning")
                    passed_count = sum(1 for i in report.items if i.passed)
                    
                    failed_rules = [i.rule_id for i in report.items if not i.passed and i.severity.value == "blocking"]
                    rectified = [r for r in prev_failed_ids if r not in failed_rules]
                    still_failing = [r for r in failed_rules if r in prev_failed_ids]
                    new_failures = [r for r in failed_rules if r not in prev_failed_ids]
                    
                    if prev_failed_ids: # only send deltas if there was a previous attempt
                        delta_info = {
                            "rectified": rectified,
                            "still_failing": still_failing,
                            "new_failures": new_failures
                        }
                        
                    iteration_history.append({
                        "attempt": current_iteration,
                        "passed": passed_count,
                        "failed": len(failed_rules),
                        "warned": warn_count,
                        "rectified": rectified,
                        "still_failing": still_failing,
                        "new_failures": new_failures
                    })
                        
                    prev_failed_ids = failed_rules
                
                payload = {
                    'node': node_name, 
                    'update': filter_update(update),
                    'delta': delta_info
                }
                yield f"data: {json.dumps(payload, default=custom_encoder)}\n\n"
                await asyncio.sleep(0.01)
            
            elapsed = time.time() - t0
            html_raw = final_state.get("html", "")
            report = final_state.get("grade_report")
            
            html_preview = html_raw
            if brief.uploaded_images:
                for fname, data_uri in brief.uploaded_images.items():
                    html_preview = html_preview.replace(f"uploaded:{fname}", data_uri)
            
            if report and not report.all_passed:
                html_preview = highlight_flagged_claims(html_preview, report)
            
            meta = {}
            if report:
                passed_count = sum(1 for i in report.items if i.passed)
                failed_count = sum(1 for i in report.items if not i.passed and i.severity.value == "blocking")
                warn_count = sum(1 for i in report.items if not i.passed and i.severity.value == "warning")
                
                out_dir = Path("outputs")
                out_dir.mkdir(exist_ok=True)
                existing = list(out_dir.glob("*.json"))
                draft_id = f"#{1200 + len(existing) + 1}"
                
                output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
                output_path = out_dir / output_filename
                output_path.write_text(html_raw, encoding="utf-8")
                
                meta = {
                    "id": draft_id,
                    "channel": brief.channel,
                    "type": brief.email_type or "-",
                    "market": brief.market,
                    "audience": brief.audience,
                    "brand": brief.brand,
                    "objective": brief.objective,
                    "iterations": final_state.get("iteration", 0),
                    "passed": passed_count,
                    "failed": failed_count,
                    "warned": warn_count,
                    "all_passed": report.all_passed,
                    "elapsed": f"{elapsed:.1f}",
                    "created_at": datetime.now().isoformat()
                }
                json_filename = output_filename.replace(".html", "") + ".json"
                (Path("outputs") / json_filename).write_text(json.dumps(meta, default=custom_encoder), encoding="utf-8")
                
            soft_review_notes_raw = final_state.get("soft_review_notes", []) or []
            soft_notes_serializable = [
                {"concern": n.concern, "detail": n.detail} if hasattr(n, "concern") else n
                for n in soft_review_notes_raw
            ]
            yield f"data: {json.dumps({'done': True, 'html': html_raw, 'html_preview': html_preview, 'report': report, 'meta': meta, 'iteration_history': iteration_history, 'soft_review_notes': soft_notes_serializable}, default=custom_encoder)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
