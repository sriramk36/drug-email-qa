import pytest
from unittest.mock import patch
from pipeline.soft_review import SoftReviewAgent
from core.schema import CampaignBrief, Channel, EmailType

@pytest.fixture
def mock_llm_client():
    with patch("pipeline.soft_review.LLMClient") as MockLLMClient:
        mock_instance = MockLLMClient.return_value
        mock_instance.soft_review.return_value = "This looks good, but could be friendlier."
        yield mock_instance

def test_soft_review_agent(mock_llm_client):
    agent = SoftReviewAgent()
    brief = CampaignBrief(
        id="test-sr-1",
        product_name="TestDrug",
        indication="Testing SR",
        target_audience="Patients",
        key_messages=["Test msg"],
        channel=Channel.EMAIL,
        email_type=EmailType.NEWSLETTER
    )
    
    html_content = "<html>Some draft content</html>"
    
    result = agent.review(html_content, brief)
    
    assert result == "This looks good, but could be friendlier."
    mock_llm_client.soft_review.assert_called_once_with(
        html_content, 
        brief_context=brief.model_dump_json()
    )
