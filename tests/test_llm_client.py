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

def test_complete(mock_llm_client):
    result = mock_llm_client.complete(system="System Prompt", user="User Prompt")
    assert result == "Test content"
