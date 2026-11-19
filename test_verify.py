import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voc_miner import normalize, verify, extract_json  # noqa: E402

REVIEWS = [
    "Reports take forever to load once you have more than a few projects.",
    "We can't find old tasks. Search is terrible.",
]


class VerifyTests(unittest.TestCase):
    def test_exact_quote_is_kept(self):
        analysis = {"pains": [{"theme": "Slow", "quotes": [
            {"review_id": 1, "quote": "Reports take forever to load"}]}]}
        cleaned, stats = verify(analysis, REVIEWS)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(len(cleaned["pains"]), 1)

    def test_invented_quote_is_dropped(self):
        analysis = {"pains": [{"theme": "Invented", "quotes": [
            {"review_id": 1, "quote": "The app crashes every morning at nine"}]}]}
        cleaned, stats = verify(analysis, REVIEWS)
        self.assertEqual(stats["kept"], 0)
        self.assertEqual(cleaned["pains"], [])
        self.assertTrue(stats["dropped"])

    def test_quote_from_wrong_review_is_dropped(self):
        analysis = {"pains": [{"theme": "Mixed up", "quotes": [
            {"review_id": 2, "quote": "Reports take forever to load"}]}]}
        cleaned, stats = verify(analysis, REVIEWS)
        self.assertEqual(stats["kept"], 0)

    def test_nonexistent_review_id_is_dropped(self):
        analysis = {"desires": [{"theme": "Ghost", "quotes": [
            {"review_id": 99, "quote": "Search is terrible"}]}]}
        cleaned, stats = verify(analysis, REVIEWS)
        self.assertEqual(stats["kept"], 0)

    def test_too_short_quote_is_dropped(self):
        analysis = {"pains": [{"theme": "Short", "quotes": [
            {"review_id": 2, "quote": "Search"}]}]}
        cleaned, stats = verify(analysis, REVIEWS)
        self.assertEqual(stats["kept"], 0)

    def test_normalize_handles_curly_quotes_and_case(self):
        self.assertEqual(normalize("We can’t   FIND it"), "we can't find it")

    def test_extract_json_ignores_text_around_it(self):
        self.assertEqual(extract_json('Here you go: {"a": 1} Thanks'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
