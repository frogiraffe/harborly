import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sea_mile.reference import parse_unlocode_coordinates, parse_wpi_dms


class ReferenceCoordinateTests(unittest.TestCase):
    def test_parses_wpi_north_coordinate(self):
        self.assertAlmostEqual(parse_wpi_dms("30°20'00\"N"), 30.3333333333)

    def test_parses_wpi_west_coordinate(self):
        self.assertAlmostEqual(parse_wpi_dms("2°05'00\"W"), -2.0833333333)

    def test_rejects_unrecognized_wpi_coordinate(self):
        self.assertIsNone(parse_wpi_dms("unknown"))

    def test_parses_unlocode_coordinate_pair(self):
        self.assertEqual(
            parse_unlocode_coordinates("4230N 00131E"), (42.5, 1.5166666666666666)
        )

    def test_parses_south_and_west_unlocode_coordinate_pair(self):
        self.assertEqual(
            parse_unlocode_coordinates("3450S 05830W"), (-34.833333333333336, -58.5)
        )

    def test_keeps_rounded_sixty_seconds(self):
        self.assertAlmostEqual(parse_wpi_dms("36°30'60\"N"), 36.5166666666)

    def test_rejects_out_of_bounds_wpi_latitude(self):
        self.assertIsNone(parse_wpi_dms("95°00'00\"N"))

    def test_rejects_out_of_bounds_unlocode_latitude(self):
        self.assertIsNone(parse_unlocode_coordinates("9500N 00131E"))


if __name__ == "__main__":
    unittest.main()
