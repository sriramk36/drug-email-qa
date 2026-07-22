import pytest
from unittest.mock import MagicMock
from pipeline.generator import generate
from core.schema import CampaignBrief, Channel, EmailType
from pipeline.grader import GradingContext

@pytest.fixture
def mock_llm_client():
    mock_instance = MagicMock()
    mock_instance.complete.return_value = "<html>Test Draft</html>"
    return mock_instance

def test_draft_generator(mock_llm_client):
    brief = CampaignBrief(
        id="test-gen-1",
        product_name="TestDrug",
        indication="Testing Generation",
        target_audience="HCPs",
        key_messages=["Test msg"],
        channel=Channel.EMAIL,
        email_type=EmailType.MASS
    )
    ctx = GradingContext(
        market_info={"id": "US", "name": "United States", "rules": []},
        tokens={"company": "TestCo", "primary": "#000", "secondary": "#fff", "ae_report_line": "Call AE", "pi_link_placeholder": "PI here"}
    )
    
    result = generate(brief, mock_llm_client, ctx)
    
    assert result == "<html>Test Draft</html>"
    mock_llm_client.complete.assert_called_once()

