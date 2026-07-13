import pytest
from bs4 import BeautifulSoup
from core.schema import CampaignBrief, ContentClassification, Severity

from pipeline.grader import (
    rule_draft_watermark,
    rule_job_code_pending,
    rule_hcp_audience_tag,
    rule_ae_box,
    rule_brand_leak,
    rule_pi_link_if_branded,
    rule_regulatory_footer_tag,
    rule_no_hardcoded_cta_url,
    rule_uploaded_images_used,
    GradingContext,
)
from core.regulatory import MarketInfo, AudienceInfo


def run_rule(rule_func, raw_html: str, brief: CampaignBrief, tokens: dict = None):
    ctx = GradingContext(
        tokens=tokens or {},
        market_info=MarketInfo(market_text="UK", body_name="ABPI", tags=["ABPI"], known=True, aliases=["uk", "united kingdom"], source="dictionary"),
        audience_info=AudienceInfo(audience_text="HCP", source="dictionary", known=True, is_hcp=True)
    )
    soup = BeautifulSoup(raw_html, "html.parser")
    return rule_func(soup, raw_html, brief, ctx)

def test_rule_draft_watermark(base_brief):
    # Pass
    html_pass = "<div>DRAFT</div><div>Not approved for distribution</div>"
    item = run_rule(rule_draft_watermark, html_pass, base_brief)
    assert item.passed

    # Fail
    html_fail = "<div>DRAFT</div>"
    item = run_rule(rule_draft_watermark, html_fail, base_brief)
    assert not item.passed

def test_rule_job_code_pending(base_brief):
    # Pass
    html_pass = "<footer>[CL ID — PENDING]</footer>"
    item = run_rule(rule_job_code_pending, html_pass, base_brief)
    assert item.passed

    # Fail
    html_fail = "<footer></footer>"
    item = run_rule(rule_job_code_pending, html_fail, base_brief)
    assert not item.passed

def test_rule_hcp_audience_tag(base_brief):
    # Pass
    html_pass = "<div>This site is intended for UK healthcare professionals only.</div>"
    item = run_rule(rule_hcp_audience_tag, html_pass, base_brief)
    assert item.passed

    # Fail
    html_fail = "<div>Welcome to the Dovato site.</div>"
    item = run_rule(rule_hcp_audience_tag, html_fail, base_brief)
    assert not item.passed

def test_rule_ae_box(base_brief):
    tokens = {"ae_report_line": "Please report adverse events to www.fda.gov"}

    # Pass
    html_pass = "<div style='border: 2px solid black'>Please report adverse events to www.fda.gov</div>"
    item = run_rule(rule_ae_box, html_pass, base_brief, tokens)
    assert item.passed

    # Fail: missing border
    html_fail1 = "<div>Please report adverse events to www.fda.gov</div>"
    item = run_rule(rule_ae_box, html_fail1, base_brief, tokens)
    assert not item.passed

    # Fail: missing text
    html_fail2 = "<div style='border: 2px solid black'>Contact us</div>"
    item = run_rule(rule_ae_box, html_fail2, base_brief, tokens)
    assert not item.passed

def test_rule_brand_leak(base_brief, branded_brief):
    # Pass (unbranded, no leak)
    html_pass = "<div class='email-content'>Learn about the disease.</div>"
    item = run_rule(rule_brand_leak, html_pass, base_brief)
    assert item.passed

    # Fail (unbranded, leak)
    html_fail = "<div class='email-content'>Try Dovato today.</div>"
    item = run_rule(rule_brand_leak, html_fail, base_brief)
    assert not item.passed

    # Pass (branded, leak allowed)
    item = run_rule(rule_brand_leak, html_fail, branded_brief)
    assert item.passed

def test_rule_pi_link_if_branded(branded_brief, base_brief):
    # Pass
    html_pass = "<div>Read the Prescribing Information here.</div>"
    item = run_rule(rule_pi_link_if_branded, html_pass, branded_brief)
    assert item.passed

    # Fail
    html_fail = "<div>Learn more on our website.</div>"
    item = run_rule(rule_pi_link_if_branded, html_fail, branded_brief)
    assert not item.passed

    # Unbranded brief always passes this
    item = run_rule(rule_pi_link_if_branded, html_fail, base_brief)
    assert item.passed

def test_rule_regulatory_footer_tag(base_brief):
    # Pass (UK market needs ABPI)
    html_pass = "<footer>Follows ABPI Code of Practice</footer>"
    item = run_rule(rule_regulatory_footer_tag, html_pass, base_brief)
    assert item.passed

    # Fail
    html_fail = "<footer>Follows FDA guidelines</footer>"
    item = run_rule(rule_regulatory_footer_tag, html_fail, base_brief)
    assert not item.passed

def test_rule_no_hardcoded_cta_url(base_brief):
    # Pass
    html_pass = "<a href='#'>Click here</a> <a href='[TBC]'>More info</a>"
    item = run_rule(rule_no_hardcoded_cta_url, html_pass, base_brief)
    assert item.passed

    # Fail
    html_fail = "<a href='https://example.com'>Click here</a>"
    item = run_rule(rule_no_hardcoded_cta_url, html_fail, base_brief)
    assert not item.passed

def test_rule_uploaded_images_used(base_brief):
    # Pass (no images)
    item = run_rule(rule_uploaded_images_used, "<html></html>", base_brief)
    assert item.passed

    # Pass (images used)
    base_brief.uploaded_images = {"logo.png": "data"}
    html_pass = "<img src='uploaded:logo.png' />"
    item = run_rule(rule_uploaded_images_used, html_pass, base_brief)
    assert item.passed

    # Fail (images not used)
    html_fail = "<html></html>"
    item = run_rule(rule_uploaded_images_used, html_fail, base_brief)
    assert not item.passed
