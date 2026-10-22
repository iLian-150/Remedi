"""Retrieval helper regressions: python smoke_rag_quality.py."""
import unittest

from app.services.rag_quality import formula_tokens, spread_by_document


class RagQualityTests(unittest.TestCase):
    def test_formula_tokens_keep_single_letter_variables_and_normalize_operators(self):
        expected = ["formula:x+y=z"]
        self.assertEqual(formula_tokens("x + y = z"), expected)
        expected_product = ["formula:x*y=z"]
        self.assertEqual(formula_tokens(r"x \times y = z"), expected_product)
        self.assertEqual(formula_tokens("x × y = z"), expected_product)

    def test_formula_tokens_do_not_turn_numbers_or_single_letters_into_evidence(self):
        self.assertEqual(formula_tokens("2+2"), [])
        self.assertEqual(formula_tokens("2"), [])
        self.assertEqual(formula_tokens("x"), [])
        self.assertEqual(formula_tokens("面积除以2"), [])
        self.assertEqual(formula_tokens("2+2=4"), ["formula:2+2=4"])

    def test_formula_tokens_normalize_implicit_coefficient_multiplication(self):
        expected = ["formula:2*x+3=7"]
        self.assertEqual(formula_tokens("2x+3=7"), expected)
        self.assertEqual(formula_tokens("2 * x + 3 = 7"), expected)

    def test_document_spread_preserves_rank_inside_each_document(self):
        candidates = [
            {"document_id": 1}, {"document_id": 1}, {"document_id": 1},
            {"document_id": 2}, {"document_id": 3},
        ]
        self.assertEqual(spread_by_document([0, 1, 2, 3, 4], candidates, 4), [0, 3, 4, 1])
        self.assertEqual(spread_by_document([0, 0, 99, 1], candidates, 8), [0, 1])


if __name__ == "__main__":
    unittest.main()
