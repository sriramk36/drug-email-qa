import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from ui.server import app

MOCK_EMAIL = """Subject: Learn about NovaMed

Body: NovaMed supports awareness. Follow safety guidance and disclaimer. Speak with a healthcare professional.

CTA: Learn more and speak with your healthcare professional.
"""


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Drug Email QA" in response.text


@patch("ui.server.run_verification_loop")
def test_run_endpoint_matches_cli_flow(mock_loop, client):
    mock_loop.return_value = {
        "passed": True,
        "email": MOCK_EMAIL,
        "attempts": 1,
        "review": {"overall_score": 95, "checks": {}, "issues": [], "feedback": []},
        "context": {},
        "image_analysis": {"available": False},
        "logs": {"generator": {"attempts": []}, "auditor": {"reviews": []}},
    }
    response = client.post(
        "/run",
        data={
            "drug": "NovaMed",
            "audience": "Adults 30-50",
            "goal": "Drug awareness",
            "message": "Educate about safe usage",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] is True
    assert "Subject:" in data["email"]
    mock_loop.assert_called_once()
    call_args = mock_loop.call_args
    assert call_args[0][0]["drug"] == "NovaMed"


def test_export_html(client):
    response = client.post("/export/html", data={"email": MOCK_EMAIL, "passed": "true", "attempts": "1", "score": "95"})
    assert response.status_code == 200
    assert "NovaMed" in response.text
    assert "attachment" in response.headers.get("content-disposition", "")


def test_export_text(client):
    response = client.post("/export/text", data={"email": MOCK_EMAIL})
    assert response.status_code == 200
    assert "Subject: Learn about NovaMed" in response.text
