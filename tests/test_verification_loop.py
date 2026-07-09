from unittest.mock import patch

import graph


MOCK_EMAIL = """Subject: Learn about NovaMed for your health

Body: NovaMed is a treatment option for adults seeking drug awareness information. Always follow safety guidance and speak with a healthcare professional before starting any medication. This message includes a safety disclaimer for educational purposes.

CTA: Learn more about NovaMed and speak with your healthcare professional today.
"""


@patch.object(graph, "generate_email", return_value=MOCK_EMAIL)
@patch.object(graph, "review_email")
def test_verification_loop_returns_structured_result(mock_review, mock_generate):
    mock_review.return_value = {
        "passed": True,
        "overall_score": 100,
        "issues": [],
        "checks": {}
    }
    
    campaign = {
        "drug": "NovaMed",
        "audience": "Adults seeking drug awareness information",
        "goal": "Educate about safe use",
        "message": "Encourage readers to speak with a healthcare professional",
    }

    result = graph.run_verification_loop(campaign, max_attempts=2)

    assert mock_generate.call_count >= 1
    assert mock_review.call_count >= 1
    assert result["passed"] is True
    assert "Subject:" in result["email"]
    assert result["attempts"] >= 1
    assert result["review"]["overall_score"] >= 70
