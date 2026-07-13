from fastapi import FastAPI

from core.schema import CampaignBrief, PipelineResult
from pipeline.pipeline import run_pipeline

app = FastAPI(title="MLR Pipeline API")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/briefs", response_model=PipelineResult)
def create_brief(brief: CampaignBrief):
    # This executes the loop (generate, grade, revise)
    # The pipeline internally handles llm client initialization and tokens.
    result = run_pipeline(brief)
    return result
