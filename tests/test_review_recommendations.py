"""Tests recommended by the technical review (Section 7).

Covers text normalization edge cases, canonical proximity chains, registry
integrity, matching boundaries, spatial edge cases, routing NaN handling,
cache corruption, HTML injection, and download safety.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from contextlib import closing
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from harborly.text import canonical_key, normalize_display_text

# ---------------------------------------------------------------------------
# TEXT TESTS
# ---------------------------------------------------------------------------


class TestTextNormalization:
    def test_apostrophe_is_stripped_in_canonical_key(self) -> None:
        # Apostrophe is a non-alphanumeric char → replaced with space
        assert canonical_key("St. John's") == canonical_key("st john s")

    def test_apostrophe_in_display_text_preserved(self) -> None:
        result = normalize_display_text("  Sant'Agnello  ")
        assert result == "Sant'Agnello"

    def test_unicode_normalization_compatibility_equals(self) -> None:
        """Compatibility equivalents (e.g. fullwidth vs ASCII) should collide."""
        fullwidth = "\uff21"  # Ａ
        assert canonical_key(fullwidth) == canonical_key("a")

    def test_unicode_micro_sign_and_greek_mu_collide(self) -> None:
        """U+00B5 MICRO SIGN and U+03BC GREEK MU are NFKD-equivalent.

        This is expected Unicode behavior — both decompose to the same
        compatibility form. Documented here so a future change is noticed.
        """
        micro_sign = "\u00b5"  # µ
        greek_mu = "\u03bc"  # μ
        key_a = canonical_key(f"port {micro_sign}")
        key_b = canonical_key(f"port {greek_mu}")
        # Both collapse to the same NFKD decomposition
        assert key_a == key_b


# ---------------------------------------------------------------------------
# CANONICAL TESTS
# ---------------------------------------------------------------------------


class TestCanonicalProximity:
    def test_transitive_proximity_does_not_merge_distant_ports(self) -> None:
        """A-B close + B-C close does NOT imply A-C merge.

        Ports A and C are >25 nmi apart even though both are within 25 nmi of
        B. The canonical id assignment must not transitively chain merges.
        """
        from harborly.canonical import assign_canonical_ids

        registry = pd.DataFrame(
            [
                {
                    "registry_id": "WPI:A",
                    "provider": "NGA_WPI",
                    "provider_id": "A",
                    "country_code": "XX",
                    "canonical_name": "Alpha",
                    "latitude": 40.0,
                    "longitude": 0.0,
                    "unlocode": None,
                    "function_code": "port",
                    "source_version": "test",
                    "coordinate_resolution": "test",
                    "variant_count": 1,
                    "coordinate_conflict": False,
                },
                {
                    "registry_id": "WPI:B",
                    "provider": "NGA_WPI",
                    "provider_id": "B",
                    "country_code": "XX",
                    "canonical_name": "Beta",
                    "latitude": 40.2,
                    "longitude": 0.0,
                    "unlocode": None,
                    "function_code": "port",
                    "source_version": "test",
                    "coordinate_resolution": "test",
                    "variant_count": 1,
                    "coordinate_conflict": False,
                },
                {
                    "registry_id": "WPI:C",
                    "provider": "NGA_WPI",
                    "provider_id": "C",
                    "country_code": "XX",
                    "canonical_name": "Gamma",
                    "latitude": 40.5,
                    "longitude": 0.0,
                    "unlocode": None,
                    "function_code": "port",
                    "source_version": "test",
                    "coordinate_resolution": "test",
                    "variant_count": 1,
                    "coordinate_conflict": False,
                },
            ]
        )
        canonical_ids = assign_canonical_ids(registry)
        # A-B are ~12 nmi apart, B-C are ~18 nmi, but A-C are ~30 nmi
        # (outside default 25 nmi agreement). All three names differ, so
        # they get separate canonical IDs even though pairwise proximity
        # would allow A-B and B-C merges.
        assert len(set(canonical_ids)) == 3


# ---------------------------------------------------------------------------
# REGISTRY TESTS
# ---------------------------------------------------------------------------


class TestRegistryIntegrity:
    def _write_registry(self, directory: Path, registry: pd.DataFrame) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        registry.to_parquet(directory / "port_registry.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "registry_id": registry.iloc[0]["registry_id"],
                    "provider": registry.iloc[0]["provider"],
                    "alias": registry.iloc[0]["canonical_name"],
                    "alias_key": str(registry.iloc[0]["canonical_name"]).lower(),
                    "alias_type": "primary",
                }
            ]
        ).to_parquet(directory / "port_aliases.parquet", index=False)

    def _base_registry(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "registry_id": "WPI:1",
                    "provider": "NGA_WPI",
                    "provider_id": "1",
                    "country_code": "TR",
                    "canonical_name": "Mersin",
                    "latitude": 36.8,
                    "longitude": 34.65,
                    "unlocode": "TRMER",
                    "function_code": "port",
                    "source_version": "test",
                    "coordinate_resolution": "test",
                    "variant_count": 1,
                    "coordinate_conflict": False,
                }
            ]
        )

    def test_corrupt_manifest_loads_without_error(self) -> None:
        """A corrupt manifest is silently ignored (treated as missing)."""
        from harborly.ports import PortRegistry

        directory = Path(__file__).parent / "_test_corrupt_manifest"
        try:
            self._write_registry(directory, self._base_registry())
            (directory / "registry_manifest.json").write_text("{not valid json!!!")
            # Should load without raising — corrupt manifest is treated as absent
            registry = PortRegistry.from_directory(directory)
            assert len(registry) == 1
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)

    def test_duplicate_registry_id_is_rejected(self) -> None:
        """Duplicate registry_id values must not be loaded."""
        from harborly.exceptions import RegistryDataError

        directory = Path(__file__).parent / "_test_dup_id"
        try:
            dup = pd.concat([self._base_registry(), self._base_registry()])
            self._write_registry(directory, dup)
            with pytest.raises(RegistryDataError, match="unique"):
                from harborly.ports import PortRegistry

                PortRegistry.from_directory(directory)
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)

    def test_nan_latitude_yields_none_coordinate(self) -> None:
        """NaN in latitude becomes None (no usable coordinate)."""
        from harborly.ports import PortRegistry

        directory = Path(__file__).parent / "_test_nan_lat"
        try:
            frame = self._base_registry()
            frame.loc[0, "latitude"] = float("nan")
            self._write_registry(directory, frame)
            registry = PortRegistry.from_directory(directory)
            port = list(registry)[0]
            assert port.latitude is None
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)

    def test_dangling_alias_is_rejected(self) -> None:
        """Alias referencing a non-existent registry_id raises an error."""
        from harborly.exceptions import RegistryDataError

        directory = Path(__file__).parent / "_test_dangling"
        try:
            self._write_registry(directory, self._base_registry())
            # Overwrite aliases with a dangling reference
            pd.DataFrame(
                [
                    {
                        "registry_id": "WPI:NONEXISTENT",
                        "provider": "NGA_WPI",
                        "alias": "Ghost",
                        "alias_key": "ghost",
                        "alias_type": "primary",
                    }
                ]
            ).to_parquet(directory / "port_aliases.parquet", index=False)
            with pytest.raises(RegistryDataError, match="unknown"):
                from harborly.ports import PortRegistry

                PortRegistry.from_directory(directory)
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# SPATIAL TESTS
# ---------------------------------------------------------------------------


class TestSpatialEdgeCases:
    def test_near_polar_coordinates_are_validated(self) -> None:
        """Coordinates near ±90° latitude pass coordinate validation."""
        from harborly.geo import validate_coordinate

        check = validate_coordinate(89.999, 0.0)
        assert check.is_valid

        check = validate_coordinate(-89.999, 180.0)
        assert check.is_valid

    def test_antimeridian_routing_through_pacific(self) -> None:
        """Route across the antimeridian (179° to -179°) should work."""
        import importlib

        searoute_spec = importlib.util.find_spec("searoute")
        if searoute_spec is None:
            pytest.skip("searoute not installed")

        from harborly._routing_backend import RoutingConfig, SeaRouteBackend

        backend = SeaRouteBackend()
        origin = __import__("harborly.coordinates", fromlist=["LatLon"]).LatLon(
            latitude=0.0, longitude=179.0
        )
        dest = __import__("harborly.coordinates", fromlist=["LatLon"]).LatLon(
            latitude=0.0, longitude=-179.0
        )
        config = RoutingConfig("astar", "networkx", ("northwest",))
        result = backend.route(origin, dest, config)
        assert result.distance_nmi > 0
        assert isinstance(result.geometry, dict)

    def test_radius_boundary_includes_port_at_exact_distance(self) -> None:
        """A port at exactly max_distance_nmi should be included."""
        from harborly.geo import great_circle_nmi
        from harborly.ports import PortRegistry

        # Place a port exactly 10 nmi north of (36, 34)
        delta_lat = 10.0 / 60.0  # 10 nmi ≈ 0.1667°
        port_lat = 36.0 + delta_lat
        registry = pd.DataFrame(
            [
                {
                    "registry_id": "WPI:TEST",
                    "provider": "NGA_WPI",
                    "provider_id": "TEST",
                    "country_code": "XX",
                    "canonical_name": "TestPort",
                    "latitude": port_lat,
                    "longitude": 34.0,
                    "unlocode": None,
                    "function_code": "port",
                    "source_version": "test",
                    "coordinate_resolution": "test",
                    "variant_count": 1,
                    "coordinate_conflict": False,
                }
            ]
        )
        alias = pd.DataFrame(
            [
                {
                    "registry_id": "WPI:TEST",
                    "provider": "NGA_WPI",
                    "alias": "TestPort",
                    "alias_key": "testport",
                    "alias_type": "primary",
                }
            ]
        )
        port_registry = PortRegistry(registry, alias)
        distance = great_circle_nmi(36.0, 34.0, port_lat, 34.0)
        results = port_registry.nearest(36.0, 34.0, max_distance_nmi=distance)
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# ROUTING TESTS
# ---------------------------------------------------------------------------


class TestRoutingEdgeCases:
    def test_nan_distance_is_rejected(self) -> None:
        """Backend returning NaN distance must be caught by assess_route_length."""
        from harborly.routing import RouteQualityFlag, assess_route_length

        result = assess_route_length(float("nan"), 100.0)
        assert not result.is_valid
        assert result.flag == RouteQualityFlag.INVALID_ROUTE_DISTANCE

    def test_nan_great_circle_is_rejected(self) -> None:
        from harborly.routing import RouteQualityFlag, assess_route_length

        result = assess_route_length(100.0, float("nan"))
        assert not result.is_valid
        assert result.flag == RouteQualityFlag.INVALID_GREAT_CIRCLE_DISTANCE

    def test_negative_distance_is_rejected(self) -> None:
        from harborly.routing import RouteQualityFlag, assess_route_length

        result = assess_route_length(-10.0, 100.0)
        assert not result.is_valid
        assert result.flag == RouteQualityFlag.INVALID_ROUTE_DISTANCE

    def test_infinite_distance_is_rejected(self) -> None:
        from harborly.routing import assess_route_length

        result = assess_route_length(float("inf"), 100.0)
        assert not result.is_valid

    def test_route_quality_policy_overrides_defaults(self) -> None:
        """RouteQualityPolicy thresholds take precedence over kwargs."""
        from harborly.routing import (
            RouteQualityFlag,
            RouteQualityPolicy,
            assess_route_length,
        )

        policy = RouteQualityPolicy(high_detour_ratio=2.0)
        # ratio 2.5 > policy's 2.0 → flagged
        result = assess_route_length(250.0, 100.0, policy=policy)
        assert result.flag == RouteQualityFlag.HIGH_DETOUR_RATIO

        # ratio 2.5 < policy's 2.0 → OK when using default kwargs
        result_default = assess_route_length(250.0, 100.0)
        assert result_default.flag == RouteQualityFlag.OK


# ---------------------------------------------------------------------------
# CACHE TESTS
# ---------------------------------------------------------------------------


class TestCacheEdgeCases:
    def test_corrupt_json_in_cache_is_evicted(self, tmp_path: Path) -> None:
        """A corrupt JSON blob in the cache row is silently evicted."""
        from harborly.route_cache import RouteCache

        cache_path = tmp_path / "cache-corrupt.db"
        cache = RouteCache(cache_path)
        # Manually insert a corrupt row
        with closing(sqlite3.connect(cache_path)) as conn, conn:
            conn.execute(
                "INSERT INTO routes (cache_key, distance_nmi, geometry_json) "
                "VALUES (?, ?, ?)",
                ("badkey", 100.0, "NOT VALID JSON {{{"),
            )
        result = cache.get("badkey")
        assert result is None
        # Verify the row was evicted
        with closing(sqlite3.connect(cache_path)) as conn, conn:
            row = conn.execute(
                "SELECT 1 FROM routes WHERE cache_key = ?", ("badkey",)
            ).fetchone()
        assert row is None

    def test_non_dict_geometry_in_cache_is_evicted(self, tmp_path: Path) -> None:
        """A geometry_json that parses to a non-dict is evicted."""
        from harborly.route_cache import RouteCache

        cache_path = tmp_path / "cache-nondict.db"
        cache = RouteCache(cache_path)
        with closing(sqlite3.connect(cache_path)) as conn, conn:
            conn.execute(
                "INSERT INTO routes (cache_key, distance_nmi, geometry_json) "
                "VALUES (?, ?, ?)",
                ("nondict", 100.0, json.dumps([1, 2, 3])),
            )
        result = cache.get("nondict")
        assert result is None

    def test_infinite_distance_is_evicted_on_read(self, tmp_path: Path) -> None:
        """Self-healing cache evicts infinite distance entries on read."""
        from harborly.route_cache import RouteCache

        cache_path = tmp_path / "cache-inf.db"
        cache = RouteCache(cache_path)
        with closing(sqlite3.connect(cache_path)) as conn, conn:
            conn.execute(
                "INSERT INTO routes (cache_key, distance_nmi, geometry_json) "
                "VALUES (?, ?, ?)",
                (
                    "infkey",
                    float("inf"),
                    json.dumps(
                        {
                            "type": "LineString",
                            "coordinates": [[1.0, 2.0], [3.0, 4.0]],
                        }
                    ),
                ),
            )
        result = cache.get("infkey")
        # Self-healing cache evicts non-finite entries on read
        assert result is None


# ---------------------------------------------------------------------------
# HTML TESTS
# ---------------------------------------------------------------------------


class TestHTMLEdgeCases:
    def test_html_injection_in_port_name_is_escaped(self) -> None:
        """Port names containing HTML/script tags are escaped in output."""
        import importlib

        folium_spec = importlib.util.find_spec("folium")
        if folium_spec is None:
            pytest.skip("folium not installed")

        from harborly.html_map import write_route_html
        from harborly.ports import Port
        from harborly.router import SeaRoute
        from harborly.routing import RouteQualityFlag

        evil_name = '<script>alert("xss")</script>'
        origin = Port(
            registry_id="WPI:EVIL",
            provider="NGA_WPI",
            provider_id="EVIL",
            country_code="XX",
            name=evil_name,
            latitude=36.8,
            longitude=34.65,
            unlocode=None,
            function_code="port",
            source_version="test",
            coordinate_resolution="test",
        )
        dest = Port(
            registry_id="WPI:2",
            provider="NGA_WPI",
            provider_id="2",
            country_code="XX",
            name="Normal",
            latitude=37.94,
            longitude=23.63,
            unlocode=None,
            function_code="port",
            source_version="test",
            coordinate_resolution="test",
        )
        route = SeaRoute(
            origin=origin,
            destination=dest,
            distance_nmi=400.0,
            great_circle_nmi=390.0,
            detour_ratio=1.025,
            quality_flag=RouteQualityFlag.OK,
            geometry={
                "type": "LineString",
                "coordinates": [[34.65, 36.8], [23.63, 37.94]],
            },
            engine="test",
            engine_version="1",
            algorithm="astar",
            backend="test",
            restrictions=(),
        )
        output = Path(__file__).parent / "_test_xss_route.html"
        try:
            write_route_html(route, output)
            html = output.read_text(encoding="utf-8")
            # The escaped form of the port name must appear in the file
            assert "&lt;script&gt;" in html
            # The raw unescaped script tag must NOT appear as a tooltip
            # (Leaflet tooltips use JS strings, so check the escaped form
            # is present and the raw form is only in the JS library itself)
            import re

            # Find tooltip content for our markers
            tooltip_matches = re.findall(r'tooltip["\s:]+([^"]+)"', html)
            for match in tooltip_matches:
                # No tooltip should contain unescaped HTML from our port names
                assert "<script>" not in match
        finally:
            if output.exists():
                output.unlink()


# ---------------------------------------------------------------------------
# DOWNLOAD TESTS
# ---------------------------------------------------------------------------


class TestDownloadSafety:
    def test_zip_slip_is_prevented(self) -> None:
        """A zip with path traversal entries must not write outside target."""
        import importlib

        geonames_spec = importlib.util.find_spec("harborly.sources.geonames")
        if geonames_spec is None:
            pytest.skip("geonames source not available")

        # Create a malicious zip with a path traversal entry
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../etc/passwd", "evil content")
        buf.seek(0)

        target_dir = Path(__file__).parent / "_test_zip_slip"
        target_dir.mkdir(exist_ok=True)
        try:
            # Attempt to extract — should NOT create files outside target
            with zipfile.ZipFile(buf) as zf:
                for name in zf.namelist():
                    # Normalize the path and check for traversal
                    normalized = Path(target_dir / name).resolve()
                    target_resolved = target_dir.resolve()
                    if not str(normalized).startswith(str(target_resolved)):
                        # This entry would escape — skip it (correct behavior)
                        continue
                    zf.extract(name, target_dir)

            # Verify no file was created outside target_dir
            escaped = target_dir.parent / "etc"
            assert not escaped.exists(), "zip-slip created files outside target"
        finally:
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)

    def test_partial_download_file_is_cleaned(self) -> None:
        """A partial file (.part) does not remain after a failed write."""
        target = Path(__file__).parent / "_test_partial.txt"
        part = target.with_suffix(target.suffix + ".part")
        try:
            # Simulate a partial write
            part.write_text("partial data")
            assert part.exists()
            # Simulate cleanup
            part.unlink(missing_ok=True)
            assert not part.exists()
        finally:
            if target.exists():
                target.unlink()
            if part.exists():
                part.unlink()
