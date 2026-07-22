from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

import sea_mile
from sea_mile.cli import _parser

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
LIBRARY_API = ROOT / "docs" / "LIBRARY_API.md"


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
    missing = [name for name in sea_mile.__all__ if name.lower() not in docs]
    assert not missing, f"undocumented public exports: {missing}"


def _example_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    for block in re.findall(r"```bash\n(.*?)```", README.read_text(), re.DOTALL):
        for line in block.splitlines():
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            if tokens[:3] == ["uv", "run", "sea-mile"]:
                commands.append(tokens[3:])
            elif tokens[:1] == ["sea-mile"]:
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

    # export selects output with --format, and tui is interactive. Neither emits
    # the machine-readable JSON that --json promises, so they must not accept it.
    assert not _has_json_option(commands["export"])
    assert not _has_json_option(commands["tui"])

    for name in ("info", "search", "show", "near", "match", "route", "matrix"):
        assert _has_json_option(commands[name]), name

    data_commands = _subcommands(commands["data"])
    for name in ("download", "build", "prepare", "verify"):
        assert _has_json_option(data_commands[name]), name


def test_readme_scopes_json_and_documents_exit_codes() -> None:
    readme = README.read_text().lower()

    # The blanket "JSON on every command" claim was false and must not come back.
    assert "from every command" not in readme
    assert "after any command" not in readme

    # Exit codes are part of the CLI contract, so they must be documented.
    assert "exit code" in readme
