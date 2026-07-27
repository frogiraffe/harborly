from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "normalize_sdist",
    Path(__file__).resolve().parents[1] / "scripts" / "normalize_sdist.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
normalize_sdist = _MODULE.normalize_sdist


def _write_archive(path: Path, *, mtime: int, reverse: bool) -> None:
    entries = [("package/a.txt", b"a"), ("package/b.txt", b"b")]
    if reverse:
        entries.reverse()
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=mtime) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, content in entries:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mtime = mtime
            member.uid = mtime
            archive.addfile(member, io.BytesIO(content))


def test_normalized_sdists_are_byte_identical(tmp_path) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    _write_archive(first, mtime=100, reverse=False)
    _write_archive(second, mtime=200, reverse=True)

    normalize_sdist(first, epoch=42)
    normalize_sdist(second, epoch=42)

    assert (
        hashlib.sha256(first.read_bytes()).digest()
        == hashlib.sha256(second.read_bytes()).digest()
    )
