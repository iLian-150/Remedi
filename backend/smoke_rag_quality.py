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

    def test_formula_tokens_normalize_adjacent_variables_and_preserve_named_atoms(self):
        self.assertEqual(formula_tokens("xy=2"), ["formula:x*y=2"])
        self.assertEqual(formula_tokens("2xy=4"), ["formula:2*x*y=4"])
        self.assertEqual(formula_tokens("a*b=c*d"), ["formula:a*b=c*d"])
        self.assertEqual(formula_tokens("ln(x)=y"), ["formula:ln(x)=y"])
        self.assertEqual(formula_tokens("pi=3.14"), ["formula:pi=3.14"])

    def test_formula_tokens_normalize_common_greek_symbols(self):
        self.assertEqual(formula_tokens("π=3.14"), ["formula:pi=3.14"])
        self.assertEqual(formula_tokens("α+β=γ"), ["formula:alpha+beta=gamma"])
        self.assertEqual(formula_tokens("αx=2"), ["formula:alpha*x=2"])
        self.assertEqual(formula_tokens("xπ=2"), ["formula:x*pi=2"])
        self.assertEqual(formula_tokens("x²=π"), ["formula:x^2=pi"])
        self.assertEqual(formula_tokens("1 μm=2"), ["formula:1*um=2"])
        self.assertEqual(formula_tokens("2 μg=4"), ["formula:2*ug=4"])

    def test_formula_tokens_normalize_latex_greek_commands(self):
        self.assertEqual(formula_tokens(r"\alpha x=2"), ["formula:alpha*x=2"])
        self.assertEqual(formula_tokens(r"\Delta x=3"), ["formula:delta*x=3"])
        self.assertEqual(formula_tokens(r"\theta^2=1"), ["formula:theta^2=1"])

    def test_formula_tokens_preserve_parenthesized_terms_and_coefficients(self):
        self.assertEqual(formula_tokens("2(x+1)=7"), ["formula:2*(x+1)=7"])
        self.assertEqual(formula_tokens("2 (x+1) = 7"), ["formula:2*(x+1)=7"])
        self.assertEqual(formula_tokens("3(x+1)=7"), ["formula:3*(x+1)=7"])
        self.assertEqual(formula_tokens("-2(x+1)=7"), ["formula:-2*(x+1)=7"])
        self.assertEqual(formula_tokens("2((x+1)*(y-2))=7"), ["formula:2*((x+1)*(y-2))=7"])
        self.assertEqual(formula_tokens("sin(x)=y"), ["formula:sin(x)=y"])
        self.assertEqual(formula_tokens("f(x)=y"), ["formula:f(x)=y"])
        self.assertEqual(formula_tokens("x(x+1)=0"), ["formula:x*(x+1)=0"])

    def test_formula_tokens_normalize_implicit_products_after_parenthesized_groups(self):
        self.assertEqual(formula_tokens("(x+1)(x-1)=0"), ["formula:(x+1)*(x-1)=0"])
        self.assertEqual(formula_tokens("(x+1)x=7"), ["formula:(x+1)*x=7"])
        self.assertEqual(formula_tokens("(x+1) 2=7"), ["formula:(x+1)*2=7"])

    def test_formula_tokens_preserve_unary_signs(self):
        self.assertEqual(formula_tokens("-2x+3=7"), ["formula:-2*x+3=7"])
        self.assertEqual(formula_tokens("x=-2"), ["formula:x=-2"])

    def test_formula_tokens_normalize_superscripts_and_unicode_fractions(self):
        self.assertEqual(formula_tokens("x²=4"), ["formula:x^2=4"])
        self.assertEqual(formula_tokens("x^2=4"), ["formula:x^2=4"])
        self.assertEqual(formula_tokens("½x=2"), ["formula:1/2*x=2"])

    def test_document_spread_preserves_rank_inside_each_document(self):
        candidates = [
            {"document_id": 1}, {"document_id": 1}, {"document_id": 1},
            {"document_id": 2}, {"document_id": 3},
        ]
        self.assertEqual(spread_by_document([0, 1, 2, 3, 4], candidates, 4), [0, 3, 4, 1])
        self.assertEqual(spread_by_document([0, 0, 99, 1], candidates, 8), [0, 1])


if __name__ == "__main__":
    unittest.main()
