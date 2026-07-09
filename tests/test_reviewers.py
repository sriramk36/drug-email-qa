import json
from unittest.mock import MagicMock, patch
from agents.reviewers import review_email
from knowledge.context import build_context


def _sample_email(drug="NovaMed"):
    return f"Subject: Learn about {drug} for your health\n\nBody: {drug} is a treatment option for adults. Always follow safety guidance and speak with a healthcare professional before starting any medication. This message includes a safety disclaimer for educational purposes.\n\nCTA: Learn more about {drug} and speak with your healthcare professional today.\n"


def _campaign(drug="NovaMed"):
    return {
        "drug": drug,
        "audience": "Adults 30-50",
        "goal": "Drug awareness",
        "message": "Educate about safe usage",
    }


def _context():
    return build_context(_campaign())


def _mock_client(response_json):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    return mock_client, "gpt-mock"


@patch("agents.reviewers.get_client_and_model")
def test_review_passes_valid_email(mock_get):
    mock_get.return_value = _mock_client({
        "medical_accuracy": {"passed": True, "issues": []},
        "brand_guidelines": {"passed": True, "issues": []},
        "email_standards": {"passed": True, "issues": []},
        "compliance": {"passed": True, "issues": []},
        "image_review": {"passed": True, "issues": []},
    })
    result = review_email(_sample_email(), _campaign(), _context())
    assert result["passed"] is True
    assert result["overall_score"] >= 90
    assert result["checks"]["medical_accuracy"]["passed"] is True


@patch("agents.reviewers.get_client_and_model")
def test_review_fails_banned_claim(mock_get):
    mock_get.return_value = _mock_client({
        "medical_accuracy": {"passed": False, "issues": ["Contains cure"]},
        "brand_guidelines": {"passed": True, "issues": []},
        "email_standards": {"passed": True, "issues": []},
        "compliance": {"passed": True, "issues": []},
        "image_review": {"passed": True, "issues": []},
    })
    email = _sample_email().replace("treatment option", "cure for all symptoms")
    result = review_email(email, _campaign(), _context())
    assert result["passed"] is False
    assert any("cure" in i.lower() for i in result["issues"])


@patch("agents.reviewers.get_client_and_model")
def test_review_fails_missing_subject(mock_get):
    mock_get.return_value = _mock_client({
        "medical_accuracy": {"passed": True, "issues": []},
        "brand_guidelines": {"passed": True, "issues": []},
        "email_standards": {"passed": False, "issues": ["Missing subject"]},
        "compliance": {"passed": True, "issues": []},
        "image_review": {"passed": True, "issues": []},
    })
    email = _sample_email().replace("Subject:", "Title:")
    result = review_email(email, _campaign(), _context())
    assert result["checks"]["email_standards"]["passed"] is False


@patch("agents.reviewers.get_client_and_model")
def test_review_without_image_still_passes(mock_get):
    mock_get.return_value = _mock_client({
        "medical_accuracy": {"passed": True, "issues": []},
        "brand_guidelines": {"passed": True, "issues": []},
        "email_standards": {"passed": True, "issues": []},
        "compliance": {"passed": True, "issues": []},
        "image_review": {"passed": True, "issues": []},
    })
    result = review_email(_sample_email(), _campaign(), _context(), image_info={"available": False})
    assert result["checks"]["image_review"]["passed"] is True

