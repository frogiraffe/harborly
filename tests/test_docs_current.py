from __future__ import annotations

import argparse
import re
import shlex
import tomllib
from pathlib import Path

from markdown_it import MarkdownIt

import harborly
from harborly.cli import _parser
from harborly.exceptions import RoutingErrorReason
from scripts.check_docs import _heading_slugs

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
LIBRARY_API = ROOT / "docs" / "LIBRARY_API.md"
API_COMPATIBILITY = ROOT / "docs" / "API_COMPATIBILITY.md"
OUTPUT_SCHEMAS = ROOT / "docs" / "OUTPUT_SCHEMAS.md"
MARKDOWN_FILES = [
    *sorted(ROOT.glob("*.md")),
    # docs/superpowers/ holds agentic-workflow planning artifacts, not public
    # documentation -- see scripts/check_docs.py's matching exclusion.
    *sorted(
        path
        for path in (ROOT / "docs").rglob("*.md")
        if "superpowers" not in path.parts
    ),
    *sorted((ROOT / "examples").rglob("*.md")),
    ROOT / "src" / "harborly" / "data" / "ATTRIBUTION.md",
]


def _command_names(parser: argparse.ArgumentParser) -> list[str]:
    names: list[str] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                names.append(name)
                names.extend(_command_names(subparser))
    return names


def test_every_cli_command_is_documented() -> None:
    docs = (README.read_text() + LIBRARY_API.read_text()).lower()
    missing = sorted(
        {name for name in _command_names(_parser()) if name.lower() not in docs}
    )
    assert not missing, f"undocumented CLI commands: {missing}"


def test_every_public_export_is_documented() -> None:
    docs = LIBRARY_API.read_text().lower()
    missing = [name for name in harborly.__all__ if name.lower() not in docs]
    assert not missing, f"undocumented public exports: {missing}"


def test_every_stable_export_is_in_compatibility_policy() -> None:
    policy = API_COMPATIBILITY.read_text().lower()
    missing = [name for name in harborly.__all__ if name.lower() not in policy]
    assert not missing, f"exports missing from compatibility policy: {missing}"


def test_every_routing_error_reason_is_documented() -> None:
    schemas = OUTPUT_SCHEMAS.read_text()
    missing = [
        reason.value for reason in RoutingErrorReason if reason.value not in schemas
    ]
    assert not missing, f"undocumented routing error reasons: {missing}"


def _example_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    for block in re.findall(r"```bash\n(.*?)```", README.read_text(), re.DOTALL):
        for line in block.splitlines():
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            if tokens[:3] == ["uv", "run", "harborly"]:
                commands.append(tokens[3:])
            elif tokens[:1] == ["harborly"]:
                commands.append(tokens[1:])
    return commands


def test_readme_examples_parse() -> None:
    parser = _parser()
    for command in _example_commands():
        try:
            parser.parse_args(command)
        except SystemExit:  # pragma: no cover - only on a broken example
            raise AssertionError(f"README example does not parse: {command}") from None


def _has_json_option(subparser: argparse.ArgumentParser) -> bool:
    return any("--json" in action.option_strings for action in subparser._actions)


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_only_json_emitting_commands_accept_the_json_flag() -> None:
    commands = _subcommands(_parser())

    # export selects output with --format; tui and serve are interactive.
    assert not _has_json_option(commands["export"])
    assert not _has_json_option(commands["tui"])
    assert not _has_json_option(commands["serve"])

    for name in ("info", "search", "show", "near", "match", "route", "matrix"):
        assert _has_json_option(commands[name]), name

    data_commands = _subcommands(commands["data"])
    for name in ("download", "build", "prepare", "verify", "lock"):
        assert _has_json_option(data_commands[name]), name

    cache_commands = _subcommands(commands["cache"])
    for name in ("info", "prune", "clear"):
        assert _has_json_option(cache_commands[name]), name


def test_readme_scopes_json_and_documents_exit_codes() -> None:
    readme = README.read_text().lower()

    assert "from every command" not in readme
    assert "after any command" not in readme

    assert "exit code" in readme


def test_markdown_files_render_and_have_balanced_fences() -> None:
    parser = MarkdownIt("commonmark")
    for path in MARKDOWN_FILES:
        text = path.read_text(encoding="utf-8")
        assert sum(line.startswith("```") for line in text.splitlines()) % 2 == 0, path
        rendered = parser.render(text)
        assert rendered.strip(), path


def test_local_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in MARKDOWN_FILES:
        text = path.read_text(encoding="utf-8")
        for target in link_pattern.findall(text):
            if "://" in target or target.startswith("mailto:"):
                continue
            if target.startswith("#"):
                anchor = target[1:]
                assert not anchor or anchor in _heading_slugs(text), (path, target)
                continue
            file_part, _, fragment = target.partition("#")
            resolved = path.parent / file_part
            assert resolved.exists(), (path, target)
            if fragment:
                assert fragment in _heading_slugs(
                    resolved.read_text(encoding="utf-8")
                ), (path, target)


def test_every_optional_dependency_extra_is_documented() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = set(project["project"]["optional-dependencies"])
    readme = README.read_text().lower()
    missing = sorted(extra for extra in extras if extra.lower() not in readme)
    assert not missing, f"extras missing from README.md: {missing}"


# Maintainer/methodology docs that are intentionally not required to be
# reachable from README.md or docs/README.md.
_INTERNAL_DOC_ALLOWLIST = frozenset(
    {
        ROOT / "benchmarks" / "route_accuracy" / "data" / "README.md",
    }
)


def test_every_docs_file_is_discoverable() -> None:
    index = (ROOT / "docs" / "README.md").read_text().lower()
    readme = README.read_text().lower()
    paths = [
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / "docs" / "maintainers").glob("*.md"),
    ]
    for path in sorted(paths):
        if path in _INTERNAL_DOC_ALLOWLIST or path.name == "README.md":
            continue
        rel = path.name.lower()
        assert rel in index or rel in readme, f"orphaned doc: {path}"


def test_documentation_uses_neutral_technical_language() -> None:
    prohibited = (
        "production-grade",
        "migration tax",
        "classic silent",
        "evidence, not leaderboard theatre",
        "realistic-looking",
        "pessimistic bound",
        "earns its place",
    )
    documentation = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in MARKDOWN_FILES
    )
    for phrase in prohibited:
        assert phrase not in documentation


def test_release_metadata_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

    citation_match = re.search(r"^version:\s*([^\s]+)\s*$", citation, re.MULTILINE)
    assert citation_match is not None
    locked_package = next(
        package for package in lock["package"] if package["name"] == "harborly"
    )

    versions = {
        project["project"]["version"],
        locked_package["version"],
        citation_match.group(1),
    }
    assert len(versions) == 1, f"inconsistent release metadata: {sorted(versions)}"
