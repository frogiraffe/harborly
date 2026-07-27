#!/usr/bin/env python3
"""Normalize an sdist archive for byte-for-byte reproducible releases."""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import os
import tarfile
import tempfile
from pathlib import Path
from typing import IO


def _payload(source: tarfile.TarFile, member: tarfile.TarInfo) -> bytes | None:
    if not member.isfile():
        return None
    extracted: IO[bytes] | None = source.extractfile(member)
    if extracted is None:
        raise ValueError(f"could not read {member.name!r} from the sdist")
    return extracted.read()


def normalize_sdist(path: Path, *, epoch: int) -> None:
    """Rewrite one gzip-compressed tar archive with deterministic metadata."""

    with tarfile.open(path, "r:gz") as source:
        entries = [
            (copy.copy(member), _payload(source, member))
            for member in source.getmembers()
        ]

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with (
            temporary.open("wb") as raw,
            gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=epoch,
            ) as compressed,
            tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as target,
        ):
            for member, payload in sorted(entries, key=lambda item: item[0].name):
                member.uid = 0
                member.gid = 0
                member.uname = ""
                member.gname = ""
                member.mtime = epoch
                member.pax_headers = {}
                target.addfile(
                    member,
                    io.BytesIO(payload) if payload is not None else None,
                )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument(
        "--epoch",
        type=int,
        default=None,
        help="Unix timestamp (default: SOURCE_DATE_EPOCH)",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    epoch = args.epoch
    if epoch is None:
        value = os.environ.get("SOURCE_DATE_EPOCH")
        if value is None:
            raise SystemExit("--epoch or SOURCE_DATE_EPOCH is required")
        epoch = int(value)
    for archive in args.archives:
        normalize_sdist(archive, epoch=epoch)


if __name__ == "__main__":
    main()
