#!/usr/bin/env python3
"""Verify DOI existence and title correspondence against live registries.

Crossref and DataCite are queried first. If neither registry contains the DOI, DOI
content negotiation is attempted because some Chinese and regional registration
agencies are not mirrored by those two APIs. Missing DOI is not an error; a
non-empty malformed DOI is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
USER_AGENT = "chemeng-literature-search/0.3.1 (+https://github.com/liliMozi/openhanako)"


def raw_doi(value: Any) -> str:
    if value is None:
        return ""
    return DOI_PREFIX_RE.sub("", str(value).strip()).strip("<>\"'").rstrip(".,").lower()


def normalize_doi(value: Any) -> str:
    doi = raw_doi(value)
    return doi if DOI_RE.match(doi) else ""


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
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


def title_similarity(left: Any, right: Any) -> float:
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def fetch_json(url: str, timeout: float, accept: str = "application/json") -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Registry response is not a JSON object")
    return payload


def date_parts_year(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            return None
    return None


def crossref_lookup(doi: str, timeout: float) -> dict[str, Any]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    payload = fetch_json(url, timeout)
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    titles = message.get("title") if isinstance(message.get("title"), list) else []
    containers = message.get("container-title") if isinstance(message.get("container-title"), list) else []
    year = None
    for key in ("published-print", "published-online", "published", "issued", "created"):
        year = date_parts_year(message.get(key))
        if year:
            break
    return {
        "title": str(titles[0]).strip() if titles else "",
        "authors": message.get("author") if isinstance(message.get("author"), list) else [],
        "year": year,
        "venue": str(containers[0]).strip() if containers else "",
        "document_type": str(message.get("type") or "").strip(),
        "doi": normalize_doi(message.get("DOI") or message.get("doi")) or doi,
        "url": url,
    }


def datacite_lookup(doi: str, timeout: float) -> dict[str, Any]:
    url = f"https://api.datacite.org/dois/{quote(doi, safe='')}"
    payload = fetch_json(url, timeout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    titles = attrs.get("titles") if isinstance(attrs.get("titles"), list) else []
    title = str(titles[0].get("title") or "").strip() if titles and isinstance(titles[0], dict) else ""
    container = attrs.get("container") if isinstance(attrs.get("container"), dict) else {}
    types = attrs.get("types") if isinstance(attrs.get("types"), dict) else {}
    try:
        year = int(attrs.get("publicationYear")) if attrs.get("publicationYear") is not None else None
    except (TypeError, ValueError):
        year = None
    return {
        "title": title,
        "authors": attrs.get("creators") if isinstance(attrs.get("creators"), list) else [],
        "year": year,
        "venue": str(container.get("title") or attrs.get("publisher") or "").strip(),
        "document_type": str(types.get("resourceTypeGeneral") or types.get("resourceType") or "").strip(),
        "doi": normalize_doi(attrs.get("doi") or data.get("id")) or doi,
        "url": url,
    }


def doi_content_lookup(doi: str, timeout: float) -> dict[str, Any]:
    """Resolve DOI using CSL-JSON content negotiation.

    This is a DOI registration-path check, not a generic publisher-page scrape.
    It is used only after Crossref and DataCite both return 404.
    """
    url = f"https://doi.org/{quote(doi, safe='/')}"
    payload = fetch_json(url, timeout, "application/vnd.citationstyles.csl+json")
    title_value = payload.get("title")
    if isinstance(title_value, list):
        title = str(title_value[0]).strip() if title_value else ""
    else:
        title = str(title_value or "").strip()
    returned_doi = normalize_doi(payload.get("DOI") or payload.get("doi") or payload.get("id"))
    if returned_doi and returned_doi != doi:
        raise ValueError("Resolved metadata returned a different DOI")
    container = payload.get("container-title")
    if isinstance(container, list):
        container = container[0] if container else ""
    return {
        "title": title,
        "authors": payload.get("author") if isinstance(payload.get("author"), list) else [],
        "year": date_parts_year(payload.get("issued") or payload.get("published")),
        "venue": str(container or payload.get("publisher") or "").strip(),
        "document_type": str(payload.get("type") or "").strip(),
        "doi": returned_doi or doi,
        "url": url,
    }


def author_family(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("family") or value.get("name") or value.get("literal")
        text = normalize_title(raw)
        return "" if text in {"", "et al", "etal"} else text
    raw = value
    text = normalize_title(raw)
    if not text or text in {"et al", "etal"}:
        return ""
    if "," in str(value):
        return normalize_title(str(value).split(",", 1)[0])
    return text.split()[-1]


def normalized_document_type(value: Any) -> str:
    text = normalize_title(value).replace(" ", "-")
    aliases = {
        "article": "journal-article", "journalarticle": "journal-article",
        "journal-article": "journal-article", "research-article": "journal-article",
        "review": "review", "review-article": "review",
    }
    return aliases.get(text, text)


def metadata_errors(record: dict[str, Any], metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    conflicts: list[str] = []
    missing: list[str] = []
    title = str(metadata.get("title") or "").strip()
    if not title:
        missing.append("registry_record_has_no_title")
    elif normalize_title(record.get("title")) != normalize_title(title):
        conflicts.append("doi_title_mismatch")

    supplied = [author_family(value) for value in record.get("authors", [])] \
        if isinstance(record.get("authors"), list) else []
    supplied = [value for value in supplied if value]
    registered = [author_family(value) for value in metadata.get("authors", [])] \
        if isinstance(metadata.get("authors"), list) else []
    registered = [value for value in registered if value]
    if not registered:
        missing.append("registry_record_has_no_authors")
    elif not supplied or supplied[0] != registered[0] or not set(supplied).issubset(set(registered)):
        conflicts.append("doi_authors_mismatch")

    registry_year = metadata.get("year")
    if registry_year is None:
        missing.append("registry_record_has_no_year")
    else:
        try:
            if int(str(record.get("year")).strip()) != int(registry_year):
                conflicts.append("doi_year_mismatch")
        except (TypeError, ValueError):
            conflicts.append("doi_year_mismatch")

    registry_venue = str(metadata.get("venue") or "").strip()
    if not registry_venue:
        missing.append("registry_record_has_no_venue")
    elif normalize_title(record.get("venue")) != normalize_title(registry_venue):
        conflicts.append("doi_venue_mismatch")

    supplied_type = normalized_document_type(record.get("document_type"))
    registry_type = normalized_document_type(metadata.get("document_type"))
    container_types = {
        "journal-article", "proceedings-article", "posted-content", "book-chapter", "dissertation"
    }
    if supplied_type in container_types:
        if not registry_type:
            missing.append("registry_record_has_no_document_type")
        elif supplied_type != registry_type:
            conflicts.append("doi_document_type_mismatch")
    return conflicts, missing


def verified_result(
    result: dict[str, Any], registry: str, metadata: dict[str, Any],
    supplied_title: str, threshold: float, record: dict[str, Any],
) -> dict[str, Any]:
    registry_title = str(metadata.get("title") or "")
    result["registry"] = registry
    result["registry_title"] = registry_title
    result["registry_url"] = str(metadata.get("url") or "")
    result["registry_metadata"] = {
        key: metadata.get(key) for key in ("doi", "authors", "year", "venue", "document_type")
    }
    result["title_similarity"] = round(title_similarity(supplied_title, registry_title), 4) if registry_title else None
    conflicts, missing = metadata_errors(record, metadata)
    if conflicts:
        result["status"] = "conflict"
        result["errors"].extend(conflicts)
    elif missing:
        result["status"] = "unavailable"
        result["errors"].extend(missing)
    else:
        result["status"] = "verified"
    return result


def verify_record(record: dict[str, Any], index: int, timeout: float, threshold: float) -> dict[str, Any]:
    if not 0.92 <= threshold <= 1.0:
        raise ValueError("title threshold must be between 0.92 and 1")
    supplied_raw_doi = raw_doi(record.get("doi"))
    doi = normalize_doi(record.get("doi"))
    supplied_title = str(record.get("title") or "").strip()
    result: dict[str, Any] = {
        "index": index,
        "doi": doi or supplied_raw_doi,
        "supplied_title": supplied_title,
        "record_fingerprint": record_fingerprint(record),
        "status": "unverified",
        "registry": "",
        "registry_title": "",
        "registry_url": "",
        "title_similarity": None,
        "errors": [],
    }
    if not supplied_raw_doi:
        result["status"] = "not_applicable"
        return result
    if not doi:
        result["status"] = "invalid_doi"
        result["errors"].append("invalid_doi_format")
        return result
    if not supplied_title:
        result["status"] = "conflict"
        result["errors"].append("missing_supplied_title")
        return result

    not_found = 0
    unavailable: list[str] = []
    for registry, lookup in (("crossref", crossref_lookup), ("datacite", datacite_lookup)):
        try:
            metadata = lookup(doi, timeout)
        except HTTPError as exc:
            if exc.code == 404:
                not_found += 1
            else:
                unavailable.append(f"{registry}:http_{exc.code}")
            continue
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            unavailable.append(f"{registry}:{type(exc).__name__}")
            continue
        return verified_result(result, registry, metadata, supplied_title, threshold, record)

    # If either primary registry was unavailable, do not turn a partial outage
    # into a nonexistence claim. Content negotiation may still positively verify.
    try:
        metadata = doi_content_lookup(doi, timeout)
    except HTTPError as exc:
        if exc.code == 404 and not_found == 2:
            result["status"] = "not_found"
            result["errors"].append("doi_not_found_in_registries_or_content_negotiation")
        else:
            result["status"] = "unavailable"
            result["errors"].extend(unavailable + [f"doi_content:http_{exc.code}"])
        return result
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        result["status"] = "unavailable"
        result["errors"].extend(unavailable + [f"doi_content:{type(exc).__name__}"])
        return result

    return verified_result(
        result, "doi_content_negotiation", metadata, supplied_title, threshold, record
    )


def verify(
    records: list[dict[str, Any]], timeout: float = 10.0, threshold: float = 0.92,
    screening_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not 0.92 <= threshold <= 1.0:
        raise ValueError("title threshold must be between 0.92 and 1")
    results = [verify_record(record, index, timeout, threshold) for index, record in enumerate(records)]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    hard_failed = sum(counts.get(key, 0) for key in ("conflict", "not_found", "invalid_doi"))
    doi_records = sum(count for key, count in counts.items() if key != "not_applicable")
    verified = counts.get("verified", 0)
    verification_complete = verified == doi_records
    return {
        "input_count": len(records),
        "doi_record_count": doi_records,
        "status_counts": counts,
        "hard_failure_count": hard_failed,
        "no_hard_identity_conflict": hard_failed == 0,
        "verification_complete": verification_complete,
        "all_verifiable_dois_match": verification_complete,
        "all_doi_records_verified": verification_complete,
        "screening_contract_fingerprint": screening_contract_fingerprint(screening_contract),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DOI-title pairs using live DOI metadata")
    parser.add_argument("input", type=Path, help="Input JSON array or object with records[]")
    parser.add_argument("--output", "-o", type=Path, help="Write verification JSON")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--title-threshold", type=float, default=0.92)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 2 for mismatch/not-found/invalid DOI; missing DOI is not applicable",
    )
    args = parser.parse_args()

    if not 0.92 <= args.title_threshold <= 1.0:
        raise SystemExit("--title-threshold must be between 0.92 and 1")
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise SystemExit("Input must be a JSON array of objects or an object containing records[]")

    screening_contract = payload.get("screening_contract") if isinstance(payload, dict) else None
    result = verify(records, args.timeout, args.title_threshold, screening_contract)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 2 if args.strict and not result["verification_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
