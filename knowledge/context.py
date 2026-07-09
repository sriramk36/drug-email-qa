import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent


def _read_text(name: str, campaign: Dict[str, Any]) -> str:
    content = (BASE_DIR / name).read_text(encoding="utf-8")
    try:
        return content.format(**campaign)
    except KeyError:
        return content


def build_context(campaign: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "campaign": campaign,
        "drug_info": _read_text("drug_info.md", campaign),
        "brand_guidelines": _read_text("brand_guidelines.md", campaign),
        "email_guidelines": _read_text("email_guidelines.md", campaign),
        "compliance_rules": _read_text("compliance_rules.md", campaign),
        "image_metadata": json.loads(_read_text("image_metadata.json", campaign)),
    }
