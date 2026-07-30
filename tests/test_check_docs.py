"""Unit tests for the conservative documentation prose linter."""

from __future__ import annotations

from pathlib import Path

from scripts.check_docs import (
    check_pypi_readme_links,
    check_text,
    iter_markdown_files,
    main,
)


def test_flags_byte_identical() -> None:
    findings = check_text(Path("doc.md"), "The output is byte identical across runs.\n")
    assert any(
        f.label == "byte-identical" and f.category == "forbidden" for f in findings
    )


def test_flags_bit_for_bit_with_hyphens() -> None:
    findings = check_text(Path("doc.md"), "Results are bit-for-bit reproducible.\n")
    assert any(f.label == "bit-for-bit" for f in findings)


def test_flags_humanized() -> None:
    findings = check_text(
        Path("doc.md"), "This paragraph was humanized by an editor.\n"
    )
    assert any(f.label == "humanized" for f in findings)


def test_forbidden_hit_reports_correct_line_number() -> None:
    text = "line one\nline two\nbyte identical here\n"
    findings = check_text(Path("doc.md"), text)
    forbidden = [f for f in findings if f.category == "forbidden"]
    assert len(forbidden) == 1
    assert forbidden[0].line == 3


def test_clean_technical_prose_has_no_findings() -> None:
    text = (
        "# API reference\n\n"
        "`GET /v1/route` returns nautical-mile distance and GeoJSON geometry.\n"
        "The response schema is documented above with exact field names.\n"
    )
    assert check_text(Path("doc.md"), text) == []


def test_duplicated_conclusion_needs_two_occurrences() -> None:
    single = "Some analysis.\n\nIn conclusion, it works.\n"
    assert not any(
        f.label == "duplicated-conclusion" for f in check_text(Path("d.md"), single)
    )

    doubled = "In summary, it works.\n\nMore text.\n\nIn conclusion, it really works.\n"
    findings = check_text(Path("d.md"), doubled)
    assert sum(1 for f in findings if f.label == "duplicated-conclusion") == 2


def test_vague_attribution_and_inflated_claim_are_smells_not_forbidden() -> None:
    text = "Many experts believe this is a game-changing, cutting-edge approach.\n"
    findings = check_text(Path("doc.md"), text)
    assert findings
    assert all(f.category == "smell" for f in findings)


def test_iter_markdown_files_skips_excluded_dirs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    ignored_dir = tmp_path / ".venv" / "lib"
    ignored_dir.mkdir(parents=True)
    (ignored_dir / "README.md").write_text("byte identical\n", encoding="utf-8")

    files = iter_markdown_files([tmp_path])
    assert (tmp_path / "docs" / "guide.md") in files
    assert not any(".venv" in f.parts for f in files)


def test_iter_markdown_files_tolerates_missing_root(tmp_path: Path) -> None:
    assert iter_markdown_files([tmp_path / "does-not-exist"]) == []


def test_iter_markdown_files_skips_superpowers_plans(tmp_path: Path) -> None:
    plans_dir = tmp_path / "docs" / "superpowers" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "plan.md").write_text("byte identical\n", encoding="utf-8")

    assert iter_markdown_files([tmp_path]) == []


def test_pypi_guard_rejects_relative_file_link() -> None:
    findings = check_pypi_readme_links(
        Path("README.md"), "See [docs](docs/GUIDE.md) for more.\n"
    )
    assert any(f.label == "pypi-link-relative" for f in findings)
    assert all(f.category == "forbidden" for f in findings)


def test_pypi_guard_rejects_relative_image() -> None:
    findings = check_pypi_readme_links(
        Path("README.md"), "![diagram](images/diagram.png)\n"
    )
    assert any(f.label == "pypi-image-relative" for f in findings)


def test_pypi_guard_rejects_relative_reference_style_link() -> None:
    text = "See [docs][guide].\n\n[guide]: docs/GUIDE.md\n"
    findings = check_pypi_readme_links(Path("README.md"), text)
    assert any(f.label == "pypi-link-relative" for f in findings)


def test_pypi_guard_allows_absolute_github_url() -> None:
    text = (
        "See [docs](https://github.com/frogiraffe/sea-mile/blob/main/docs/GUIDE.md).\n"
    )
    assert check_pypi_readme_links(Path("README.md"), text) == []


def test_pypi_guard_allows_valid_same_document_anchor() -> None:
    text = "# Installation\n\nSee [installation](#installation) above.\n"
    assert check_pypi_readme_links(Path("README.md"), text) == []


def test_pypi_guard_rejects_missing_same_document_anchor() -> None:
    text = "# Installation\n\nSee [usage](#usage) above.\n"
    findings = check_pypi_readme_links(Path("README.md"), text)
    assert any(f.label == "pypi-link-broken-anchor" for f in findings)


def test_pypi_guard_ignores_markdown_inside_fenced_code_blocks() -> None:
    text = "Example:\n\n```markdown\n[docs](docs/GUIDE.md)\n```\n"
    assert check_pypi_readme_links(Path("README.md"), text) == []


def test_pypi_guard_allows_mailto_and_http() -> None:
    text = (
        "Contact [us](mailto:security@example.com) or read "
        "[this](http://example.com/notice).\n"
    )
    assert check_pypi_readme_links(Path("README.md"), text) == []


def test_main_returns_nonzero_only_for_forbidden_hits(tmp_path: Path) -> None:
    clean = tmp_path / "clean.md"
    clean.write_text("Plain technical prose with no issues.\n", encoding="utf-8")
    assert main([str(clean)]) == 0

    smelly = tmp_path / "smelly.md"
    smelly.write_text("This is a cutting-edge, seamless solution.\n", encoding="utf-8")
    assert main([str(smelly)]) == 0

    forbidden = tmp_path / "forbidden.md"
    forbidden.write_text("The output is byte identical.\n", encoding="utf-8")
    assert main([str(forbidden)]) == 1
