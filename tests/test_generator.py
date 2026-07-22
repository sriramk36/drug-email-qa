import pytest
from unittest.mock import patch, MagicMock
from pipeline.generator import DraftGenerator
from core.schema import CampaignBrief, Channel, EmailType

@pytest.fixture
def mock_llm_client():
    with patch("pipeline.generator.LLMClient") as MockLLMClient:
        mock_instance = MockLLMClient.return_value
        mock_instance.generate_draft.return_value = "<html>Test Draft</html>"
        yield mock_instance

def test_draft_generator(mock_llm_client):
    generator = DraftGenerator()
    brief = CampaignBrief(
        id="test-gen-1",
        product_name="TestDrug",
        indication="Testing Generation",
        target_audience="HCPs",
        key_messages=["Test msg"],
        channel=Channel.EMAIL,
        email_type=EmailType.NEWSLETTER
    )
    
    result = generator.generate(brief)
    
    assert result == "<html>Test Draft</html>"
    mock_llm_client.generate_draft.assert_called_once_with(brief)
