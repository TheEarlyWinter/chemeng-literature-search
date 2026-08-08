#!/usr/bin/env python3
"""Deduplicate scholarly records without external dependencies.

Input: a JSON array or {"records": [...]}.
Exact DOI and stable-ID matches merge automatically. Exact normalized-title matches
merge only when publication years differ by at most one. Similar titles are reported
as possible duplicates and are never silently merged.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
STABLE_ID_KEY_MAP = {
    "pmid": "pmid",
    "pmcid": "pmcid",
    "arxiv": "arxiv",
    "openalex": "openalex",
    "semantic_scholar": "semantic_scholar",
    "s2": "semantic_scholar",
    "lens": "lens",
    "handle": "handle",
    "cnki": "cnki",
    "cnki_record_id": "cnki",
    "wanfang": "wanfang",
    "wanfang_record_id": "wanfang",
    "cqvip": "cqvip",
    "vip_record_id": "cqvip",
}
STABLE_ID_KEYS = tuple(STABLE_ID_KEY_MAP)


def _trim_doi_wrapper(text: str) -> str:
    """Trim prose wrappers while preserving balanced punctuation inside a DOI."""
    text = text.strip().strip("<>\"'")
    text = text.rstrip(".,")
    pairs = (("(", ")"), ("[", "]"), ("{", "}"))
    changed = True
    while changed and text:
        changed = False
        for opening, closing in pairs:
            if text.endswith(closing) and text.count(closing) > text.count(opening):
                text = text[:-1].rstrip()
                changed = True
    return text


def normalize_doi(value: Any) -> str:
    if not value:
        return ""
    doi = DOI_PREFIX_RE.sub("", str(value).strip())
    doi = _trim_doi_wrapper(doi).lower()
    return doi if DOI_RE.match(doi) else ""


def normalize_title(value: Any) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_id(value: Any) -> str:
    return str(value).strip().casefold() if value is not None else ""


def year_value(record: dict[str, Any]) -> int | None:
    value = record.get("year")
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def record_sources(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = record.get("sources")
    if isinstance(raw, list):
        values.extend(str(v).strip() for v in raw if str(v).strip())
    source = str(record.get("source") or "").strip()
    if source:
        values.append(source)
    return list(dict.fromkeys(values))


def record_urls(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = record.get("urls")
    if isinstance(raw, list):
        values.extend(str(v).strip() for v in raw if str(v).strip())
    url = str(record.get("url") or "").strip()
    if url:
        values.append(url)
    return list(dict.fromkeys(values))


def stable_ids(record: dict[str, Any]) -> set[tuple[str, str]]:
    ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
    found: set[tuple[str, str]] = set()
    for key, canonical_key in STABLE_ID_KEY_MAP.items():
        value = ids.get(key) or record.get(key)
        norm = normalize_id(value)
        if norm:
            found.add((canonical_key, norm))
    return found


def record_abstracts(record: dict[str, Any]) -> list[dict[str, str]]:
    """Return abstract texts with their provider instead of losing provenance."""
    values: list[dict[str, str]] = []
    raw = record.get("abstracts")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            provider = str(item.get("provider") or item.get("source") or "").strip()
            locator = str(item.get("locator") or "").strip()
            if text:
                values.append({"text": text, "provider": provider, "locator": locator})
    abstract = str(record.get("abstract") or "").strip()
    if abstract:
        provider = str(record.get("abstract_source") or record.get("source") or "").strip()
        locator = str(record.get("abstract_url") or record.get("url") or "").strip()
        values.append({"text": abstract, "provider": provider, "locator": locator})

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values:
        key = (item["text"], item["provider"].casefold(), item["locator"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def exact_match(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    doi_a, doi_b = normalize_doi(a.get("doi")), normalize_doi(b.get("doi"))
    if doi_a and doi_b:
        # Two different valid DOIs are an identity conflict. Never hide it by
        # falling through to a title match, even when the titles are identical.
        if doi_a == doi_b:
            return True, "doi"
        return False, "doi_conflict"

    if stable_ids(a) & stable_ids(b):
        return True, "stable_id"

    title_a, title_b = normalize_title(a.get("title")), normalize_title(b.get("title"))
    if title_a and title_a == title_b:
        year_a, year_b = year_value(a), year_value(b)
        # Missing years make title-only merging too risky. Keep both records and
        # let the possible-duplicate report send them to manual verification.
        if year_a is not None and year_b is not None and abs(year_a - year_b) <= 1:
            return True, "title_year"
    return False, ""


def merge_dict(base: dict[str, Any], incoming: dict[str, Any], reason: str) -> dict[str, Any]:
    merged = deepcopy(base)

    # Prefer valid DOI and otherwise fill only empty scalar fields.
    if not normalize_doi(merged.get("doi")) and normalize_doi(incoming.get("doi")):
        merged["doi"] = normalize_doi(incoming.get("doi"))
    elif normalize_doi(merged.get("doi")):
        merged["doi"] = normalize_doi(merged.get("doi"))

    for key, value in incoming.items():
        if key in {
            "source", "sources", "url", "urls", "ids", "authors",
            "citation_count", "citation_source", "abstract", "abstracts",
            "abstract_source", "abstract_url",
        }:
            continue
        if merged.get(key) in (None, "", [], {}):
            merged[key] = deepcopy(value)

    # Keep provenance as sets represented by stable-order lists.
    merged["sources"] = list(dict.fromkeys(record_sources(base) + record_sources(incoming)))
    merged["urls"] = list(dict.fromkeys(record_urls(base) + record_urls(incoming)))
    merged.pop("source", None)
    merged.pop("url", None)

    ids: dict[str, Any] = {}
    for record in (base, incoming):
        raw_ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
        for key in STABLE_ID_KEYS:
            value = raw_ids.get(key) or record.get(key)
            if value and key not in ids:
                ids[key] = value
    if ids:
        merged["ids"] = ids

    authors: list[Any] = []
    for record in (base, incoming):
        raw = record.get("authors")
        if isinstance(raw, list):
            authors.extend(raw)
        elif raw:
            authors.append(raw)
    if authors:
        seen: set[str] = set()
        merged_authors: list[Any] = []
        for author in authors:
            key = json.dumps(author, ensure_ascii=False, sort_keys=True) if isinstance(author, dict) else str(author).casefold()
            if key not in seen:
                seen.add(key)
                merged_authors.append(author)
        merged["authors"] = merged_authors

    abstracts = record_abstracts(base) + record_abstracts(incoming)
    if abstracts:
        seen_abstracts: set[tuple[str, str, str]] = set()
        merged_abstracts: list[dict[str, str]] = []
        for item in abstracts:
            key = (item["text"], item["provider"].casefold(), item["locator"])
            if key not in seen_abstracts:
                seen_abstracts.add(key)
                merged_abstracts.append(item)
        merged["abstracts"] = merged_abstracts
        merged.pop("abstract", None)
        merged.pop("abstract_source", None)
        merged.pop("abstract_url", None)

    citation_metrics = merged.get("citation_metrics") if isinstance(merged.get("citation_metrics"), dict) else {}
    for record in (base, incoming):
        count = record.get("citation_count")
        source = record.get("citation_source") or record.get("source")
        if count is not None and source:
            citation_metrics[str(source)] = count
    if citation_metrics:
        merged["citation_metrics"] = citation_metrics
    merged.pop("citation_count", None)
    merged.pop("citation_source", None)

    history = merged.get("merge_reasons") if isinstance(merged.get("merge_reasons"), list) else []
    merged["merge_reasons"] = list(dict.fromkeys(history + [reason]))
    merged["version_count"] = int(base.get("version_count") or 1) + int(incoming.get("version_count") or 1)
    return merged


def possible_duplicates(records: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(records):
        left_title = normalize_title(left.get("title"))
        if not left_title:
            continue
        for j in range(i + 1, len(records)):
            right = records[j]
            right_title = normalize_title(right.get("title"))
            if not right_title:
                continue
            ratio = SequenceMatcher(None, left_title, right_title).ratio()
            if ratio < threshold:
                continue
            y1, y2 = year_value(left), year_value(right)
            if y1 is not None and y2 is not None and abs(y1 - y2) > 2:
                continue
            left_doi = normalize_doi(left.get("doi"))
            right_doi = normalize_doi(right.get("doi"))
            reason = "similar_title"
            if left_doi and right_doi and left_doi != right_doi:
                reason = "doi_conflict"
            elif left_title == right_title and (y1 is None or y2 is None):
                reason = "missing_year"
            pairs.append({
                "left_index": i,
                "right_index": j,
                "similarity": round(ratio, 4),
                "reason": reason,
                "left_title": left.get("title", ""),
                "right_title": right.get("title", ""),
                "left_doi": left_doi,
                "right_doi": right_doi,
            })
    return pairs


def dedupe(records: list[dict[str, Any]], similarity_threshold: float = 0.92) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("Every record must be a JSON object")
        candidate = deepcopy(raw)
        candidate["doi"] = normalize_doi(candidate.get("doi")) or candidate.get("doi", "")
        for index, existing in enumerate(merged):
            matched, reason = exact_match(existing, candidate)
            if matched:
                merged[index] = merge_dict(existing, candidate, reason)
                break
        else:
            candidate["sources"] = record_sources(candidate)
            candidate["urls"] = record_urls(candidate)
            abstracts = record_abstracts(candidate)
            if abstracts:
                candidate["abstracts"] = abstracts
                candidate.pop("abstract", None)
                candidate.pop("abstract_source", None)
                candidate.pop("abstract_url", None)
            candidate.pop("source", None)
            candidate.pop("url", None)
            candidate["version_count"] = int(candidate.get("version_count") or 1)
            merged.append(candidate)

    return {
        "input_count": len(records),
        "unique_count": len(merged),
        "merged_count": len(records) - len(merged),
        "records": merged,
        "possible_duplicates": possible_duplicates(merged, similarity_threshold),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate scholarly metadata records")
    parser.add_argument("input", type=Path, help="Input JSON array or object with records[]")
    parser.add_argument("--output", "-o", type=Path, help="Write result JSON to this path")
    parser.add_argument("--similarity-threshold", type=float, default=0.92)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise SystemExit("Input must be a JSON array or an object containing records[]")
    if not 0.0 <= args.similarity_threshold <= 1.0:
        raise SystemExit("--similarity-threshold must be between 0 and 1")

    result = dedupe(records, args.similarity_threshold)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
