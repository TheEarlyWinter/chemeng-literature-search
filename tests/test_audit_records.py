import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_records.py"
spec = importlib.util.spec_from_file_location("audit_records", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class AuditRecordTests(unittest.TestCase):
    def base_record(self):
        return {
            "title": "Verified chemical engineering paper",
            "authors": ["A. Researcher"],
            "year": 2025,
            "venue": "Journal of Verifiable Results",
            "doi": "10.1000/example",
            "relevance_basis": "abstract",
            "verification_status": "confirmed",
            "evidence": [
                {
                    "provider": "openalex",
                    "source_type": "scholarly_index",
                    "role": "discovery",
                    "supports": ["identity", "relevance"],
                    "locator": "https://openalex.org/W123",
                    "accessed_at": "2026-08-09",
                },
                {
                    "provider": "crossref",
                    "source_type": "registry",
                    "role": "verification",
                    "supports": ["identity"],
                    "locator": "https://api.crossref.org/works/10.1000/example",
                    "accessed_at": "2026-08-09",
                },
            ],
        }

    def verified_doi(self, record=None):
        record = record or self.base_record()
        return {
            0: {
                "index": 0,
                "doi": "10.1000/example",
                "supplied_title": "Verified chemical engineering paper",
                "record_fingerprint": module.record_fingerprint(record),
                "status": "verified",
                "registry": "crossref",
                "registry_title": "Verified chemical engineering paper",
                "registry_url": "https://api.crossref.org/works/10.1000%2Fexample",
                "registry_metadata": {
                    "doi": "10.1000/example",
                    "authors": [{"family": "Researcher", "given": "A."}],
                    "year": 2025,
                    "venue": "Journal of Verifiable Results",
                    "document_type": "",
                },
            }
        }

    def test_registry_plus_discovery_confirms_record(self):
        result = module.audit([self.base_record()])
        self.assertTrue(result["all_confirmed"])
        self.assertEqual(result["confirmed_count"], 1)

    def test_strict_doi_gate_consumes_verified_result(self):
        result = module.audit([self.base_record()], self.verified_doi(), True)
        self.assertTrue(result["all_confirmed"])

    def test_strict_doi_gate_rejects_missing_result(self):
        result = module.audit([self.base_record()], {}, True)
        self.assertIn("missing_doi_verification_result", result["results"][0]["errors"])

    def test_strict_doi_gate_rejects_stale_sidecar_after_record_change(self):
        original = self.base_record()
        verification = self.verified_doi(original)
        changed = self.base_record()
        changed["year"] = 2024
        result = module.audit([changed], verification, True)
        self.assertIn(
            "doi_verification_record_fingerprint_mismatch",
            result["results"][0]["errors"],
        )

    def test_strict_doi_gate_rejects_registry_doi_only_in_query_parameter(self):
        record = self.base_record()
        verification = self.verified_doi(record)
        verification[0]["registry_url"] = (
            "https://api.crossref.org/works/10.1000/other?related=10.1000/example"
        )
        result = module.audit([record], verification, True)
        self.assertIn("doi_verification_untrusted_registry_trace", result["results"][0]["errors"])

    def test_strict_doi_gate_rejects_empty_forged_verified_sidecar(self):
        record = self.base_record()
        verification = {0: {
            "index": 0,
            "doi": "10.1000/example",
            "record_fingerprint": module.record_fingerprint(record),
            "status": "verified",
        }}
        result = module.audit([record], verification, True)
        self.assertIn("doi_verification_untrusted_registry_trace", result["results"][0]["errors"])
        self.assertIn("doi_verification_missing_registry_metadata", result["results"][0]["errors"])

    def test_strict_doi_gate_rejects_conflict_result(self):
        verification = self.verified_doi()
        verification[0]["status"] = "conflict"
        result = module.audit([self.base_record()], verification, True)
        self.assertIn("doi_verification_not_verified:conflict", result["results"][0]["errors"])

    def test_strict_doi_gate_rejects_nonempty_invalid_doi(self):
        record = self.base_record()
        record["doi"] = "invalid_doi_123"
        record["ids"] = {"openalex": "W9999"}
        verification = {0: {
            "index": 0,
            "doi": "invalid_doi_123",
            "supplied_title": record["title"],
            "record_fingerprint": module.record_fingerprint(record),
            "status": "invalid_doi",
        }}
        result = module.audit([record], verification, True)
        self.assertIn("doi_verification_not_verified:invalid_doi", result["results"][0]["errors"])

    def test_invalid_doi_prefixes_share_the_same_fingerprint(self):
        plain = self.base_record()
        prefixed = self.base_record()
        plain["doi"] = "invalid_doi_123"
        prefixed["doi"] = "https://doi.org/invalid_doi_123"
        self.assertEqual(module.record_fingerprint(plain), module.record_fingerprint(prefixed))

    def test_access_date_and_datetime_are_valid(self):
        self.assertTrue(module.valid_accessed_at("2026-08-09"))
        self.assertTrue(module.valid_accessed_at("2026-08-09T03:20:00Z"))
        self.assertFalse(module.valid_accessed_at("2026-99-99"))

    def test_two_independent_structured_indexes_can_confirm_identity(self):
        record = self.base_record()
        record["doi"] = ""
        s2_id = "a" * 40
        record["ids"] = {"openalex": "W123", "semantic_scholar": s2_id}
        record["evidence"] = [
            {
                "provider": "openalex",
                "source_type": "scholarly_index",
                "role": "discovery",
                "supports": ["identity"],
                "locator": "https://openalex.org/W123",
                "accessed_at": "2026-08-09",
            },
            {
                "provider": "semantic_scholar",
                "source_type": "scholarly_index",
                "role": "verification",
                "supports": ["identity"],
                "locator": f"https://www.semanticscholar.org/paper/{s2_id}",
                "accessed_at": "2026-08-09",
            },
        ]
        result = module.audit([record])
        self.assertTrue(result["all_confirmed"])

    def test_identifier_binding_rejects_substring_collision(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"pmid": "12345"}
        record["evidence"] = [{
            "provider": "pubmed",
            "source_type": "registry",
            "role": "discovery",
            "supports": ["identity"],
            "locator": "https://pubmed.ncbi.nlm.nih.gov/9123456/",
            "accessed_at": "2026-08-09",
        }]
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_identifier_binding_ignores_query_parameter(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"pmid": "12345"}
        record["evidence"] = [{
            "provider": "pubmed",
            "source_type": "registry",
            "role": "discovery",
            "supports": ["identity"],
            "locator": "https://pubmed.ncbi.nlm.nih.gov/99999999/?related_pmid=12345",
            "accessed_at": "2026-08-09",
        }]
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_structured_index_locator_must_contain_declared_id(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"openalex": "W123", "semantic_scholar": "a" * 40}
        record["evidence"] = [
            {
                "provider": provider,
                "source_type": "scholarly_index",
                "role": "discovery",
                "supports": ["identity"],
                "locator": locator,
                "accessed_at": "2026-08-09",
            }
            for provider, locator in (
                ("openalex", "https://openalex.org/W999"),
                ("semantic_scholar", "https://www.semanticscholar.org/paper/bad"),
            )
        ]
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_search_snippet_alone_does_not_confirm_identity(self):
        record = self.base_record()
        record["evidence"] = [
            {
                "provider": "web_search",
                "source_type": "search_engine",
                "role": "discovery",
                "supports": ["identity", "relevance"],
                "locator": "https://search.example/result/1",
                "accessed_at": "2026-08-09",
            }
        ]
        result = module.audit([record])
        self.assertFalse(result["all_confirmed"])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])
        self.assertIn("declared_confirmed_but_gate_failed", result["results"][0]["errors"])

    def test_query_urn_is_traceable_discovery_evidence(self):
        record = self.base_record()
        record["evidence"][0]["locator"] = "urn:search:web_search:q-20260809-001"
        record["evidence"][0]["query_or_relation"] = "deep eutectic phase change material"
        result = module.audit([record])
        self.assertTrue(result["all_confirmed"])

    def test_query_urn_without_query_text_is_not_traceable(self):
        record = self.base_record()
        record["evidence"][0]["locator"] = "urn:search:web_search:q-20260809-001"
        result = module.audit([record])
        self.assertIn("missing_discovery_evidence", result["results"][0]["errors"])

    def test_untraceable_memory_record_fails(self):
        record = {
            "title": "Plausible but unsupported title",
            "doi": "10.1000/plausible",
            "relevance_basis": "title",
        }
        result = module.audit([record])
        errors = result["results"][0]["errors"]
        self.assertIn("missing_discovery_evidence", errors)
        self.assertIn("identity_not_confirmed", errors)

    def test_claim_requires_abstract_or_fulltext_locator_and_excerpt(self):
        record = self.base_record()
        record["claims"] = [
            {
                "text": "Conversion efficiency was 99.9%",
                "basis": "title",
                "locator": "https://doi.org/10.1000/example",
            }
        ]
        result = module.audit([record])
        errors = result["results"][0]["errors"]
        self.assertIn("claim_0_unsupported_basis", errors)
        self.assertIn("claim_0_missing_evidence_excerpt", errors)

    def test_claim_with_excerpt_passes(self):
        record = self.base_record()
        record["evidence"].append({
            "provider": "publisher",
            "source_type": "publisher",
            "role": "content",
            "supports": ["claim", "abstract"],
            "locator": "https://doi.org/10.1000/example",
            "accessed_at": "2026-08-09",
        })
        record["claims"] = [{
            "text": "Latent heat was 200 J/g",
            "basis": "abstract",
            "locator": "https://doi.org/10.1000/example",
            "evidence_excerpt": "The measured latent heat was 200 J/g.",
        }]
        result = module.audit([record])
        self.assertTrue(result["all_confirmed"])

    def test_claim_locator_must_link_to_content_evidence(self):
        record = self.base_record()
        record["claims"] = [{
            "text": "Latent heat was 200 J/g",
            "basis": "abstract",
            "locator": "https://publisher.example/article/1",
            "evidence_excerpt": "The measured latent heat was 200 J/g.",
        }]
        result = module.audit([record])
        self.assertIn("claim_0_unlinked_locator_or_basis", result["results"][0]["errors"])

    def test_claim_rejects_current_doi_only_in_query_parameter(self):
        record = self.base_record()
        locator = "https://doi.org/10.1000/other?related=10.1000/example"
        record["evidence"].append({
            "provider": "doi",
            "source_type": "publisher",
            "role": "content",
            "supports": ["claim", "abstract"],
            "locator": locator,
            "accessed_at": "2026-08-09",
        })
        record["claims"] = [{
            "text": "Latent heat was 999 J/g",
            "basis": "abstract",
            "locator": locator,
            "evidence_excerpt": "The material achieved 999 J/g latent heat.",
        }]
        result = module.audit([record])
        self.assertIn("claim_0_unlinked_locator_or_basis", result["results"][0]["errors"])

    def test_claim_rejects_fake_content_host_even_when_linked(self):
        record = self.base_record()
        locator = "https://attacker.invalid/10.1000/example"
        record["evidence"].append({
            "provider": "fake",
            "source_type": "publisher",
            "role": "content",
            "supports": ["claim", "abstract"],
            "locator": locator,
            "accessed_at": "2026-08-09",
        })
        record["claims"] = [{
            "text": "Latent heat was 999 J/g",
            "basis": "abstract",
            "locator": locator,
            "evidence_excerpt": "The material achieved a latent heat of 999 J/g.",
        }]
        result = module.audit([record])
        self.assertIn("claim_0_unlinked_locator_or_basis", result["results"][0]["errors"])

    def test_provider_homepage_is_not_record_level_evidence(self):
        record = self.base_record()
        record["evidence"][1]["locator"] = "https://api.crossref.org/"
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_handle_and_cnki_ids_are_controlled_stable_identifiers(self):
        cases = (
            (
                {"handle": "123456789/9876"},
                "repository",
                "https://hdl.handle.net/123456789/9876",
            ),
            (
                {"cnki": "CDMD-0000000000"},
                "domain_database",
                "https://cdmd.cnki.com.cn/Article/CDMD-0000000000.htm",
            ),
        )
        for ids, source_type, locator in cases:
            with self.subTest(ids=ids):
                record = self.base_record()
                record["doi"] = ""
                record["ids"] = ids
                record["evidence"] = [{
                    "provider": source_type,
                    "source_type": source_type,
                    "role": "discovery",
                    "supports": ["identity", "relevance"],
                    "locator": locator,
                    "accessed_at": "2026-08-09",
                }]
                result = module.audit([record])
                self.assertTrue(result["all_confirmed"])

    def test_repository_permanent_identity_url_can_be_stable_identifier(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"repository_url": "https://repository.example.edu/handle/123/456"}
        record["evidence"] = [{
            "provider": "university_repository",
            "source_type": "repository",
            "role": "discovery",
            "supports": ["identity", "relevance"],
            "locator": "https://repository.example.edu/handle/123/456",
            "accessed_at": "2026-08-09",
        }]
        result = module.audit([record])
        self.assertTrue(result["all_confirmed"])

    def test_repository_word_in_untrusted_domain_is_not_stable_identifier(self):
        for url in (
            "https://repository-attacker.example/paper/1",
            "https://fake.edu.attacker.example/paper/1",
        ):
            with self.subTest(url=url):
                record = self.base_record()
                record["doi"] = ""
                record["ids"] = {"repository_url": url}
                record["evidence"] = [{
                    "provider": "fake_repository",
                    "source_type": "repository",
                    "role": "discovery",
                    "supports": ["identity"],
                    "locator": url,
                    "accessed_at": "2026-08-09",
                }]
                result = module.audit([record])
                self.assertIn("missing_stable_identifier", result["results"][0]["errors"])

    def test_self_declared_evil_registry_does_not_confirm_identity(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"pmid": "12345"}
        record["evidence"] = [{
            "provider": "not-a-registry",
            "source_type": "registry",
            "role": "discovery",
            "supports": ["identity"],
            "locator": "https://evil.invalid/fake-record/1",
            "accessed_at": "2026-08-09",
        }]
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_two_self_declared_fake_indexes_do_not_confirm_identity(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"pmid": "12345"}
        record["evidence"] = [
            {
                "provider": provider,
                "source_type": "scholarly_index",
                "role": "discovery",
                "supports": ["identity"],
                "locator": f"https://{provider}.invalid/record/1",
                "accessed_at": "2026-08-09",
            }
            for provider in ("fake_one", "fake_two")
        ]
        result = module.audit([record])
        self.assertIn("identity_not_confirmed", result["results"][0]["errors"])

    def test_blank_string_authors_and_year_fail(self):
        record = self.base_record()
        record["authors"] = "   "
        record["year"] = "   "
        result = module.audit([record])
        errors = result["results"][0]["errors"]
        self.assertIn("missing_or_invalid_authors", errors)
        self.assertIn("missing_or_invalid_year", errors)

    def screening_contract(self):
        return {
            "allowed_document_classes": ["original-research", "review"],
            "document_class_trusted_hosts": ["publisher.example"],
            "required_criteria": [
                {
                    "id": "direct_storage",
                    "evidence_policy": "direct_result_not_candidate",
                    "applies_to_classes": ["original-research"],
                    "trusted_hosts": ["publisher.example"],
                },
                {
                    "id": "journal_attribute",
                    "evidence_policy": "exact_attribute",
                    "trusted_hosts": ["library.example.edu"],
                    "expected_attributes": {
                        "ranking_system": "CAS upgraded major category",
                        "ranking_year": 2025,
                        "zone": "1",
                        "top": True,
                    },
                },
            ],
        }

    def screened_record(self):
        record = self.base_record()
        record["document_class"] = "original-research"
        record["evidence"].extend([
            {
                "provider": "publisher",
                "source_type": "publisher",
                "role": "content",
                "supports": ["claim", "abstract", "document_type"],
                "locator": "https://publisher.example/doi/10.1000/example",
                "accessed_at": "2026-08-09",
            },
            {
                "provider": "ranking_table",
                "source_type": "bibliographic_database",
                "role": "attribute",
                "supports": ["ranking"],
                "locator": "https://library.example.edu/ranking/2025",
                "query_or_relation": "Journal of Verifiable Results | 2025 | zone 1 | Top yes",
                "accessed_at": "2026-08-09",
            },
        ])
        record["eligibility_checks"] = [
            {
                "criterion": "document_class",
                "passed": True,
                "source_label": "Article",
                "locator": "https://publisher.example/doi/10.1000/example",
                "evidence_excerpt": "Document type: Article",
            },
            {
                "criterion": "direct_storage",
                "passed": True,
                "locator": "https://publisher.example/doi/10.1000/example",
                "evidence_excerpt": "The material achieved an energy density of 123 J/g.",
                "measured_value": 123,
                "unit": "J/g",
                "measurement_context": "energy density measured for the target material",
            },
            {
                "criterion": "journal_attribute",
                "passed": True,
                "locator": "https://library.example.edu/ranking/2025",
                "evidence_excerpt": "2025大类1区，Top=是",
                "subject_venue": "Journal of Verifiable Results",
                "observed_attributes": {
                    "ranking_system": "CAS upgraded major category",
                    "ranking_year": 2025,
                    "zone": "1",
                    "top": True,
                },
            },
        ]
        return record

    def test_screening_contract_accepts_direct_original_research(self):
        result = module.audit(
            [self.screened_record()], screening_contract=self.screening_contract()
        )
        self.assertTrue(result["all_confirmed"])

    def test_screening_contract_rejects_perspective_as_article(self):
        record = self.screened_record()
        record["document_class"] = "perspective"
        record["eligibility_checks"][0]["source_label"] = "Perspective"
        record["eligibility_checks"][0]["evidence_excerpt"] = "Document type: Perspective"
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn("screening_document_class_not_allowed", result["results"][0]["errors"])

    def test_screening_contract_rejects_candidate_only_topic_evidence(self):
        record = self.screened_record()
        record["eligibility_checks"][1]["evidence_excerpt"] = (
            "This promising candidate may offer opportunities for future latent heat storage."
        )
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn(
            "eligibility_criterion_candidate_only:direct_storage",
            result["results"][0]["errors"],
        )

    def test_screening_contract_rejects_duplicate_criterion(self):
        record = self.screened_record()
        record["eligibility_checks"].append(dict(record["eligibility_checks"][1]))
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn(
            "duplicate_eligibility_criterion:direct_storage",
            result["results"][0]["errors"],
        )

    def test_screening_contract_rejects_untrusted_evidence_host(self):
        record = self.screened_record()
        record["evidence"][2]["locator"] = "https://attacker.invalid/doi/10.1000/example"
        record["eligibility_checks"][0]["locator"] = "https://attacker.invalid/doi/10.1000/example"
        record["eligibility_checks"][1]["locator"] = "https://attacker.invalid/doi/10.1000/example"
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn("document_class_check_unlinked_or_untrusted", result["results"][0]["errors"])
        self.assertIn(
            "eligibility_criterion_unlinked_or_untrusted:direct_storage",
            result["results"][0]["errors"],
        )

    def test_screening_contract_rejects_attribute_mismatch(self):
        record = self.screened_record()
        record["eligibility_checks"][2]["observed_attributes"]["zone"] = "2"
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn(
            "eligibility_criterion_attribute_mismatch:journal_attribute",
            result["results"][0]["errors"],
        )

    def test_screening_contract_binds_attribute_to_record_venue(self):
        record = self.screened_record()
        record["eligibility_checks"][2]["subject_venue"] = "Different Journal"
        result = module.audit([record], screening_contract=self.screening_contract())
        self.assertIn(
            "eligibility_criterion_subject_venue_mismatch:journal_attribute",
            result["results"][0]["errors"],
        )

    def test_doi_sidecar_binds_screening_contract(self):
        contract = self.screening_contract()
        payload = {
            "input_count": 1,
            "screening_contract_fingerprint": module.screening_contract_fingerprint(contract),
            "results": [],
        }
        changed = dict(contract)
        changed["allowed_document_classes"] = ["review"]
        _, errors = module.doi_verification_map(payload, 1, changed)
        self.assertIn("doi_verification_screening_contract_fingerprint_mismatch", errors)

    def test_arbitrary_id_key_does_not_satisfy_stable_identifier(self):
        record = self.base_record()
        record["doi"] = ""
        record["ids"] = {"random": "looks-stable"}
        result = module.audit([record])
        self.assertIn("missing_stable_identifier", result["results"][0]["errors"])

    def test_declared_conflict_cannot_be_upgraded(self):
        record = self.base_record()
        record["verification_status"] = "conflict"
        result = module.audit([record])
        self.assertEqual(result["results"][0]["computed_status"], "provisional")
        self.assertIn("declared_metadata_conflict", result["results"][0]["errors"])

    def test_declared_provisional_stays_provisional(self):
        record = self.base_record()
        record["verification_status"] = "provisional"
        result = module.audit([record])
        self.assertEqual(result["results"][0]["computed_status"], "provisional")


if __name__ == "__main__":
    unittest.main()
