"""Unit tests for the offline parts of the external-link checker.

Deliberately does not make network calls in this test file -- the checker's
network behavior is exercised manually / by the scheduled workflow, not by
the deterministic pytest suite.
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_external_links import extract_https_links


def test_extract_https_links_finds_link_and_image_targets() -> None:
    text = (
        "[docs](https://github.com/frogiraffe/harborly/blob/main/docs/GUIDE.md)\n"
        "![badge](https://img.shields.io/pypi/v/harborly.svg)\n"
    )
    links = extract_https_links(Path("README.md"), text)
    assert "https://github.com/frogiraffe/harborly/blob/main/docs/GUIDE.md" in links
    assert "https://img.shields.io/pypi/v/harborly.svg" in links


def test_extract_https_links_ignores_relative_and_code_fenced_targets() -> None:
    text = "[local](docs/GUIDE.md)\n\n```markdown\n[x](https://example.com/in-a-fence)\n```\n"
    links = extract_https_links(Path("README.md"), text)
    assert links == []
