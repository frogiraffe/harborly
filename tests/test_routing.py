import unittest

from sea_mile.routing import assess_route_length


class RouteAssessmentTests(unittest.TestCase):
    def test_route_cannot_be_materially_shorter_than_great_circle(self):
        result = assess_route_length(90.0, 100.0)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.flag, "below_great_circle_lower_bound")

    def test_large_but_possible_detour_is_flagged_without_rejection(self):
        result = assess_route_length(310.0, 100.0)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.flag, "high_detour_ratio")
        self.assertAlmostEqual(result.detour_ratio or 0.0, 3.1)

    def test_coincident_endpoints_accept_zero_route(self):
        result = assess_route_length(0.0, 0.0)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.flag, "coincident_endpoints")


if __name__ == "__main__":
    unittest.main()
