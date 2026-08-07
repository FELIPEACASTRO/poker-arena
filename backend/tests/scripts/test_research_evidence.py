from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs" / "research" / "evidence"

INVENTORY_PATH = EVIDENCE_ROOT / "platform_inventory.json"
PRIMARY_FINDINGS_PATH = EVIDENCE_ROOT / "primary_candidate_findings.json"
REGIONAL_SUPPLEMENT_PATH = EVIDENCE_ROOT / "regional_platform_supplement_20260717.json"
SWEEP_SPECS = {
    EVIDENCE_ROOT / "platform_sweep_sections_1_4.json": frozenset(range(1, 5)),
    EVIDENCE_ROOT / "platform_sweep_sections_5_8.json": frozenset(range(5, 9)),
    EVIDENCE_ROOT / "platform_sweep_sections_9_12.json": frozenset(range(9, 13)),
}
MANDATORY_PATHS = (
    INVENTORY_PATH,
    EVIDENCE_ROOT / "platform_sweep_sections_5_8.json",
    EVIDENCE_ROOT / "platform_sweep_sections_9_12.json",
    PRIMARY_FINDINGS_PATH,
    REGIONAL_SUPPLEMENT_PATH,
)

EXPECTED_PLATFORM_COUNT = 156
EXPECTED_SECTIONS = frozenset(range(1, 13))
HEX_16 = re.compile(r"[0-9a-f]{16}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def _load_object(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"missing research receipt: {path.relative_to(REPOSITORY_ROOT)}"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid UTF-8 JSON receipt: {path.name}: {error}") from error
    assert isinstance(parsed, dict), f"receipt root must be an object: {path.name}"
    return parsed


def _nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping | Sequence) and not isinstance(value, bytes):
        return bool(value)
    return True


def _assert_nonempty(value: object, context: str) -> None:
    assert _nonempty(value), f"empty research evidence field: {context}"
    if isinstance(value, Mapping):
        for key, child in value.items():
            assert isinstance(key, str) and key.strip(), f"empty object key: {context}"
            _assert_nonempty(child, f"{context}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, child in enumerate(value):
            _assert_nonempty(child, f"{context}[{index}]")


def _assert_http_url(value: object, context: str) -> str:
    assert isinstance(value, str) and value.strip(), f"missing URL: {context}"
    parsed = urlsplit(value)
    assert parsed.scheme in {"http", "https"} and parsed.netloc, (
        f"invalid absolute HTTP(S) URL: {context}: {value!r}"
    )
    assert parsed.username is None and parsed.password is None, (
        f"credentials must not be embedded in URL: {context}"
    )
    return value


def _assert_unique(values: Iterable[str], context: str) -> None:
    materialized = list(values)
    duplicates = sorted(value for value, count in Counter(materialized).items() if count > 1)
    assert not duplicates, f"duplicate {context}: {duplicates}"


def _platform_key(record: Mapping[str, Any], context: str) -> tuple[int, str]:
    section_value = record.get("section")
    assert isinstance(section_value, int | str), f"invalid section: {context}"
    try:
        section = int(section_value)
    except ValueError as error:
        raise AssertionError(f"invalid section: {context}: {section_value!r}") from error
    url = record.get("requested_url", record.get("url"))
    return section, _assert_http_url(url, f"{context}.url")


def _sweep_paths() -> list[Path]:
    return [path for path in SWEEP_SPECS if path.is_file()]


def _platform_records(receipt: Mapping[str, Any], receipt_name: str) -> list[dict[str, Any]]:
    records = receipt.get("platforms", receipt.get("platform_audit"))
    assert isinstance(records, list) and records, f"empty platform audit: {receipt_name}"
    assert all(isinstance(record, dict) for record in records), (
        f"platform audit entries must be objects: {receipt_name}"
    )
    return records


def _assert_records_have_unique_ids(
    receipt: Mapping[str, Any], collection_name: str, receipt_name: str
) -> None:
    records = receipt.get(collection_name)
    if records is None:
        return
    assert isinstance(records, list) and records, (
        f"{receipt_name}.{collection_name} must be a non-empty list"
    )
    identifiers: list[str] = []
    for index, record in enumerate(records):
        context = f"{receipt_name}.{collection_name}[{index}]"
        assert isinstance(record, dict), f"{context} must be an object"
        identifier = record.get("id")
        assert isinstance(identifier, str) and identifier.strip(), f"missing ID: {context}"
        identifiers.append(identifier)
    _assert_unique(identifiers, f"IDs in {receipt_name}.{collection_name}")


def _assert_records_have_unique_urls(
    receipt: Mapping[str, Any], collection_name: str, receipt_name: str
) -> None:
    records = receipt.get(collection_name)
    if records is None:
        return
    assert isinstance(records, list) and records
    urls: list[str] = []
    for index, record in enumerate(records):
        context = f"{receipt_name}.{collection_name}[{index}]"
        url_fields = {
            key: value
            for key, value in record.items()
            if key == "url" or key.endswith("_url")
        }
        assert url_fields, f"missing URL field: {context}"
        urls.extend(
            _assert_http_url(value, f"{context}.{key}") for key, value in url_fields.items()
        )
    _assert_unique(urls, f"URLs in {receipt_name}.{collection_name}")


def test_mandatory_research_receipts_are_valid_utf8_json_objects() -> None:
    for path in MANDATORY_PATHS:
        receipt = _load_object(path)
        assert _nonempty(receipt.get("schema_version")), f"missing schema_version: {path.name}"

    optional_sweep = EVIDENCE_ROOT / "platform_sweep_sections_1_4.json"
    if optional_sweep.exists():
        assert _nonempty(_load_object(optional_sweep).get("schema_version"))


def test_platform_inventory_has_unique_stable_ids_urls_and_expected_sections() -> None:
    inventory = _load_object(INVENTORY_PATH)
    platforms = inventory.get("platforms")
    assert isinstance(platforms, list)
    assert inventory.get("platform_count") == EXPECTED_PLATFORM_COUNT == len(platforms)

    identifiers: list[str] = []
    urls: list[str] = []
    actual_section_counts: Counter[int] = Counter()
    for index, platform in enumerate(platforms):
        context = f"platform_inventory.platforms[{index}]"
        assert isinstance(platform, dict), f"{context} must be an object"
        identifier = platform.get("inventory_id")
        assert isinstance(identifier, str) and HEX_16.fullmatch(identifier), (
            f"invalid inventory_id: {context}"
        )
        section, url = _platform_key(platform, context)
        assert section in EXPECTED_SECTIONS, f"unexpected section: {context}: {section}"
        assert isinstance(platform.get("name"), str) and platform["name"].strip()
        identifiers.append(identifier)
        urls.append(url)
        actual_section_counts[section] += 1

    _assert_unique(identifiers, "inventory IDs")
    _assert_unique(urls, "inventory URLs")
    assert frozenset(actual_section_counts) == EXPECTED_SECTIONS
    assert inventory.get("section_counts") == {
        str(section): actual_section_counts[section] for section in sorted(EXPECTED_SECTIONS)
    }

    source = inventory.get("source")
    assert isinstance(source, dict)
    assert isinstance(source.get("sha256"), str) and HEX_64.fullmatch(source["sha256"])


def test_each_available_sweep_exactly_covers_its_inventory_sections() -> None:
    inventory = _load_object(INVENTORY_PATH)
    inventory_platforms = inventory["platforms"]
    assert isinstance(inventory_platforms, list)

    inventory_keys = {
        _platform_key(record, f"platform_inventory.platforms[{index}]")
        for index, record in enumerate(inventory_platforms)
    }

    for sweep_path in _sweep_paths():
        sweep = _load_object(sweep_path)
        expected_sections = SWEEP_SPECS[sweep_path]
        platforms = _platform_records(sweep, sweep_path.name)

        sweep_keys = [
            _platform_key(record, f"{sweep_path.name}.platforms[{index}]")
            for index, record in enumerate(platforms)
        ]
        assert frozenset(section for section, _ in sweep_keys) == expected_sections
        assert len(sweep_keys) == len(set(sweep_keys)), f"duplicate platform: {sweep_path.name}"

        expected_keys = {key for key in inventory_keys if key[0] in expected_sections}
        assert set(sweep_keys) == expected_keys, (
            f"{sweep_path.name} does not exactly cover its inventory sections"
        )


def test_complete_sweep_union_covers_all_156_inventory_platforms() -> None:
    first_sweep = EVIDENCE_ROOT / "platform_sweep_sections_1_4.json"
    if not first_sweep.is_file():
        pytest.skip("sections 1-4 receipt has not been produced yet")

    inventory = _load_object(INVENTORY_PATH)
    inventory_platforms = inventory["platforms"]
    assert isinstance(inventory_platforms, list)
    inventory_keys = {
        _platform_key(record, f"platform_inventory.platforms[{index}]")
        for index, record in enumerate(inventory_platforms)
    }

    covered: list[tuple[int, str]] = []
    covered_sections: set[int] = set()
    for sweep_path in SWEEP_SPECS:
        sweep = _load_object(sweep_path)
        platforms = _platform_records(sweep, sweep_path.name)
        for index, record in enumerate(platforms):
            key = _platform_key(record, f"{sweep_path.name}.platforms[{index}]")
            covered.append(key)
            covered_sections.add(key[0])

    assert covered_sections == EXPECTED_SECTIONS
    assert len(covered) == len(set(covered)) == EXPECTED_PLATFORM_COUNT
    assert set(covered) == inventory_keys


def test_finding_and_query_identifiers_and_primary_urls_are_unique() -> None:
    primary = _load_object(PRIMARY_FINDINGS_PATH)
    _assert_records_have_unique_ids(primary, "findings", PRIMARY_FINDINGS_PATH.name)
    primary_findings = primary["findings"]
    assert isinstance(primary_findings, list)
    primary_urls = [
        _assert_http_url(record.get("primary_url"), f"primary.findings[{index}].primary_url")
        for index, record in enumerate(primary_findings)
    ]
    _assert_unique(primary_urls, "primary finding URLs")

    for sweep_path in _sweep_paths():
        sweep = _load_object(sweep_path)
        for collection_name in (
            "findings",
            "high_signal_findings",
            "candidate_datasets",
            "query_families",
            "targeted_query_audit",
        ):
            _assert_records_have_unique_ids(sweep, collection_name, sweep_path.name)
        for collection_name in ("high_signal_findings", "candidate_datasets"):
            _assert_records_have_unique_urls(sweep, collection_name, sweep_path.name)

        evidence = sweep.get("high_value_primary_evidence")
        if evidence is not None:
            assert isinstance(evidence, list) and evidence
            evidence_urls = [
                _assert_http_url(record.get("url"), f"{sweep_path.name}.evidence[{index}].url")
                for index, record in enumerate(evidence)
            ]
            _assert_unique(evidence_urls, f"primary evidence URLs in {sweep_path.name}")


def test_findings_and_decisions_do_not_contain_empty_fields() -> None:
    primary = _load_object(PRIMARY_FINDINGS_PATH)
    primary_findings = primary.get("findings")
    assert isinstance(primary_findings, list) and primary_findings
    for index, finding in enumerate(primary_findings):
        context = f"{PRIMARY_FINDINGS_PATH.name}.findings[{index}]"
        assert isinstance(finding, dict)
        for required in ("id", "area", "title", "primary_url", "status", "decision"):
            _assert_nonempty(finding.get(required), f"{context}.{required}")
        assert _nonempty(finding.get("source_claim")) or _nonempty(finding.get("source_fact")), (
            f"missing source claim/fact: {context}"
        )
        _assert_nonempty(finding, context)

    for sweep_path in _sweep_paths():
        sweep = _load_object(sweep_path)

        for collection_name in (
            "findings",
            "high_signal_findings",
            "candidate_datasets",
            "high_value_primary_evidence",
            "recommendations",
            "recommended_actions",
        ):
            records = sweep.get(collection_name)
            if records is None:
                continue
            assert isinstance(records, list) and records
            for index, record in enumerate(records):
                context = f"{sweep_path.name}.{collection_name}[{index}]"
                assert isinstance(record, dict), f"{context} must be an object"
                _assert_nonempty(record, context)

        decision_summary = sweep.get("decision_summary")
        if decision_summary is not None:
            _assert_nonempty(decision_summary, f"{sweep_path.name}.decision_summary")


def test_regional_supplement_covers_requested_regions_and_has_unique_findings() -> None:
    receipt = _load_object(REGIONAL_SUPPLEMENT_PATH)
    regions = receipt.get("regions")
    assert isinstance(regions, list) and len(regions) == 4
    assert {region.get("id") for region in regions if isinstance(region, dict)} == {
        "asia",
        "canada",
        "russia",
        "india",
    }
    for index, region in enumerate(regions):
        assert isinstance(region, dict)
        _assert_nonempty(region, f"regional.regions[{index}]")
        platforms = region.get("platforms")
        assert isinstance(platforms, list) and platforms
        for platform_index, platform in enumerate(platforms):
            assert isinstance(platform, dict)
            _assert_http_url(
                platform.get("url"),
                f"regional.regions[{index}].platforms[{platform_index}].url",
            )

    _assert_records_have_unique_ids(receipt, "retained_findings", REGIONAL_SUPPLEMENT_PATH.name)
    _assert_records_have_unique_urls(
        receipt, "retained_findings", REGIONAL_SUPPLEMENT_PATH.name
    )
    _assert_records_have_unique_ids(
        receipt, "integrity_incidents", REGIONAL_SUPPLEMENT_PATH.name
    )
    _assert_nonempty(receipt.get("decision_summary"), "regional.decision_summary")
