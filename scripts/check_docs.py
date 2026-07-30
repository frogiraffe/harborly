"""Conservative documentation prose linter.

Flags two categories of prose problems for human review, plus one hard rule
for the PyPI long description. It never rewrites anything, and it is
deliberately conservative:

1. Forbidden phrases: wording the project has explicitly banned (see
   `notes/ACTIVE_HANDOFF.md` for why -- "byte identical" / "bit-for-bit" and
   close variants overstate a reproducibility guarantee this project does not
   make, and "humanized" is not an accurate description of an editorial
   change). A hit here is always wrong and fails the check.
2. Heuristic AI-writing signals: patterns loosely modeled on
   https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing (vague
   attribution, generic scene-setting, formulaic contrast constructions,
   inflated marketing claims, duplicated conclusions). These have real false
   positives in ordinary technical prose, so a hit here is reported for a
   human to look at and never fails the check by itself.
3. PyPI-unsafe README links: `pyproject.toml` renders the root `README.md` as
   the PyPI long description, which resolves relative links against the PyPI
   project page rather than the repository, so a repository-relative link or
   a broken same-document anchor there is always wrong. A hit here fails the
   check the same way a forbidden phrase does.

Usage:
    uv run python scripts/check_docs.py [paths...]

With no paths, scans the project's standard documentation locations.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".venv",
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".hypothesis",
        # Agentic-workflow planning artifacts (see docs/superpowers/plans/):
        # process/planning prose, not public documentation, and may quote
        # this script's own forbidden-phrase list as illustration.
        "superpowers",
    }
)

# Standard documentation locations for the sea-mile repository. Scanning the
# whole tree by default would sweep in third-party markdown under .venv/ and
# vendored license text; this list matches what the handoff's documentation
# constraints actually apply to: READMEs, docs, release notes, and generated
# reports.
DEFAULT_ROOTS: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "docs",
    "examples",
    "benchmarks",
    "benchmark-results",
    ".github",
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line: int
    category: str  # "forbidden" or "smell"
    label: str
    context: str

    def format(self) -> str:
        tag = "FORBIDDEN" if self.category == "forbidden" else "smell"
        return f"{self.path}:{self.line}: [{tag}:{self.label}] {self.context.strip()}"


_PYPI_SAFE_SCHEMES = ("http://", "https://", "mailto:")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _heading_slugs(text: str) -> set[str]:
    """GitHub-style heading slugs: lowercase, spaces to hyphens, strip punctuation."""
    slugs: set[str] = set()
    for match in _HEADING_RE.finditer(text):
        heading = match.group(2)
        slug = re.sub(r"[^\w\s-]", "", heading.lower())
        slug = re.sub(r"\s+", "-", slug.strip())
        slugs.add(slug)
    return slugs


def _check_pypi_target(
    path: Path, line: int, target: str, slugs: set[str], kind: str
) -> list[Finding]:
    if not target:
        return []
    if target.startswith(_PYPI_SAFE_SCHEMES):
        return []
    if target.startswith("#"):
        anchor = target[1:]
        if anchor and anchor not in slugs:
            return [
                Finding(
                    path,
                    line,
                    "forbidden",
                    f"pypi-{kind}-broken-anchor",
                    f"same-document anchor '#{anchor}' has no matching heading",
                )
            ]
        return []
    return [
        Finding(
            path,
            line,
            "forbidden",
            f"pypi-{kind}-relative",
            f"'{target}' is repository-relative and will not resolve when this "
            "file is rendered as the PyPI long description; use an absolute "
            "https://github.com/frogiraffe/sea-mile/blob/main/... (or "
            ".../tree/main/...) URL",
        )
    ]


def check_pypi_readme_links(path: Path, text: str) -> list[Finding]:
    """Reject any link/image target in a PyPI long-description README that
    would not resolve on the PyPI project page: only absolute http(s)/mailto
    URLs and same-document anchors pointing at a real heading are safe there.
    """

    findings: list[Finding] = []
    slugs = _heading_slugs(text)
    md = MarkdownIt("commonmark")
    for block in md.parse(text):
        if block.type != "inline" or block.children is None:
            continue
        line = (block.map[0] + 1) if block.map else 0
        for child in block.children:
            if child.type == "link_open":
                href = child.attrGet("href") or ""
                findings.extend(_check_pypi_target(path, line, href, slugs, "link"))
            elif child.type == "image":
                src = child.attrGet("src") or ""
                findings.extend(_check_pypi_target(path, line, src, slugs, "image"))
    findings.sort(key=lambda finding: finding.line)
    return findings


# Hard rule: never use these phrases in project prose, docs, or reports.
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("byte-identical", re.compile(r"\bbyte[\s-]+identical\b", re.IGNORECASE)),
    ("bit-for-bit", re.compile(r"\bbit[\s-]+for[\s-]+bit\b", re.IGNORECASE)),
    ("bit-identical", re.compile(r"\bbit[\s-]+identical\b", re.IGNORECASE)),
    (
        "humanized",
        re.compile(r"\bhumaniz(?:e|ed|es|ing|ation)\b", re.IGNORECASE),
    ),
)

# Heuristic signals of AI-generated prose. Conservative by design: flagged
# for review, never auto-fixed, never fails the check by itself.
SMELL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "generic-scene-setting",
        re.compile(
            r"\bin (?:today'?s|the ever-evolving|this day and age|"
            r"the modern|an increasingly)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "formulaic-contrast",
        re.compile(r"\bit'?s not (?:just|only) .{1,60}?,\s*it'?s\b", re.IGNORECASE),
    ),
    (
        "vague-attribution",
        re.compile(
            r"\b(?:many experts|some (?:say|argue)|studies show|"
            r"industry experts|researchers agree|"
            r"it is widely (?:known|believed))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "inflated-claim",
        re.compile(
            r"\b(?:game[\s-]?changing|revolutioniz\w+|cutting[\s-]edge|"
            r"seamless(?:ly)?|unleash\w*|state[\s-]of[\s-]the[\s-]art|"
            r"robust and scalable|elevate your)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # Whole-file signal: filtered in check_text() so only a *second*
        # conclusion-style opener in the same document is reported. Saying
        # "in conclusion" once is normal prose, not a defect.
        "duplicated-conclusion",
        re.compile(
            r"^(?:in (?:conclusion|summary)|to (?:conclude|summarize))\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _line_text(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end]


def check_text(path: Path, text: str) -> list[Finding]:
    """Return findings for one document's text, sorted by line number."""

    findings: list[Finding] = []
    for label, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    path,
                    _line_number(text, match.start()),
                    "forbidden",
                    label,
                    _line_text(text, match.start()),
                )
            )
    for label, pattern in SMELL_PATTERNS:
        matches = list(pattern.finditer(text))
        if label == "duplicated-conclusion" and len(matches) < 2:
            continue
        for match in matches:
            findings.append(
                Finding(
                    path,
                    _line_number(text, match.start()),
                    "smell",
                    label,
                    _line_text(text, match.start()),
                )
            )
    findings.sort(key=lambda finding: finding.line)
    return findings


def iter_markdown_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix == ".md":
                files.append(root)
            continue
        for path in sorted(root.rglob("*.md")):
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            files.append(path)
    return files


def check_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(check_text(path, text))
    return findings


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(root) for root in DEFAULT_ROOTS],
        help="files or directories to scan (default: standard doc locations)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    files = iter_markdown_files(args.paths)
    findings = check_paths(files)

    for path in files:
        if path == Path("README.md"):
            findings.extend(
                check_pypi_readme_links(path, path.read_text(encoding="utf-8"))
            )
            findings.sort(key=lambda finding: finding.line)

    forbidden = [finding for finding in findings if finding.category == "forbidden"]
    smells = [finding for finding in findings if finding.category == "smell"]

    for finding in findings:
        print(finding.format())

    print(
        f"\n{len(files)} file(s) scanned, {len(forbidden)} forbidden-phrase "
        f"hit(s), {len(smells)} heuristic smell(s) for review",
        file=sys.stderr,
    )

    return 1 if forbidden else 0


if __name__ == "__main__":
    raise SystemExit(main())
