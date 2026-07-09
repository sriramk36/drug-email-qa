import json
from typing import Any, Dict

from tenacity import retry, stop_after_attempt, wait_exponential

from agents.generator import get_client_and_model
from knowledge.rules import build_review_rules


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def review_email(email_text: str, campaign: Dict[str, Any], context: Dict[str, Any], image_info: Dict[str, Any] | None = None) -> Dict[str, Any]:
    rules = build_review_rules(context)
    client, model = get_client_and_model()

    if client is None or model is None:
        raise EnvironmentError("OpenAI/Azure client is not configured for reviewers.")

    system_prompt = """You are an expert medical and legal compliance reviewer for healthcare marketing emails.
You will be provided with an email draft, the campaign context, and the rules.
You must evaluate the email against the rules in 5 categories: medical_accuracy, brand_guidelines, email_standards, compliance, image_review.
For each category, determine if it passed (boolean) and list any issues found (list of strings).
Your response MUST be a valid JSON object matching the following structure:
{
  "medical_accuracy": {"passed": true, "issues": []},
  "brand_guidelines": {"passed": true, "issues": []},
  "email_standards": {"passed": true, "issues": []},
  "compliance": {"passed": true, "issues": []},
  "image_review": {"passed": true, "issues": []}
}
Be strict. If a requirement is missing, it fails. Return ONLY valid JSON."""

    image_caption = "No image uploaded"
    if image_info and image_info.get("available"):
        image_caption = image_info.get("caption", "Unknown")

    user_prompt = f"""
CAMPAIGN:
Drug: {campaign.get('drug')}
Goal: {campaign.get('goal')}
Message: {campaign.get('message')}

RULES:
Banned Claims: {rules.get('banned_claims', [])}
Promotional Phrases to avoid: {rules.get('promotional_phrases', [])}
Requires Subject: {rules.get('requires_subject', True)}
Requires Body: {rules.get('requires_body', True)}
Requires CTA: {rules.get('requires_cta', True)}
Max Words: {rules.get('max_words', 200)}
Compliance Keywords: {rules.get('compliance_keywords', [])}

IMAGE INFO:
Caption: {image_caption}
Expected Image Guidance: {context.get("image_metadata", {}).get("hero_image", {}).get("caption", "")}

EMAIL DRAFT TO REVIEW:
{email_text}
"""

    # For Azure models that don't support response_format easily, just ask for JSON
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    result_text = response.choices[0].message.content
    
    # Strip markdown code blocks if the model wrapped the JSON
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
    result_text = result_text.strip()

    try:
        checks_data = json.loads(result_text)
    except json.JSONDecodeError:
        checks_data = {
            "medical_accuracy": {"passed": False, "issues": ["Failed to parse review JSON"]},
            "brand_guidelines": {"passed": False, "issues": ["Failed to parse review JSON"]},
            "email_standards": {"passed": False, "issues": ["Failed to parse review JSON"]},
            "compliance": {"passed": False, "issues": ["Failed to parse review JSON"]},
            "image_review": {"passed": False, "issues": ["Failed to parse review JSON"]},
        }

    checks = {}
    all_passed = True
    issues = []

    for category in ["medical_accuracy", "brand_guidelines", "email_standards", "compliance", "image_review"]:
        cat_data = checks_data.get(category, {"passed": False, "issues": ["Missing category in LLM response"]})
        passed = cat_data.get("passed", False)
        cat_issues = cat_data.get("issues", [])

        checks[category] = {
            "passed": passed,
            "score": 100 if passed else 70,
            "issues": cat_issues
        }

        if not passed:
            all_passed = False
            issues.extend(cat_issues)

    score = round(sum(c["score"] for c in checks.values()) / len(checks))

    feedback = []
    for section_name, section in checks.items():
        if not section["passed"]:
            feedback.append(f"{section_name}: " + "; ".join(section["issues"]) if section["issues"] else section_name)

    return {
        "passed": all_passed,
        "overall_score": score,
        "checks": checks,
        "issues": issues,
        "feedback": feedback or ["No issues found. The email satisfies the current review rubric."],
    }
