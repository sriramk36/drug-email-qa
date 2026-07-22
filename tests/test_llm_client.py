import pytest
from unittest.mock import patch, MagicMock
import os

# We need to mock os.environ before importing LLMClient because it might load dotenv at module level.
@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test_key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.endpoint.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

from core.llm_client import LLMClient
from core.schema import CampaignBrief, Channel, EmailType

@pytest.fixture
def mock_llm_client():
    with patch("openai.AzureOpenAI") as MockAzureOpenAI:
        mock_client = MockAzureOpenAI.return_value
        # Configure a dummy response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test content"
        mock_client.chat.completions.create.return_value = mock_response
        
        yield LLMClient()

def test_generate_draft(mock_llm_client):
    brief = CampaignBrief(
        id="test-123",
        product_name="TestDrug",
        indication="Testing",
        target_audience="HCPs",
        key_messages=["Test message"],
        channel=Channel.EMAIL,
        email_type=EmailType.MASS
    )
    
    result = mock_llm_client.generate_draft(brief)
    assert result == "Test content"

def test_soft_review(mock_llm_client):
    result = mock_llm_client.soft_review("Draft HTML content")
    assert result == "Test content"
