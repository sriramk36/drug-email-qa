from typing import Any, Dict, Optional

from agents.generator import generate_email
from agents.reviewers import review_email
from knowledge.context import build_context


def run_verification_loop(
    campaign: Dict[str, Any],
    image_info: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    context = build_context(campaign)
    feedback = None
    last_review = None
    email_text = ""
    # structured logs to return to callers / UI
    generator_attempts = []
    review_history = []

    for attempt in range(1, max_attempts + 1):
        try:
            email_text = generate_email(campaign, feedback=feedback)
            review = review_email(email_text, campaign, context, image_info=image_info)
        except Exception as e:
            # If a fatal error occurs (e.g. auth issue, or tenacity gave up), log it and fail gracefully
            review = {
                "passed": False,
                "issues": [f"Fatal error during generation or review: {str(e)}"],
                "overall_score": 0,
                "checks": {}
            }
        
        last_review = review

        # record logs for this attempt
        generator_attempts.append({
            "attempt": attempt,
            "email": email_text,
            "feedback_used": feedback,
        })
        review_history.append(review)

        if review.get("passed", False):
            return {
                "passed": True,
                "email": email_text,
                "attempts": attempt,
                "review": review,
                "context": context,
                "image_analysis": image_info,
                "logs": {
                    "generator": {"attempts": generator_attempts},
                    "auditor": {"reviews": review_history},
                },
            }

        feedback = "\n".join(review["issues"])

    return {
        "passed": False,
        "email": email_text,
        "attempts": max_attempts,
        "review": last_review,
        "context": context,
        "image_analysis": image_info,
        "logs": {
            "generator": {"attempts": generator_attempts},
            "auditor": {"reviews": review_history},
        },
    }
