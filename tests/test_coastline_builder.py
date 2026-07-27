from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_coastline",
    Path(__file__).resolve().parents[1] / "scripts" / "build_coastline.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
NE_REQUIRED_FILES = _MODULE.NE_REQUIRED_FILES
_required_archive_members = _MODULE._required_archive_members


def _archive(names: tuple[str, ...]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, name)
    return buffer.getvalue()


def test_coastline_archive_reads_only_expected_members() -> None:
    data = _archive((*NE_REQUIRED_FILES, "../../escape.txt"))

    members = _required_archive_members(data)

    assert set(members) == set(NE_REQUIRED_FILES)
    assert "../../escape.txt" not in members


def test_coastline_archive_requires_complete_shapefile() -> None:
    with pytest.raises(ValueError, match="is missing"):
        _required_archive_members(_archive(NE_REQUIRED_FILES[:-1]))
