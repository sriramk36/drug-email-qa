import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from agents.export_utils import build_html_export, build_text_export
from agents.image_analyzer import analyze_image
from graph import run_verification_loop

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

app = FastAPI(title="Drug Email QA", version="1.0.0")


def _save_upload(upload: UploadFile) -> dict:
    filename = Path(upload.filename or "upload").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return {"available": False, "summary": f"Unsupported image type: {ext}"}

    content = upload.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return {"available": False, "summary": "Image exceeds 5 MB upload limit."}

    uploads_dir = ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    image_path = uploads_dir / safe_name
    with image_path.open("wb") as fh:
        fh.write(content)
    try:
        return analyze_image(str(image_path))
    finally:
        image_path.unlink(missing_ok=True)


def _campaign_payload(drug: str, audience: str, goal: str, message: str) -> dict:
    return {
        "drug": drug,
        "audience": audience,
        "goal": goal,
        "message": message,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run")
async def run(
    drug: str = Form("NovaMed"),
    audience: str = Form("Adults 30-50"),
    goal: str = Form("Drug awareness"),
    message: str = Form("Educate about safe usage and encourage professional guidance"),
    image: Optional[UploadFile] = File(None),
):
    """Run the verification loop — same flow as app.py CLI."""
    image_info = {"available": False}
    if image is not None and image.filename:
        image_info = _save_upload(image)

    payload = _campaign_payload(drug, audience, goal, message)
    try:
        return run_verification_loop(payload, image_info=image_info)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "passed": False,
                "email": "",
                "attempts": 0,
                "review": {
                    "overall_score": 0,
                    "issues": [],
                    "feedback": [f"Server error: {type(exc).__name__}: {exc}"],
                    "checks": {},
                },
                "context": {},
                "image_analysis": image_info,
                "logs": {
                    "generator": {"error": str(exc)},
                    "auditor": {"error": str(exc)},
                },
            },
        )


@app.post("/export/html", response_class=HTMLResponse)
async def export_html(email: str = Form(...), passed: Optional[str] = Form(None), attempts: Optional[str] = Form(None), score: Optional[str] = Form(None)):
    result = None
    if passed is not None:
        result = {
            "passed": passed.lower() == "true",
            "attempts": int(attempts or 0),
            "review": {"overall_score": int(score or 0), "feedback": []},
        }
    return HTMLResponse(content=build_html_export(email, result), headers={"Content-Disposition": 'attachment; filename="drug-email-export.html"'})


@app.post("/export/text", response_class=PlainTextResponse)
async def export_text(email: str = Form(...), passed: Optional[str] = Form(None), attempts: Optional[str] = Form(None), score: Optional[str] = Form(None)):
    result = None
    if passed is not None:
        result = {
            "passed": passed.lower() == "true",
            "attempts": int(attempts or 0),
            "review": {"overall_score": int(score or 0), "feedback": []},
        }
    return PlainTextResponse(
        content=build_text_export(email, result),
        headers={"Content-Disposition": 'attachment; filename="drug-email-export.txt"'},
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    print(f"UI server running at http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
