"""Non-blocking external-link checker for documentation.

Extracts every absolute https:// link and image target from the project's
standard documentation locations and issues a HEAD (falling back to GET on a
405/501) request with a timeout, reporting confirmed 404/410 responses.
Intended for a scheduled, non-blocking GitHub Actions job -- never wired into
the required PR gate, since it depends on third-party site availability.

Usage:
    uv run python -m scripts.check_external_links

(Must be run as a module, not a bare script path, so the `scripts.check_docs`
import resolves.)
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

from markdown_it import MarkdownIt

from scripts.check_docs import DEFAULT_ROOTS, iter_markdown_files

_USER_AGENT = "sea-mile-doc-link-check/1.0 (+https://github.com/frogiraffe/sea-mile)"
_TIMEOUT_SECONDS = 10


def extract_https_links(path: Path, text: str) -> list[str]:
    links: list[str] = []
    md = MarkdownIt("commonmark")
    for block in md.parse(text):
        if block.type != "inline" or block.children is None:
            continue
        for child in block.children:
            target = None
            if child.type == "link_open":
                target = child.attrGet("href")
            elif child.type == "image":
                target = child.attrGet("src")
            if target and target.startswith("https://"):
                links.append(target)
    return links


def check_url(url: str) -> str | None:
    """Return an error description, or None if the URL looks reachable."""

    if not url.startswith("https://"):
        # extract_https_links() only ever yields https:// targets; this
        # guard makes that invariant explicit at the network boundary
        # instead of trusting the caller, and satisfies bandit's B310
        # url-scheme audit for urlopen().
        raise ValueError(f"refusing to open a non-https:// URL: {url}")

    request = urllib.request.Request(  # nosec B310 -- scheme checked above
        url, method="HEAD", headers={"User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):  # nosec B310
            return None
    except urllib.error.HTTPError as error:
        if error.code in (405, 501):
            get_request = urllib.request.Request(  # nosec B310
                url, method="GET", headers={"User-Agent": _USER_AGENT}
            )
            try:
                with urllib.request.urlopen(  # nosec B310
                    get_request, timeout=_TIMEOUT_SECONDS
                ):
                    return None
            except urllib.error.HTTPError as get_error:
                if get_error.code in (404, 410):
                    return f"{get_error.code} {get_error.reason}"
                return None  # rate limiting, anti-bot, etc. -- not a confirmed break
        if error.code in (404, 410):
            return f"{error.code} {error.reason}"
        return None
    except (urllib.error.URLError, TimeoutError) as error:
        return f"unreachable: {error}"


def main(argv: list[str] | None = None) -> int:
    del argv  # this checker always scans the standard documentation locations
    roots = [Path(root) for root in DEFAULT_ROOTS]
    files = iter_markdown_files(roots)
    urls: set[str] = set()
    for path in files:
        urls.update(extract_https_links(path, path.read_text(encoding="utf-8")))

    broken: list[tuple[str, str]] = []
    for url in sorted(urls):
        error = check_url(url)
        if error is not None:
            broken.append((url, error))

    for url, error in broken:
        print(f"{url}: {error}")
    print(
        f"\n{len(urls)} external link(s) checked, {len(broken)} confirmed broken",
        file=sys.stderr,
    )
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
