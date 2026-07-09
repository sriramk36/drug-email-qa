from agents.export_utils import build_html_export, build_text_export, parse_email_sections

SAMPLE = """Subject: Hello NovaMed

Body: Safety and disclaimer included. Speak with a healthcare professional.

CTA: Learn more today.
"""


def test_parse_email_sections():
    sections = parse_email_sections(SAMPLE)
    assert len(sections) == 3
    assert sections[0][0] == "Subject"


def test_build_text_export_includes_email():
    text = build_text_export(SAMPLE)
    assert "Subject: Hello NovaMed" in text


def test_build_html_export_includes_sections():
    html = build_html_export(SAMPLE, {"passed": True, "attempts": 1, "review": {"overall_score": 95, "feedback": []}})
    assert "Hello NovaMed" in html
    assert "Passed" in html
