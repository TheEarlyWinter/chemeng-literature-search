import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_doi_records.py"
spec = importlib.util.spec_from_file_location("verify_doi_records", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def not_found(url="https://example.invalid"):
    return HTTPError(url, 404, "not found", None, None)


class VerifyDoiTests(unittest.TestCase):
    def record(self, title="A Verified Paper Title"):
        return {
            "title": title,
            "authors": ["Researcher, Alice", "Scientist, Bob"],
            "year": 2025,
            "venue": "Journal of Verified Results",
            "document_type": "journal-article",
            "doi": "10.1000/test",
        }

    def metadata(self, title="A Verified Paper Title"):
        return {
            "title": title,
            "authors": [
                {"family": "Researcher", "given": "Alice"},
                {"family": "Scientist", "given": "Bob"},
            ],
            "year": 2025,
            "venue": "Journal of Verified Results",
            "document_type": "journal-article",
            "doi": "10.1000/test",
            "url": "https://api.crossref.org/works/x",
        }

    def test_normalize_and_title_similarity(self):
        self.assertEqual(module.normalize_doi("https://doi.org/10.1000/ABC."), "10.1000/abc")
        self.assertEqual(module.title_similarity("Photo-Tuned Transition", "Photo Tuned Transition"), 1.0)
        self.assertEqual(module.normalize_title("<i>E</i>→<i>Z</i> switch"), "e z switch")

    def test_title_threshold_cannot_be_lowered_below_identity_floor(self):
        with self.assertRaises(ValueError):
            module.verify_record({"title": "Wrong", "doi": "10.1000/test"}, 0, 1.0, 0.0)

    @patch.object(module, "crossref_lookup")
    def test_matching_registry_title_is_verified(self, lookup):
        lookup.return_value = self.metadata()
        result = module.verify_record(self.record("A verified paper title"), 0, 1.0, 0.92)
        self.assertEqual(result["status"], "verified")

    @patch.object(module, "crossref_lookup")
    def test_real_doi_with_wrong_title_is_conflict(self, lookup):
        lookup.return_value = self.metadata("The Actual Registered Article")
        result = module.verify_record(
            self.record("A Completely Different Fabricated Title"), 0, 1.0, 0.92
        )
        self.assertEqual(result["status"], "conflict")
        self.assertIn("doi_title_mismatch", result["errors"])

    @patch.object(module, "crossref_lookup")
    def test_high_similarity_but_nonexact_title_is_conflict(self, lookup):
        lookup.return_value = self.metadata(
            "Photothermal Storage in Azobenzene Polymer Alpha"
        )
        result = module.verify_record(
            self.record("Photothermal Storage in Azobenzene Polymer Beta"),
            0, 1.0, 0.92,
        )
        self.assertGreater(result["title_similarity"], 0.92)
        self.assertEqual(result["status"], "conflict")

    @patch.object(module, "crossref_lookup")
    def test_real_title_with_fabricated_bibliographic_fields_is_conflict(self, lookup):
        lookup.return_value = self.metadata()
        for field, value, error in (
            ("authors", ["Fabricated, Person"], "doi_authors_mismatch"),
            ("year", 2024, "doi_year_mismatch"),
            ("venue", "Fabricated Journal", "doi_venue_mismatch"),
        ):
            with self.subTest(field=field):
                record = self.record()
                record[field] = value
                result = module.verify_record(record, 0, 1.0, 0.92)
                self.assertEqual(result["status"], "conflict")
                self.assertIn(error, result["errors"])

    def test_missing_doi_is_not_applicable_and_not_hard_failure(self):
        record = {"title": "Repository thesis", "doi": ""}
        result = module.verify_record(record, 0, 1.0, 0.92)
        self.assertEqual(result["status"], "not_applicable")
        batch = module.verify([record])
        self.assertEqual(batch["hard_failure_count"], 0)
        self.assertTrue(batch["all_verifiable_dois_match"])

    def test_nonempty_invalid_doi_is_hard_failure(self):
        record = {"title": "Plausible title", "doi": "not-a-doi"}
        result = module.verify_record(record, 0, 1.0, 0.92)
        self.assertEqual(result["status"], "invalid_doi")
        self.assertIn("invalid_doi_format", result["errors"])
        self.assertEqual(module.verify([record])["hard_failure_count"], 1)

    @patch.object(module, "doi_content_lookup")
    @patch.object(module, "datacite_lookup")
    @patch.object(module, "crossref_lookup")
    def test_content_negotiation_verifies_non_crossref_doi(self, crossref, datacite, content):
        crossref.side_effect = not_found()
        datacite.side_effect = not_found()
        record = self.record("中文期刊论文题名")
        record["doi"] = "10.11949/example"
        metadata = self.metadata("中文期刊论文题名")
        metadata["doi"] = "10.11949/example"
        metadata["url"] = "https://doi.org/10.11949/example"
        content.return_value = metadata
        result = module.verify_record(record, 0, 1.0, 0.92)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["registry"], "doi_content_negotiation")

    @patch.object(module, "doi_content_lookup")
    @patch.object(module, "datacite_lookup")
    @patch.object(module, "crossref_lookup")
    def test_all_registration_paths_not_found_is_hard_failure(self, crossref, datacite, content):
        crossref.side_effect = not_found()
        datacite.side_effect = not_found()
        content.side_effect = not_found()
        result = module.verify_record(
            {"title": "Missing paper", "doi": "10.1000/missing"}, 0, 1.0, 0.92
        )
        self.assertEqual(result["status"], "not_found")

    @patch.object(module, "doi_content_lookup")
    @patch.object(module, "datacite_lookup")
    @patch.object(module, "crossref_lookup")
    def test_unavailable_is_incomplete_even_without_identity_conflict(self, crossref, datacite, content):
        crossref.side_effect = TimeoutError()
        datacite.side_effect = TimeoutError()
        content.side_effect = TimeoutError()
        record = {"title": "Temporarily unavailable", "doi": "10.1000/test"}
        result = module.verify([record])
        self.assertEqual(result["status_counts"], {"unavailable": 1})
        self.assertTrue(result["no_hard_identity_conflict"])
        self.assertFalse(result["verification_complete"])
        self.assertFalse(result["all_verifiable_dois_match"])

    @patch.object(module, "doi_content_lookup")
    @patch.object(module, "datacite_lookup")
    @patch.object(module, "crossref_lookup")
    def test_mixed_doi_and_non_doi_batch(self, crossref, datacite, content):
        crossref.return_value = self.metadata("Verified title")
        records = [
            {"title": "Repository thesis", "doi": ""},
            self.record("Verified title"),
        ]
        result = module.verify(records)
        self.assertEqual(result["status_counts"], {"not_applicable": 1, "verified": 1})
        self.assertEqual(result["hard_failure_count"], 0)
        self.assertTrue(result["all_doi_records_verified"])
        datacite.assert_not_called()
        content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
