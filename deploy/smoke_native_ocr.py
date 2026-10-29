"""APT planning checks; no downloads or host package changes."""
import unittest
from unittest.mock import patch

from install_native_ocr import candidate, planned_packages


class NativeOcrPlanTests(unittest.TestCase):
    def test_plan_preserves_versions_epochs_and_architectures(self):
        plan = planned_packages(
            "Inst tesseract-ocr (5.5.0-1build1 Ubuntu:26.04 [arm64])\n"
            "Inst tesseract-ocr-eng [1:4.0] (1:4.1.0-2build1 Ubuntu:26.04 [all])\n"
            "Inst libexample:arm64 (1.0-2 Ubuntu:26.04 [arm64])\n"
            "Conf tesseract-ocr (5.5.0-1build1 Ubuntu:26.04 [arm64])\n"
        )
        self.assertEqual(plan, {
            "tesseract-ocr": "5.5.0-1build1", "tesseract-ocr-eng": "1:4.1.0-2build1",
            "libexample:arm64": "1.0-2",
        })

    def test_package_removals_and_host_runtime_upgrades_are_rejected(self):
        for text in ["Remv other-service [1.0]", "Inst libc6:arm64 [2.40] (2.43 Ubuntu [arm64])"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                planned_packages(text)

    def test_unavailable_package_is_rejected(self):
        with patch("install_native_ocr.run", return_value="  Candidate: (none)\n"), self.assertRaises(RuntimeError):
            candidate("tesseract-ocr")

    def test_pinned_candidate_is_used(self):
        with patch("install_native_ocr.run", return_value="  Candidate: 1:4.1.0-2build1\n"):
            self.assertEqual(candidate("tesseract-ocr-eng"), "1:4.1.0-2build1")


if __name__ == "__main__":
    unittest.main()
