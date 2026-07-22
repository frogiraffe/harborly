import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sea_mile.matching import decide_exact_match, generate_source_aware_candidates


class ExactMatchingTests(unittest.TestCase):
    def test_unique_wpi_match_is_tier_a(self):
        result = decide_exact_match(["WPI:1"], ["UNLOCODE:XXAAA"])
        self.assertEqual(result.status, "auto_resolved")
        self.assertEqual(result.confidence_tier, "A")
        self.assertEqual(result.selected_registry_id, "WPI:1")

    def test_multiple_wpi_matches_require_review(self):
        result = decide_exact_match(["WPI:1", "WPI:2"], [])
        self.assertEqual(result.status, "review_required")
        self.assertIsNone(result.selected_registry_id)

    def test_unique_unlocode_match_is_tier_b(self):
        result = decide_exact_match([], ["UNLOCODE:XXAAA"])
        self.assertEqual(result.status, "auto_resolved")
        self.assertEqual(result.confidence_tier, "B")

    def test_geonames_exact_does_not_suppress_official_fuzzy_candidate(self):
        queries = pd.DataFrame(
            [
                {
                    "query_id": "Q1",
                    "country_code": "TR",
                    "destination_key": "harbour x",
                }
            ]
        )
        aliases = pd.DataFrame(
            [
                {
                    "registry_id": "GEONAMES:1",
                    "provider": "GEONAMES",
                    "country_code": "TR",
                    "alias_key": "harbour x",
                },
                {
                    "registry_id": "WPI:1",
                    "provider": "NGA_WPI",
                    "country_code": "TR",
                    "alias_key": "harbour ex",
                },
            ]
        )

        candidates = generate_source_aware_candidates(queries, aliases)

        methods = candidates.set_index("registry_id")["match_method"].to_dict()
        self.assertEqual(methods["GEONAMES:1"], "exact_alias")
        self.assertEqual(methods["WPI:1"], "fuzzy_alias")

    def test_country_review_prevents_automatic_resolution(self):
        result = decide_exact_match(["WPI:1"], [], country_requires_review=True)
        self.assertEqual(result.status, "review_required")
        self.assertEqual(result.confidence_tier, "B")

    def test_disagreeing_wpi_and_unlocode_exact_matches_require_review(self):
        # Real places can share a name within a country (seen on the real
        # registry: multiple US "Hamilton"s, "Chatham"s etc. thousands of
        # nmi apart). A single WPI match and a single UN/LOCODE match must
        # not auto-resolve just because each family individually has one
        # candidate, if those candidates disagree on location.
        result = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={
                "WPI:1": (40.0, -74.0),
                "UNLOCODE:1": (34.0, -118.0),
            },
        )
        self.assertEqual(result.status, "review_required")
        self.assertIsNone(result.selected_registry_id)

    def test_agreeing_wpi_and_unlocode_exact_matches_still_auto_resolve(self):
        result = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={
                "WPI:1": (40.0, -74.0),
                "UNLOCODE:1": (40.01, -74.01),
            },
        )
        self.assertEqual(result.status, "auto_resolved")
        self.assertEqual(result.selected_registry_id, "WPI:1")

    def test_missing_coordinates_preserve_prior_auto_resolve_behavior(self):
        result = decide_exact_match(["WPI:1"], ["UNLOCODE:1"])
        self.assertEqual(result.status, "auto_resolved")
        self.assertEqual(result.selected_registry_id, "WPI:1")
        self.assertIn("unchecked", result.reason)

    def test_partial_coordinates_still_note_unchecked_location(self):
        # Only one of the two ids has a known coordinate - still can't
        # check agreement, so the decision must say so rather than
        # silently proceeding as if it were verified.
        result = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={"WPI:1": (40.0, -74.0)},
        )
        self.assertEqual(result.status, "auto_resolved")
        self.assertIn("unchecked", result.reason)

    def test_agreeing_match_reason_does_not_say_unchecked(self):
        result = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={
                "WPI:1": (40.0, -74.0),
                "UNLOCODE:1": (40.01, -74.01),
            },
        )
        self.assertNotIn("unchecked", result.reason)

    def test_fuzzy_candidates_exclude_alias_far_shorter_than_query(self):
        # "re" scores 90 via fuzz.WRatio against "pireus" (well above the
        # 80 cutoff used here) purely because it is a short substring - a
        # length-ratio floor should drop it even though the raw score
        # alone would let it through.
        queries = pd.DataFrame(
            [
                {
                    "query_id": "Q1",
                    "country_code": "GR",
                    "destination_key": "pireus",
                }
            ]
        )
        aliases = pd.DataFrame(
            [
                {
                    "registry_id": "WPI:1",
                    "provider": "NGA_WPI",
                    "country_code": "GR",
                    "alias_key": "piraeus",
                },
                {
                    "registry_id": "GEONAMES:1",
                    "provider": "GEONAMES",
                    "country_code": "GR",
                    "alias_key": "re",
                },
            ]
        )

        candidates = generate_source_aware_candidates(queries, aliases)

        registry_ids = set(candidates["registry_id"])
        self.assertIn("WPI:1", registry_ids)
        self.assertNotIn("GEONAMES:1", registry_ids)


if __name__ == "__main__":
    unittest.main()
