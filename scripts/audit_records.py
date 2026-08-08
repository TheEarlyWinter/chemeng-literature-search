#!/usr/bin/env python3
"""Audit scholarly records for provenance and minimum verification evidence.

Strict mode requires each DOI-bearing record to consume a matching `verified`
result from verify_doi_records.py. DOI sidecars are bound to complete normalized
record fingerprints so stale or index-shifted results cannot be reused silently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
STRUCTURED_TYPES = {"scholarly_index", "bibliographic_database"}
VALID_BASIS = {"title", "abstract", "fulltext"}
ID_PATTERNS = {
    "pmid": re.compile(r"^[1-9]\d*$", re.I),
    "pmcid": re.compile(r"^pmc[1-9]\d*$", re.I),
    "arxiv": re.compile(r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z-]+)?/\d{7}(?:v\d+)?)$", re.I),
    "openalex": re.compile(r"^(?:https?://openalex\.org/)?w[1-9]\d*$", re.I),
    "semantic_scholar": re.compile(r"^(?:[0-9a-f]{40}|corpusid:?[1-9]\d*)$", re.I),
    "s2": re.compile(r"^(?:[0-9a-f]{40}|corpusid:?[1-9]\d*)$", re.I),
    "lens": re.compile(r"^[0-9-]+[a-z]?$", re.I),
    "handle": re.compile(r"^(?:https?://hdl\.handle\.net/)?(?:20\.)?\d+(?:\.\d+)*/\S+$", re.I),
    "cnki": re.compile(
        r"^(?:https?://(?:kns|oversea|cdmd)\.cnki\.net/\S+|(?:CDMD|CMFD|CDFD|CPFD|CJFD)[A-Z0-9._:-]{6,})$",
        re.I,
    ),
    "cnki_record_id": re.compile(r"^(?:CDMD|CMFD|CDFD|CPFD|CJFD)[A-Z0-9._:-]{6,}$", re.I),
    "wanfang": re.compile(
        r"^(?:https?://(?:d|www)\.wanfangdata\.com\.cn/\S+|(?:degree|conference|periodical|patent):[A-Z0-9._:/-]{6,})$",
        re.I,
    ),
    "wanfang_record_id": re.compile(r"^(?:degree|conference|periodical|patent):[A-Z0-9._:/-]{6,}$", re.I),
    "cqvip": re.compile(r"^(?:https?://(?:www\.)?cqvip\.com/\S+|(?:QK|ZK|HY):[A-Z0-9._:/-]{6,})$", re.I),
    "vip_record_id": re.compile(r"^(?:QK|ZK|HY):[A-Z0-9._:/-]{6,}$", re.I),
}


def raw_doi(value: Any) -> str:
    if value is None:
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.strip("<>\"'").rstrip(".,").lower()


def normalize_doi(value: Any) -> str:
    doi = raw_doi(value)
    return doi if DOI_RE.match(doi) else ""


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def normalize_title_identity(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).casefold(): normalize_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if value is None:
        return None
    return normalize_text(value)


FINGERPRINT_FIELDS = (
    "title", "authors", "year", "venue", "ids", "document_type", "evidence", "claims",
    "relevance_basis", "document_class", "eligibility_checks", "verification_status",
)


def canonical_fingerprint(value: Any) -> str:
    canonical = json.dumps(
        normalize_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_fingerprint(record: dict[str, Any]) -> str:
    supplied_raw_doi = raw_doi(record.get("doi"))
    payload = {field: record.get(field) for field in FINGERPRINT_FIELDS}
    payload["doi"] = normalize_doi(supplied_raw_doi) or normalize_text(supplied_raw_doi)
    return canonical_fingerprint(payload)


def screening_contract_fingerprint(contract: Any) -> str:
    return canonical_fingerprint(contract) if isinstance(contract, dict) else ""


def valid_locator(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    parsed = urlparse(text)
    if parsed.scheme == "urn":
        return bool(re.match(r"^urn:(?:search|query):[a-z0-9_.-]+:[a-z0-9_.:-]+$", text, re.I))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return parsed.path not in {"", "/"} or bool(parsed.query)


def valid_accessed_at(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        if "T" not in text and " " not in text:
            date.fromisoformat(text)
        else:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def institutional_repository_host(host: str) -> bool:
    host = host.rstrip(".").casefold()
    if host == "hdl.handle.net":
        return True
    return bool(
        re.search(r"\.(?:edu|gov)$", host)
        or re.search(r"\.(?:edu|ac|gov)\.[a-z]{2}$", host)
    )


def host_is(host: str, *suffixes: str) -> bool:
    host = host.rstrip(".").casefold()
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def evidence_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("evidence")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def supports_identity(item: dict[str, Any]) -> bool:
    supports = item.get("supports")
    if isinstance(supports, str):
        supports = [supports]
    return isinstance(supports, list) and "identity" in supports


def support_values(item: dict[str, Any]) -> set[str]:
    supports = item.get("supports")
    if isinstance(supports, str):
        supports = [supports]
    return {str(value).casefold() for value in supports} if isinstance(supports, list) else set()


def supports_content(item: dict[str, Any]) -> bool:
    return bool({"claim", "abstract", "fulltext"} & support_values(item))


CONTENT_HOSTS = {
    "doi.org", "pubs.acs.org", "onlinelibrary.wiley.com", "sciencedirect.com",
    "link.springer.com", "nature.com", "rsc.org", "tandfonline.com", "academic.oup.com",
    "mdpi.com", "pubmed.ncbi.nlm.nih.gov", "europepmc.org", "cnki.net", "cnki.com.cn",
    "wanfangdata.com.cn", "cqvip.com", "zenodo.org", "hal.science", "osf.io",
    "figshare.com", "core.ac.uk", "hdl.handle.net",
}


def supports_claim_basis(item: dict[str, Any], basis: str, record: dict[str, Any]) -> bool:
    if not (
        str(item.get("role") or "").casefold() == "content"
        and basis in {"abstract", "fulltext"}
        and basis in support_values(item)
    ):
        return False
    locator = str(item.get("locator") or "").strip()
    parsed = urlparse(locator)
    if not parsed.hostname or not (
        any(host_is(parsed.hostname, host) for host in CONTENT_HOSTS)
        or institutional_repository_host(parsed.hostname)
    ):
        return False
    if str(item.get("source_type") or "").casefold() not in {
        "publisher", "registry", "domain_database", "repository"
    }:
        return False
    return locator_matches_record_path(locator, record)


def provider_key(item: dict[str, Any]) -> str:
    return str(item.get("provider") or item.get("source") or "").strip().casefold()


def traceable_evidence(item: dict[str, Any]) -> bool:
    locator = str(item.get("locator") or "").strip()
    if not provider_key(item) or not valid_locator(locator) or not valid_accessed_at(item.get("accessed_at")):
        return False
    if locator.casefold().startswith("urn:"):
        return (
            str(item.get("role") or "").casefold() == "discovery"
            and bool(str(item.get("query_or_relation") or "").strip())
        )
    return True


def id_values(record: dict[str, Any], *keys: str) -> list[str]:
    ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
    values: list[str] = []
    for key in keys:
        value = ids.get(key) or record.get(key)
        if value is not None and str(value).strip():
            values.append(str(value).strip().casefold())
    return values


def locator_contains_any(locator: str, values: list[str]) -> bool:
    """Match identifiers only in the URL record path, never query/fragment text.

    Host-specific callers already constrain which provider path grammar is
    acceptable. A value that is itself a URL contributes only its path. This
    prevents unrelated records from borrowing an identifier through parameters
    such as ``?related_pmid=12345`` or ``?related=10.1000/example``.
    """
    parsed_locator = urlparse(locator)
    normalized_path = unquote(parsed_locator.path).casefold()
    for value in values:
        raw_token = unquote(str(value)).strip().casefold()
        if not raw_token:
            continue
        parsed_token = urlparse(raw_token)
        token = unquote(parsed_token.path).casefold() if parsed_token.scheme else raw_token
        token = token.strip("/")
        if not token:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
        if re.search(pattern, normalized_path):
            return True
    return False


def decoded_path(locator: str) -> str:
    return unquote(urlparse(locator).path).strip("/").casefold()


def doi_matches_record_path(locator: str, doi: str) -> bool:
    path = decoded_path(locator)
    token = normalize_doi(doi)
    return bool(token) and (path == token or path.endswith("/" + token))


def exact_path_id(locator: str, values: list[str], allow_extension: bool = False) -> bool:
    segments = [segment for segment in decoded_path(locator).split("/") if segment]
    candidates = set(segments)
    if allow_extension:
        candidates.update(re.sub(r"\.(?:s?html?|aspx?)$", "", segment) for segment in segments)
    normalized_values: set[str] = set()
    for value in values:
        raw = unquote(str(value)).strip().casefold()
        parsed = urlparse(raw)
        token = unquote(parsed.path).strip("/").casefold() if parsed.scheme else raw.strip("/")
        if token:
            normalized_values.add(token)
    return bool(candidates & normalized_values)


def locator_matches_record_path(locator: str, record: dict[str, Any]) -> bool:
    parsed = urlparse(locator)
    if not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    doi = normalize_doi(record.get("doi"))
    if doi:
        return doi_matches_record_path(locator, doi)
    if host_is(host, "pubmed.ncbi.nlm.nih.gov"):
        return decoded_path(locator) in set(id_values(record, "pmid"))
    if host_is(host, "europepmc.org"):
        return exact_path_id(locator, id_values(record, "pmid", "pmcid"))
    if host_is(host, "openalex.org"):
        values = [re.sub(r"^https?://openalex\.org/", "", value) for value in id_values(record, "openalex")]
        return decoded_path(locator) in set(values)
    if host_is(host, "semanticscholar.org"):
        return exact_path_id(locator, id_values(record, "semantic_scholar", "s2"))
    if host_is(host, "lens.org"):
        return exact_path_id(locator, id_values(record, "lens"))
    if host == "hdl.handle.net":
        values = [re.sub(r"^https?://hdl\.handle\.net/", "", value) for value in id_values(record, "handle")]
        return decoded_path(locator) in set(values)
    if host_is(host, "cnki.net", "cnki.com.cn"):
        return exact_path_id(locator, id_values(record, "cnki", "cnki_record_id"), True)
    if host_is(host, "wanfangdata.com.cn"):
        return exact_path_id(locator, id_values(record, "wanfang", "wanfang_record_id"), True)
    if host_is(host, "cqvip.com"):
        return exact_path_id(locator, id_values(record, "cqvip", "vip_record_id"), True)
    declared = id_values(record, "repository_url", "institution_record_url")
    return locator.casefold() in declared


def trusted_structured_identity(item: dict[str, Any], record: dict[str, Any]) -> bool:
    locator = str(item.get("locator") or "").strip()
    parsed = urlparse(locator)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not supports_identity(item):
        return False
    if str(item.get("source_type") or "").casefold() not in STRUCTURED_TYPES:
        return False
    host = parsed.hostname.casefold()
    if host_is(
        host, "openalex.org", "semanticscholar.org", "pubmed.ncbi.nlm.nih.gov",
        "europepmc.org", "lens.org",
    ):
        return locator_matches_record_path(locator, record)
    return False


def structured_source_key(item: dict[str, Any]) -> str:
    parsed = urlparse(str(item.get("locator") or ""))
    return parsed.hostname.casefold() if parsed.hostname else ""


def trusted_direct_identity(item: dict[str, Any], record: dict[str, Any]) -> bool:
    """Bind confirming source types to plausible hosts.

    DOI records are additionally protected by the live DOI sidecar. No-DOI
    records can be directly confirmed only by controlled registries, domain
    databases, or institutional repositories—not an arbitrary self-declared URL.
    """
    locator = str(item.get("locator") or "").strip()
    parsed = urlparse(locator)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not supports_identity(item):
        return False
    host = parsed.hostname.casefold()
    source_type = str(item.get("source_type") or "").casefold()
    if source_type == "registry":
        if host_is(host, "doi.org", "crossref.org", "datacite.org"):
            return doi_matches_record_path(locator, normalize_doi(record.get("doi")))
        if host_is(host, "ncbi.nlm.nih.gov", "europepmc.org"):
            return locator_matches_record_path(locator, record)
        return False
    if source_type == "domain_database":
        if host_is(
            host, "cnki.net", "cnki.com.cn", "wanfangdata.com.cn", "cqvip.com",
            "ncbi.nlm.nih.gov", "europepmc.org",
        ):
            return locator_matches_record_path(locator, record)
        return False
    if source_type == "repository":
        if host == "hdl.handle.net":
            return locator_matches_record_path(locator, record)
        declared = id_values(record, "repository_url", "institution_record_url")
        return locator.casefold() in declared and (
            institutional_repository_host(host)
            or host_is(host, "zenodo.org", "hal.science", "osf.io", "figshare.com", "core.ac.uk")
        )
    # Publisher pages can support content, but DOI identity in strict workflows
    # comes from the live sidecar. An arbitrary host cannot self-declare itself
    # a publisher and become a confirming identity source.
    return False


def repository_id_from_evidence(record: dict[str, Any]) -> bool:
    ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
    declared_url = str(ids.get("repository_url") or ids.get("institution_record_url") or "").strip()
    if not declared_url or not valid_locator(declared_url):
        return False
    parsed = urlparse(declared_url)
    if not parsed.hostname or not institutional_repository_host(parsed.hostname):
        return False
    return any(
        str(item.get("locator") or "").strip() == declared_url
        and traceable_evidence(item)
        and str(item.get("source_type") or "").casefold() == "repository"
        and supports_identity(item)
        for item in evidence_entries(record)
    )


def has_stable_id(record: dict[str, Any]) -> bool:
    if normalize_doi(record.get("doi")):
        return True
    ids = record.get("ids")
    if isinstance(ids, dict):
        for key, pattern in ID_PATTERNS.items():
            value = str(ids.get(key) or "").strip()
            if value and pattern.match(value):
                return True
    return repository_id_from_evidence(record)


def doi_verification_map(
    payload: Any, expected_count: int, screening_contract: dict[str, Any] | None = None,
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return {}, ["invalid_doi_verification_payload"]
    if payload.get("input_count") != expected_count:
        errors.append("doi_verification_input_count_mismatch")
    expected_contract_fingerprint = screening_contract_fingerprint(screening_contract)
    if str(payload.get("screening_contract_fingerprint") or "") != expected_contract_fingerprint:
        errors.append("doi_verification_screening_contract_fingerprint_mismatch")
    mapped: dict[int, dict[str, Any]] = {}
    for item in payload["results"]:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            errors.append("invalid_doi_verification_result")
            continue
        index = item["index"]
        if index in mapped:
            errors.append("duplicate_doi_verification_index")
        if index < 0 or index >= expected_count:
            errors.append("doi_verification_index_out_of_range")
        mapped[index] = item
    return mapped, list(dict.fromkeys(errors))


def audit_author_family(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("family") or value.get("name") or value.get("literal")
        text = normalize_title_identity(raw)
        return "" if text in {"", "et al", "etal"} else text
    raw = value
    text = normalize_title_identity(raw)
    if not text or text in {"et al", "etal"}:
        return ""
    if "," in str(value):
        return normalize_title_identity(str(value).split(",", 1)[0])
    return text.split()[-1]


def normalized_record_type(value: Any) -> str:
    text = re.sub(r"[^\w\s-]", " ", normalize_text(value), flags=re.UNICODE)
    text = "-".join(text.split())
    return {
        "article": "journal-article", "journalarticle": "journal-article",
        "research-article": "journal-article", "review-article": "review",
    }.get(text, text)


def sidecar_metadata_errors(record: dict[str, Any], checked: dict[str, Any], doi: str) -> list[str]:
    errors: list[str] = []
    registry = str(checked.get("registry") or "").casefold()
    url = str(checked.get("registry_url") or "").strip()
    parsed = urlparse(url)
    allowed_hosts = {
        "crossref": "crossref.org", "datacite": "datacite.org",
        "doi_content_negotiation": "doi.org",
    }
    expected_host = allowed_hosts.get(registry)
    if not expected_host or not parsed.hostname or not host_is(parsed.hostname, expected_host) \
            or not doi_matches_record_path(url, doi):
        errors.append("doi_verification_untrusted_registry_trace")
    if normalize_title_identity(checked.get("registry_title")) != normalize_title_identity(record.get("title")):
        errors.append("doi_verification_registry_title_mismatch")
    metadata = checked.get("registry_metadata")
    if not isinstance(metadata, dict):
        return errors + ["doi_verification_missing_registry_metadata"]
    if normalize_doi(metadata.get("doi")) != doi:
        errors.append("doi_verification_registry_metadata_doi_mismatch")
    supplied = [audit_author_family(value) for value in record.get("authors", [])] \
        if isinstance(record.get("authors"), list) else []
    supplied = [value for value in supplied if value]
    registered = [audit_author_family(value) for value in metadata.get("authors", [])] \
        if isinstance(metadata.get("authors"), list) else []
    registered = [value for value in registered if value]
    if not supplied or not registered or supplied[0] != registered[0] \
            or not set(supplied).issubset(set(registered)):
        errors.append("doi_verification_registry_metadata_authors_mismatch")
    try:
        if int(str(record.get("year")).strip()) != int(metadata.get("year")):
            errors.append("doi_verification_registry_metadata_year_mismatch")
    except (TypeError, ValueError):
        errors.append("doi_verification_registry_metadata_year_mismatch")
    if normalize_text(record.get("venue")) != normalize_text(metadata.get("venue")):
        errors.append("doi_verification_registry_metadata_venue_mismatch")
    supplied_type = normalized_record_type(record.get("document_type"))
    metadata_type = normalized_record_type(metadata.get("document_type"))
    container_types = {
        "journal-article", "proceedings-article", "posted-content", "book-chapter", "dissertation"
    }
    if supplied_type in container_types and supplied_type != metadata_type:
        errors.append("doi_verification_registry_metadata_type_mismatch")
    return errors


def doi_gate_errors(
    record: dict[str, Any], index: int, verification: dict[int, dict[str, Any]] | None,
) -> list[str]:
    raw = str(record.get("doi") or "").strip()
    if not raw:
        return []
    doi = normalize_doi(raw)
    if verification is None:
        return ["missing_doi_verification_result"]
    checked = verification.get(index)
    if not checked:
        return ["missing_doi_verification_result"]
    if str(checked.get("record_fingerprint") or "") != record_fingerprint(record):
        return ["doi_verification_record_fingerprint_mismatch"]
    if normalize_doi(checked.get("doi")) != doi:
        return ["doi_verification_record_mismatch"]
    status = str(checked.get("status") or "").casefold()
    if status != "verified":
        return [f"doi_verification_not_verified:{status or 'missing_status'}"]
    return sidecar_metadata_errors(record, checked, doi)


DOCUMENT_CLASS_LABELS = {
    "original-research": {"article", "research article", "original article", "research paper", "communication"},
    "review": {"review", "review article", "systematic review", "meta-analysis"},
    "perspective": {"perspective", "viewpoint", "commentary", "opinion"},
    "editorial": {"editorial"},
}


def document_class_from_label(value: Any) -> str:
    label = normalize_text(value)
    for document_class, labels in DOCUMENT_CLASS_LABELS.items():
        if label in labels:
            return document_class
    return ""


SCREENING_POLICIES = {"direct_result_not_candidate", "exact_attribute"}
SCREENING_EVIDENCE_TYPES = {
    "publisher", "registry", "domain_database", "repository", "bibliographic_database"
}


def record_identity_tokens(record: dict[str, Any]) -> list[str]:
    tokens = [normalize_doi(record.get("doi"))]
    ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
    for key in ID_PATTERNS:
        value = ids.get(key)
        if value is None or not str(value).strip() or not ID_PATTERNS[key].match(str(value).strip()):
            continue
        token = str(value).strip().casefold()
        token = re.sub(r"^https?://(?:hdl\.handle\.net|openalex\.org)/", "", token)
        tokens.append(token)
    return [token for token in tokens if token]


def screening_source_ok(
    item: dict[str, Any] | None, record: dict[str, Any], policy: str,
    trusted_hosts: set[str],
) -> bool:
    if not item or str(item.get("source_type") or "").casefold() not in SCREENING_EVIDENCE_TYPES:
        return False
    role = str(item.get("role") or "").casefold()
    supports = support_values(item)
    locator = str(item.get("locator") or "").strip()
    parsed = urlparse(locator)
    if not parsed.hostname or not any(host_is(parsed.hostname, host) for host in trusted_hosts):
        return False
    if policy == "document_class":
        return role in {"content", "verification"} and "document_type" in supports \
            and locator_contains_any(locator, record_identity_tokens(record))
    if policy == "direct_result_not_candidate":
        return role == "content" and bool({"claim", "abstract", "fulltext"} & supports) \
            and locator_contains_any(locator, record_identity_tokens(record))
    if policy == "exact_attribute":
        return role == "attribute" and bool({"attribute", "ranking"} & supports)
    return False


def contract_errors(contract: dict[str, Any]) -> tuple[list[str], set[str], list[dict[str, Any]]]:
    errors: list[str] = []
    allowed = contract.get("allowed_document_classes")
    allowed_values = {
        normalize_text(value) for value in allowed if normalize_text(value)
    } if isinstance(allowed, list) else set()
    if not allowed_values:
        errors.append("screening_contract_missing_document_classes")
    unknown_classes = allowed_values - set(DOCUMENT_CLASS_LABELS)
    if unknown_classes:
        errors.extend(f"screening_contract_unknown_document_class:{value}" for value in sorted(unknown_classes))

    type_hosts = contract.get("document_class_trusted_hosts")
    if not isinstance(type_hosts, list) or not {
        normalize_text(value) for value in type_hosts if normalize_text(value)
    }:
        errors.append("screening_contract_missing_document_class_trusted_hosts")

    required = contract.get("required_criteria")
    valid_required: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(required, list) or not required:
        errors.append("screening_contract_missing_required_criteria")
        return errors, allowed_values, valid_required
    for item in required:
        if not isinstance(item, dict):
            errors.append("screening_contract_invalid_criterion")
            continue
        criterion_id = normalize_text(item.get("id"))
        policy = normalize_text(item.get("evidence_policy"))
        if not criterion_id:
            errors.append("screening_contract_criterion_missing_id")
            continue
        if criterion_id in seen:
            errors.append(f"screening_contract_duplicate_criterion:{criterion_id}")
            continue
        seen.add(criterion_id)
        if policy not in SCREENING_POLICIES:
            errors.append(f"screening_contract_unknown_policy:{policy or 'missing'}")
            continue
        applies = item.get("applies_to_classes")
        if applies is not None:
            if not isinstance(applies, list) or not applies:
                errors.append(f"screening_contract_invalid_applies_to:{criterion_id}")
                continue
            applies_values = {normalize_text(value) for value in applies if normalize_text(value)}
            if not applies_values or not applies_values <= allowed_values:
                errors.append(f"screening_contract_invalid_applies_to:{criterion_id}")
                continue
        trusted_hosts = item.get("trusted_hosts")
        if not isinstance(trusted_hosts, list) or not {
            normalize_text(value) for value in trusted_hosts if normalize_text(value)
        }:
            errors.append(f"screening_contract_missing_trusted_hosts:{criterion_id}")
            continue
        if policy == "exact_attribute" and not isinstance(item.get("expected_attributes"), dict):
            errors.append(f"screening_contract_missing_expected_attributes:{criterion_id}")
            continue
        valid_required.append(item)
    return errors, allowed_values, valid_required


def screening_errors(
    record: dict[str, Any], traceable: list[dict[str, Any]], contract: dict[str, Any] | None,
) -> list[str]:
    if not contract:
        return []
    errors, allowed_values, required = contract_errors(contract)
    document_class = normalize_text(record.get("document_class"))
    if not document_class or document_class not in allowed_values:
        errors.append("screening_document_class_not_allowed")

    checks = record.get("eligibility_checks")
    if not isinstance(checks, list):
        return errors + ["missing_eligibility_checks"]
    check_map: dict[str, dict[str, Any]] = {}
    for item in checks:
        criterion_id = normalize_text(item.get("criterion")) if isinstance(item, dict) else ""
        if not criterion_id:
            errors.append("invalid_eligibility_check")
            continue
        if criterion_id in check_map:
            errors.append(f"duplicate_eligibility_criterion:{criterion_id}")
            continue
        check_map[criterion_id] = item
    evidence_by_locator = {
        str(item.get("locator") or "").strip(): item for item in traceable
        if not str(item.get("locator") or "").casefold().startswith("urn:")
    }

    type_check = check_map.get("document_class")
    if not type_check:
        errors.append("missing_document_class_check")
    else:
        if type_check.get("passed") is not True:
            errors.append("document_class_check_not_passed")
        source_label = type_check.get("source_label")
        if document_class_from_label(source_label) != document_class:
            errors.append("document_class_source_label_mismatch")
        locator = str(type_check.get("locator") or "").strip()
        evidence_item = evidence_by_locator.get(locator)
        type_hosts_raw = contract.get("document_class_trusted_hosts")
        type_hosts = {
            normalize_text(value) for value in type_hosts_raw if normalize_text(value)
        } if isinstance(type_hosts_raw, list) else set()
        if not screening_source_ok(evidence_item, record, "document_class", type_hosts):
            errors.append("document_class_check_unlinked_or_untrusted")
        excerpt = type_check.get("evidence_excerpt")
        if not isinstance(excerpt, str) or normalize_text(source_label) not in normalize_text(excerpt):
            errors.append("document_class_check_missing_excerpt")

    for criterion in required:
        criterion_id = normalize_text(criterion.get("id"))
        policy = normalize_text(criterion.get("evidence_policy"))
        applies_raw = criterion.get("applies_to_classes")
        applies_to = {normalize_text(value) for value in applies_raw} if isinstance(applies_raw, list) else set()
        if applies_to and document_class not in applies_to:
            continue
        check = check_map.get(criterion_id)
        if not check:
            errors.append(f"missing_eligibility_criterion:{criterion_id}")
            continue
        if check.get("passed") is not True:
            errors.append(f"eligibility_criterion_not_passed:{criterion_id}")
        locator = str(check.get("locator") or "").strip()
        evidence_item = evidence_by_locator.get(locator)
        trusted_hosts_raw = criterion.get("trusted_hosts")
        trusted_hosts = {
            normalize_text(value) for value in trusted_hosts_raw if normalize_text(value)
        } if isinstance(trusted_hosts_raw, list) else set()
        if not screening_source_ok(evidence_item, record, policy, trusted_hosts):
            errors.append(f"eligibility_criterion_unlinked_or_untrusted:{criterion_id}")
        excerpt = check.get("evidence_excerpt")
        if not isinstance(excerpt, str) or len(excerpt.strip()) < 12:
            errors.append(f"eligibility_criterion_missing_excerpt:{criterion_id}")
            excerpt = ""
        if policy == "direct_result_not_candidate":
            normalized_excerpt = normalize_text(excerpt)
            candidate_terms = (
                "candidate", "promising", "potential", "opportunit", "toward", "future",
                "may ", "could ", "can ", "有望", "潜力", "可能", "候选", "机会", "未来"
            )
            result_terms = (
                "energy density", "energy-storage dens", "storage capacity", "heat release",
                "released as heat", "latent heat", "enthalpy", "储能密度", "储热容量", "释热", "潜热", "焓"
            )
            measured_value = check.get("measured_value")
            unit = str(check.get("unit") or "").strip()
            context = str(check.get("measurement_context") or "").strip()
            numeric = isinstance(measured_value, (int, float)) and not isinstance(measured_value, bool)
            unit_ok = bool(re.fullmatch(
                r"\s*(?:j\s*/?\s*g|j\s*g[-−]?1|kj\s*/?\s*mol|kj\s*mol[-−]?1|°?c|k)\s*",
                unit, re.I,
            ))
            direct_language = any(term in normalized_excerpt for term in result_terms)
            value_in_excerpt = numeric and bool(re.search(
                rf"(?<!\d){re.escape(str(measured_value))}(?!\d)", excerpt
            ))
            unit_token = re.sub(r"\s+", "", unit.casefold()).replace("−", "-")
            excerpt_token = re.sub(r"\s+", "", normalize_text(excerpt)).replace("−", "-")
            unit_in_excerpt = bool(unit_token) and unit_token in excerpt_token
            candidate_only = any(term in normalized_excerpt for term in candidate_terms)
            if not (
                numeric and unit_ok and value_in_excerpt and unit_in_excerpt
                and len(context) >= 12 and direct_language
            ):
                errors.append(f"eligibility_criterion_no_direct_result:{criterion_id}")
            if candidate_only:
                errors.append(f"eligibility_criterion_candidate_only:{criterion_id}")
        elif policy == "exact_attribute":
            expected = criterion.get("expected_attributes")
            observed = check.get("observed_attributes")
            subject_venue = check.get("subject_venue")
            if normalize_title_identity(subject_venue) != normalize_title_identity(record.get("venue")):
                errors.append(f"eligibility_criterion_subject_venue_mismatch:{criterion_id}")
            relation = str((evidence_item or {}).get("query_or_relation") or "")
            if normalize_title_identity(record.get("venue")) not in normalize_title_identity(relation):
                errors.append(f"eligibility_criterion_attribute_source_unbound:{criterion_id}")
            if not isinstance(observed, dict):
                errors.append(f"eligibility_criterion_missing_observed_attributes:{criterion_id}")
            elif normalize_json_value(observed) != normalize_json_value(expected):
                errors.append(f"eligibility_criterion_attribute_mismatch:{criterion_id}")
    return list(dict.fromkeys(errors))


def valid_authors(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and any(str(v).strip() for v in item.values()):
            continue
        return False
    return True


def valid_year(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return 1500 <= year <= date.today().year + 1


def audit_record(
    record: dict[str, Any], index: int,
    doi_verification: dict[int, dict[str, Any]] | None = None,
    require_doi_verification: bool = False,
    screening_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    evidence = evidence_entries(record)

    if not str(record.get("title") or "").strip():
        errors.append("missing_title")
    if not valid_authors(record.get("authors")):
        errors.append("missing_or_invalid_authors")
    if not valid_year(record.get("year")):
        errors.append("missing_or_invalid_year")
    if not str(record.get("venue") or "").strip():
        errors.append("missing_venue")
    if not has_stable_id(record):
        errors.append("missing_stable_identifier")

    traceable = [item for item in evidence if traceable_evidence(item)]
    discovery = [item for item in traceable if str(item.get("role") or "").casefold() == "discovery"]
    if not discovery:
        errors.append("missing_discovery_evidence")

    # Query URNs are discovery traces only and never confirm identity.
    identity = [
        item for item in traceable
        if supports_identity(item) and not str(item.get("locator") or "").casefold().startswith("urn:")
    ]
    direct = [item for item in identity if trusted_direct_identity(item, record)]
    structured_providers = {
        structured_source_key(item) for item in identity
        if trusted_structured_identity(item, record) and structured_source_key(item)
    }
    doi_errors = doi_gate_errors(record, index, doi_verification) if require_doi_verification else []
    doi_identity_confirmed = (
        require_doi_verification
        and bool(str(record.get("doi") or "").strip())
        and not doi_errors
    )
    if not direct and len(structured_providers) < 2 and not doi_identity_confirmed:
        errors.append("identity_not_confirmed")

    if require_doi_verification:
        errors.extend(doi_errors)

    errors.extend(screening_errors(record, traceable, screening_contract))

    basis = str(record.get("relevance_basis") or "").casefold()
    if basis not in VALID_BASIS:
        errors.append("missing_relevance_basis")
    elif basis == "title":
        warnings.append("title_only_relevance")

    claims = record.get("claims")
    if claims is not None:
        if not isinstance(claims, list):
            errors.append("claims_must_be_list")
        else:
            content_by_locator = {
                str(item.get("locator") or "").strip(): item
                for item in traceable
                if supports_content(item)
                and not str(item.get("locator") or "").casefold().startswith("urn:")
            }
            for claim_index, claim in enumerate(claims):
                if not isinstance(claim, dict):
                    errors.append(f"claim_{claim_index}_invalid")
                    continue
                claim_basis = str(claim.get("basis") or "").casefold()
                if claim_basis not in {"abstract", "fulltext"}:
                    errors.append(f"claim_{claim_index}_unsupported_basis")
                locator = claim.get("locator")
                if not valid_locator(locator) or str(locator).casefold().startswith("urn:"):
                    errors.append(f"claim_{claim_index}_missing_locator")
                else:
                    evidence_item = content_by_locator.get(str(locator).strip())
                    if not supports_claim_basis(evidence_item or {}, claim_basis, record):
                        errors.append(f"claim_{claim_index}_unlinked_locator_or_basis")
                if not isinstance(claim.get("text"), str) or not claim["text"].strip():
                    errors.append(f"claim_{claim_index}_missing_text")
                excerpt = claim.get("evidence_excerpt") or claim.get("quote")
                if not isinstance(excerpt, str) or len(excerpt.strip()) < 12:
                    errors.append(f"claim_{claim_index}_missing_evidence_excerpt")

    declared = str(record.get("verification_status") or "").casefold()
    if declared and declared not in {"confirmed", "provisional", "conflict"}:
        errors.append("invalid_verification_status")
    if declared == "conflict":
        errors.append("declared_metadata_conflict")
    if declared == "provisional":
        warnings.append("declared_provisional")

    computed = "confirmed" if not errors and declared != "provisional" else "provisional"
    if declared == "confirmed" and errors:
        errors.append("declared_confirmed_but_gate_failed")

    return {
        "index": index,
        "title": record.get("title", ""),
        "computed_status": computed,
        "errors": errors,
        "warnings": warnings,
    }


def audit(
    records: list[dict[str, Any]],
    doi_verification: dict[int, dict[str, Any]] | None = None,
    require_doi_verification: bool = False,
    global_errors: list[str] | None = None,
    screening_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results = [
        audit_record(
            record, index, doi_verification, require_doi_verification, screening_contract
        )
        for index, record in enumerate(records)
    ]
    global_errors = list(dict.fromkeys(global_errors or []))
    confirmed = sum(item["computed_status"] == "confirmed" for item in results)
    all_confirmed = confirmed == len(records) and not global_errors
    return {
        "input_count": len(records),
        "confirmed_count": confirmed,
        "provisional_count": len(records) - confirmed,
        "all_confirmed": all_confirmed,
        "doi_verification_consumed": require_doi_verification,
        "global_errors": global_errors,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit literature-record provenance")
    parser.add_argument("input", type=Path, help="Input JSON array or object with records[]")
    parser.add_argument("--output", "-o", type=Path, help="Write audit JSON to this path")
    parser.add_argument(
        "--doi-verification", type=Path,
        help="JSON output from verify_doi_records.py; required by --strict for DOI records",
    )
    parser.add_argument("--strict", action="store_true", help="Exit 2 if any record is provisional")
    parser.add_argument(
        "--require-screening-contract", action="store_true",
        help="Require an external frozen screening contract and per-record eligibility checks",
    )
    parser.add_argument(
        "--screening-contract", type=Path,
        help="External frozen screening-contract JSON; required with --require-screening-contract",
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise SystemExit("Input must be a JSON array of objects or an object containing records[]")

    verification: dict[int, dict[str, Any]] | None = None
    global_errors: list[str] = []
    embedded_contract = payload.get("screening_contract") if isinstance(payload, dict) else None
    screening_contract: dict[str, Any] | None = None
    if args.require_screening_contract:
        if not args.screening_contract:
            global_errors.append("missing_external_screening_contract")
        else:
            contract_payload = json.loads(args.screening_contract.read_text(encoding="utf-8-sig"))
            if not isinstance(contract_payload, dict):
                global_errors.append("invalid_external_screening_contract")
            else:
                screening_contract = contract_payload
                if not isinstance(embedded_contract, dict):
                    global_errors.append("missing_embedded_screening_contract")
                elif screening_contract_fingerprint(embedded_contract) != screening_contract_fingerprint(screening_contract):
                    global_errors.append("screening_contract_payload_mismatch")
    if args.doi_verification:
        verification_payload = json.loads(args.doi_verification.read_text(encoding="utf-8-sig"))
        verification, sidecar_errors = doi_verification_map(
            verification_payload, len(records), screening_contract
        )
        global_errors.extend(sidecar_errors)

    result = audit(
        records,
        verification,
        require_doi_verification=args.strict,
        global_errors=global_errors,
        screening_contract=screening_contract if args.require_screening_contract else None,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 2 if args.strict and not result["all_confirmed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
