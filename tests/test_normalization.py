import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sea_mile.normalization import canonical_key, normalize_display_text


class NormalizationTests(unittest.TestCase):
    def test_display_normalization_preserves_accents_and_collapses_whitespace(self):
        self.assertEqual(normalize_display_text("  İZMİR\t LİMANI  "), "İZMİR LİMANI")

    def test_canonical_key_ignores_accents_case_and_punctuation(self):
        self.assertEqual(canonical_key("İzmir-Limanı"), canonical_key("IZMIR LIMANI"))

    def test_canonical_key_does_not_modify_raw_value(self):
        raw = "  Çanakkale  "
        canonical_key(raw)
        self.assertEqual(raw, "  Çanakkale  ")


if __name__ == "__main__":
    unittest.main()
