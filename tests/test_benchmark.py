from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import sea_mile.ports

BENCHMARK = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"

_STAGES = (
    "build registry",
    "search exact",
    "search fuzzy",
    "search_grouped",
    "nearest",
    "peak memory",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sea_mile_benchmark", BENCHMARK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_reports_every_stage(capsys: pytest.CaptureFixture[str]) -> None:
    _load().main(["400"])
    printed = capsys.readouterr().out
    for stage in _STAGES:
        assert stage in printed, stage


def test_benchmark_scan_path_runs_without_the_kdtree(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = sea_mile.ports.cKDTree
    try:
        _load().main(["400", "--no-kdtree"])
    finally:
        sea_mile.ports.cKDTree = original
    printed = capsys.readouterr().out
    assert "scan only" in printed
    assert "nearest" in printed
