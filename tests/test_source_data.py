from __future__ import annotations

import json

from sea_mile.build.download import download_reference_data, sha256


def test_existing_snapshots_produce_checksum_manifest_without_network(tmp_path) -> None:
    snapshot = "2099-01-02"
    files = {
        "wpi": tmp_path / "raw" / "wpi" / snapshot / "UpdatedPub150.csv",
        "unlocode": (
            tmp_path / "raw" / "unlocode" / "2025-1" / "unlocode-2025-1-artifacts.zip"
        ),
        "geonames": (tmp_path / "raw" / "geonames" / snapshot / "allCountries.zip"),
    }
    for name, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())

    manifest = download_reference_data(tmp_path, snapshot_label=snapshot)
    saved = json.loads((tmp_path / "manifest.json").read_text())

    assert saved == manifest
    sources = manifest["sources"]
    assert isinstance(sources, dict)
    assert sources["geonames"]["license"] == "CC BY 4.0"
    assert sources["wpi"]["sha256"] == sha256(files["wpi"])


def _seed_snapshots(root, wpi_label: str, geonames_label: str) -> None:
    targets = {
        root / "raw" / "wpi" / wpi_label / "UpdatedPub150.csv": b"wpi",
        root
        / "raw"
        / "unlocode"
        / "2025-1"
        / "unlocode-2025-1-artifacts.zip": b"unlocode",
        root / "raw" / "geonames" / geonames_label / "allCountries.zip": b"geonames",
    }
    for path, payload in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def test_reuses_existing_snapshot_without_network(tmp_path, monkeypatch) -> None:
    _seed_snapshots(tmp_path, "2020-01-01", "2020-01-01")

    def fail(*args, **kwargs):
        raise AssertionError("no download expected when a snapshot already exists")

    monkeypatch.setattr("sea_mile.build.download._download", fail)

    manifest = download_reference_data(tmp_path)
    sources = manifest["sources"]

    assert sources["wpi"]["path"] == "raw/wpi/2020-01-01/UpdatedPub150.csv"
    assert sources["geonames"]["path"] == "raw/geonames/2020-01-01/allCountries.zip"
    assert sources["wpi"]["snapshot_label"] == "2020-01-01"


def test_reused_snapshot_keeps_manifest_checksum_without_rehashing(
    tmp_path, monkeypatch
) -> None:
    _seed_snapshots(tmp_path, "2020-01-01", "2020-01-01")

    def fail(*args, **kwargs):
        raise AssertionError("no download expected")

    monkeypatch.setattr("sea_mile.build.download._download", fail)
    first = download_reference_data(tmp_path)

    calls: list = []

    def counting_sha256(path):
        calls.append(path)
        return "unexpected"

    monkeypatch.setattr("sea_mile.build.download.sha256", counting_sha256)
    second = download_reference_data(tmp_path)

    assert calls == []
    assert (
        second["sources"]["geonames"]["sha256"]
        == first["sources"]["geonames"]["sha256"]
    )


def test_explicit_snapshot_label_downloads_into_that_label(
    tmp_path, monkeypatch
) -> None:
    _seed_snapshots(tmp_path, "2020-01-01", "2020-01-01")
    calls: list = []

    def fake_download(client, url, destination) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fresh")
        calls.append(destination)

    monkeypatch.setattr("sea_mile.build.download._download", fake_download)
    manifest = download_reference_data(tmp_path, snapshot_label="2099-12-31")
    sources = manifest["sources"]

    assert sources["wpi"]["path"] == "raw/wpi/2099-12-31/UpdatedPub150.csv"
    assert sources["geonames"]["path"] == "raw/geonames/2099-12-31/allCountries.zip"
    assert any("2099-12-31" in str(path) for path in calls)


def test_refresh_redownloads_into_new_folder(tmp_path, monkeypatch) -> None:
    _seed_snapshots(tmp_path, "2020-01-01", "2020-01-01")
    calls: list = []

    def fake_download(client, url, destination) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fresh")
        calls.append(destination)

    monkeypatch.setattr("sea_mile.build.download._download", fake_download)

    manifest = download_reference_data(
        tmp_path, snapshot_label="2099-12-31", refresh=True
    )
    sources = manifest["sources"]

    assert len(calls) == 3
    assert sources["wpi"]["path"] == "raw/wpi/2099-12-31/UpdatedPub150.csv"
    assert sources["geonames"]["path"] == "raw/geonames/2099-12-31/allCountries.zip"
    assert (
        sources["unlocode"]["path"]
        == "raw/unlocode/2025-1/unlocode-2025-1-artifacts.zip"
    )
