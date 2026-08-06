import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harborly.matching import (
    MatchReason,
    decide_exact_match,
)


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

    def test_reason_code_identifies_each_decision_branch(self):
        self.assertEqual(
            decide_exact_match(["WPI:1"], []).reason_code,
            MatchReason.UNIQUE_EXACT_WPI,
        )
        self.assertEqual(
            decide_exact_match([], ["UNLOCODE:XXAAA"]).reason_code,
            MatchReason.UNIQUE_EXACT_UNLOCODE,
        )
        self.assertEqual(
            decide_exact_match(["WPI:1", "WPI:2"], []).reason_code,
            MatchReason.MULTIPLE_IDENTITIES,
        )
        self.assertEqual(
            decide_exact_match([], []).reason_code,
            MatchReason.NO_CANDIDATE,
        )
        conflict = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={
                "WPI:1": (40.0, -74.0),
                "UNLOCODE:1": (34.0, -118.0),
            },
        )
        self.assertEqual(conflict.reason_code, MatchReason.COORDINATE_CONFLICT)

    def test_rules_applied_trace_the_decision_path(self):
        conflict = decide_exact_match(
            ["WPI:1"],
            ["UNLOCODE:1"],
            coordinates_by_registry_id={
                "WPI:1": (40.0, -74.0),
                "UNLOCODE:1": (34.0, -118.0),
            },
        )
        self.assertEqual(
            conflict.rules_applied,
            (
                "single_exact_wpi",
                "single_exact_unlocode",
                "coordinate_conflict_detected",
            ),
        )
        self.assertEqual(
            decide_exact_match(["WPI:1"], []).rules_applied, ("single_exact_wpi",)
        )
        self.assertEqual(
            decide_exact_match([], []).rules_applied, ("no_official_candidate",)
        )

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


if __name__ == "__main__":
    unittest.main()
