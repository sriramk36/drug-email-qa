import pytest
from unittest.mock import patch, MagicMock
import os

# We need to set os.environ before importing LLMClient because core.config loads at module level.
os.environ["AZURE_OPENAI_API_KEY"] = "test_key"
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://test.endpoint.com"
os.environ["AZURE_OPENAI_API_VERSION"] = "2024-02-15-preview"

from core.llm_client import LLMClient
from core.schema import CampaignBrief, Channel, EmailType

@pytest.fixture
def mock_llm_client():
    client = LLMClient()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test content"
    mock_client.chat.completions.create.return_value = mock_response
    client._client = mock_client
    yield client

def test_complete(mock_llm_client):
    result = mock_llm_client.complete(system="System Prompt", user="User Prompt")
    assert result == "Test content"
