import pytest
from bs4 import BeautifulSoup
from schema import CampaignBrief, ContentClassification

from grader import rule_hcp_audience_tag, rule_regulatory_footer_tag

def test_word_boundary_regression():
    # Market="US" should NOT be satisfied by body text containing "focuses" or "discusses"
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="US",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS
    )

    # Note that rule_hcp_audience_tag requires both the "healthcare professional" string
    # AND the market name to appear if the market is known.
    html_fail = "<div>This focuses on healthcare professional insights and discusses outcomes.</div>"
    soup = BeautifulSoup(html_fail, "html.parser")
    
    item = rule_hcp_audience_tag(soup, html_fail, brief, {})
    assert not item.passed, "Word boundary check failed, incorrectly matched 'us' inside 'focuses' or 'discusses'."

    # Correct case
    html_pass = "<div>This US healthcare professional site is for HCPs.</div>"
    soup_pass = BeautifulSoup(html_pass, "html.parser")
    item_pass = rule_hcp_audience_tag(soup_pass, html_pass, brief, {})
    assert item_pass.passed

def test_unrecognized_market_narnia():
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="Narnia",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS
    )

    html = "<footer>Some footer text.</footer>"
    soup = BeautifulSoup(html, "html.parser")

    item = rule_regulatory_footer_tag(soup, html, brief, {})
    
    assert not item.passed
    assert item.severity == "warning", "Unrecognized market must produce a warning severity, not blocking."
