import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dedupe_records.py"
spec = importlib.util.spec_from_file_location("dedupe_records", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class DedupeTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(module.normalize_doi("https://doi.org/10.1002/ANIE.202508314."), "10.1002/anie.202508314")
        self.assertEqual(module.normalize_doi("doi:10.1000/xyz(1999)."), "10.1000/xyz(1999)")
        self.assertEqual(module.normalize_doi("not-a-doi"), "")

    def test_doi_merge_preserves_provenance_and_citations(self):
        records = [
            {
                "title": "Photo-Tuned Solid-Liquid Transition",
                "year": 2025,
                "doi": "https://doi.org/10.1002/ANIE.202508314",
                "source": "crossref",
                "url": "https://doi.org/10.1002/anie.202508314",
                "citation_count": 3,
                "citation_source": "crossref",
                "abstract": "Publisher-deposited abstract text.",
                "abstract_source": "crossref",
            },
            {
                "title": "Photo-Tuned Solid–Liquid Transition",
                "year": 2025,
                "doi": "doi:10.1002/anie.202508314",
                "source": "openalex",
                "url": "https://openalex.org/W123",
                "citation_count": 5,
                "citation_source": "openalex",
                "abstract": "Indexed abstract text.",
                "abstract_source": "openalex",
            },
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 1)
        record = result["records"][0]
        self.assertEqual(record["doi"], "10.1002/anie.202508314")
        self.assertEqual(record["sources"], ["crossref", "openalex"])
        self.assertEqual(record["citation_metrics"], {"crossref": 3, "openalex": 5})
        self.assertNotIn("abstract", record)
        self.assertEqual(
            [(item["provider"], item["text"]) for item in record["abstracts"]],
            [
                ("crossref", "Publisher-deposited abstract text."),
                ("openalex", "Indexed abstract text."),
            ],
        )

    def test_preprint_and_published_merge_by_title_year(self):
        records = [
            {"title": "Form-stable phase change material for solar storage", "year": 2024, "source": "chemrxiv"},
            {"title": "Form Stable Phase-Change Material for Solar Storage", "year": 2025, "source": "crossref"},
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 1)
        self.assertIn("title_year", result["records"][0]["merge_reasons"])

    def test_similar_titles_are_flagged_not_merged(self):
        records = [
            {"title": "Thermal cycling stability of organic phase change composites", "year": 2024},
            {"title": "Thermal-cycle stability of organic phase-change composite materials", "year": 2024},
        ]
        result = module.dedupe(records, similarity_threshold=0.80)
        self.assertEqual(result["unique_count"], 2)
        self.assertEqual(len(result["possible_duplicates"]), 1)
        self.assertEqual(result["possible_duplicates"][0]["reason"], "similar_title")

    def test_same_title_with_different_dois_is_not_merged(self):
        records = [
            {"title": "A shared article title", "year": 2025, "doi": "10.1000/alpha"},
            {"title": "A shared article title", "year": 2025, "doi": "10.1000/beta"},
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 2)
        self.assertEqual(result["possible_duplicates"][0]["reason"], "doi_conflict")

    def test_same_title_with_missing_year_is_not_merged(self):
        records = [
            {"title": "A record without a publication year", "source": "web_search"},
            {"title": "A record without a publication year", "source": "openalex"},
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 2)
        self.assertEqual(result["possible_duplicates"][0]["reason"], "missing_year")

    def test_cnki_alias_ids_merge_even_when_titles_differ_in_punctuation(self):
        records = [
            {"title": "染料废水吸附：性能研究", "ids": {"cnki_record_id": "CDMD-10000-1234567890"}},
            {"title": "另一来源转写题名", "ids": {"cnki": "CDMD-10000-1234567890"}},
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 1)
        self.assertIn("stable_id", result["records"][0]["merge_reasons"])

    def test_handle_id_merges_without_doi(self):
        records = [
            {"title": "Repository thesis", "ids": {"handle": "123456789/9876"}},
            {"title": "Repository thesis metadata copy", "ids": {"handle": "123456789/9876"}},
        ]
        result = module.dedupe(records)
        self.assertEqual(result["unique_count"], 1)


if __name__ == "__main__":
    unittest.main()
