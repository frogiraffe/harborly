from __future__ import annotations

import json
from pathlib import Path

import pytest

from sea_mile.cli import main
from sea_mile.exceptions import SourceDataError
from sea_mile.source_data import lock_mismatches, sha256, write_source_lock


def _seed_manifest(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "wpi.csv"
    source.write_text("port\nMersin\n", encoding="utf-8")
    manifest = {
        "retrieved_at_utc": "2026-07-23T00:00:00+00:00",
        "sources": {
            "wpi": {
                "url": "https://example.invalid/wpi.csv",
                "snapshot_label": "2026-07-23",
                "path": "wpi.csv",
                "sha256": sha256(source),
                "bytes": source.stat().st_size,
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return source


def test_write_source_lock_pins_the_manifest_sources(tmp_path) -> None:
    _seed_manifest(tmp_path)

    lock = write_source_lock(tmp_path)

    assert (tmp_path / "sea-mile.lock.json").exists()
    assert lock["lock_version"] == 1
    assert lock["sources"]["wpi"]["path"] == "wpi.csv"


def test_write_source_lock_without_a_manifest_errors(tmp_path) -> None:
    with pytest.raises(SourceDataError, match="run data download first"):
        write_source_lock(tmp_path)


def test_lock_mismatches_detects_a_changed_source(tmp_path) -> None:
    source = _seed_manifest(tmp_path)
    lock = write_source_lock(tmp_path)

    assert lock_mismatches(tmp_path, lock) == []

    source.write_text("port\nChanged\n", encoding="utf-8")
    assert lock_mismatches(tmp_path, lock) == ["wpi: sha256 differs from the lock"]


def test_lock_mismatches_detects_a_missing_source(tmp_path) -> None:
    source = _seed_manifest(tmp_path)
    lock = write_source_lock(tmp_path)
    source.unlink()

    assert lock_mismatches(tmp_path, lock) == ["wpi: missing local file wpi.csv"]


def test_data_lock_cli_writes_a_lockfile(tmp_path, capsys) -> None:
    _seed_manifest(tmp_path)

    status = main(["data", "lock", "--reference-root", str(tmp_path), "--json"])

    assert status == 0
    lock = json.loads(capsys.readouterr().out)["data"]
    assert lock["sources"]["wpi"]["path"] == "wpi.csv"
    assert (tmp_path / "sea-mile.lock.json").exists()


def test_data_build_with_lock_mismatch_errors_before_building(tmp_path, capsys) -> None:
    source = _seed_manifest(tmp_path)
    write_source_lock(tmp_path)
    source.unlink()  # the lock no longer matches the local files

    status = main(
        [
            "data",
            "build",
            "--reference-root",
            str(tmp_path),
            "--lock",
            str(tmp_path / "sea-mile.lock.json"),
        ]
    )

    assert status == 2
    assert "source lock mismatch" in capsys.readouterr().err
