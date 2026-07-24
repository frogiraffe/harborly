from __future__ import annotations

import argparse
import json
from pathlib import Path

from sea_mile.build import build_reference_registry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "src" / "sea_mile" / "data"
BUNDLED_PROVIDERS = ("NGA_WPI", "GEONAMES")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the WPI and GeoNames registry distributed with sea-mile."
    )
    parser.add_argument(
        "reference_root",
        type=Path,
        help="directory containing raw source snapshots and manifest.json",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = build_reference_registry(
        args.reference_root,
        providers=BUNDLED_PROVIDERS,
        output_directory=args.output,
    )
    source_manifest = json.loads(
        (args.reference_root / "manifest.json").read_text(encoding="utf-8")
    )
    raw_sources = source_manifest["sources"]
    manifest["distribution"] = {
        "type": "bundled",
        "sources": {
            "NGA_WPI": raw_sources["wpi"],
            "GEONAMES": raw_sources["geonames"],
        },
    }
    (args.output / "registry_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
