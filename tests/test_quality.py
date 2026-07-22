import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sea_mile.quality import great_circle_nmi, validate_coordinate


class CoordinateQualityTests(unittest.TestCase):
    def test_rejects_null_island_sentinel(self):
        result = validate_coordinate(0, 0)
        self.assertFalse(result.is_valid)
        self.assertIn("sentinel", result.reason)

    def test_rejects_out_of_range_latitude(self):
        self.assertFalse(validate_coordinate(91, 10).is_valid)

    def test_accepts_valid_coordinate(self):
        self.assertTrue(validate_coordinate(38.0, 26.0).is_valid)

    def test_same_point_has_zero_great_circle_distance(self):
        self.assertAlmostEqual(great_circle_nmi(38.0, 26.0, 38.0, 26.0), 0.0)

    def test_one_degree_of_latitude_is_about_sixty_nautical_miles(self):
        self.assertAlmostEqual(great_circle_nmi(0.0, 0.0, 1.0, 0.0), 60.04, delta=0.1)

    def test_antipodal_points_do_not_raise(self):
        from math import isfinite

        distance = great_circle_nmi(0.0, 0.0, 0.0, 180.0)
        self.assertTrue(isfinite(distance))
        self.assertGreater(distance, 10000)


if __name__ == "__main__":
    unittest.main()
