from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cross_org_context_and_pages_are_sanitized():
    context = (ROOT / "docs/CROSS-ORGANIZATION-CONTEXT.md").read_text()
    page = (ROOT / "site/index.html").read_text()
    assert "re8ch/service-backend#2883" in context
    assert "owner/repository#number" in context
    assert "https://re8ch.com/" in page
    assert "application/ld+json" in page
    assert "KUBECONFIG" not in page
    assert "apiVersion:" not in page
    assert "223." not in page
    assert "10." not in page
