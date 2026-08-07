from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts.catalog_search_receipt import (
    FetchResult,
    _build_public_opener,
    _NoProxyHandler,
    _NoRedirectHandler,
    build_public_request,
    collect_snapshot,
    render_markdown,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = (
    BACKEND_ROOT.parent / "docs" / "research" / "evidence" / "catalog_search_snapshot_20260718.json"
)
HARDENING_RECEIPT_PATH = (
    BACKEND_ROOT.parent
    / "docs"
    / "research"
    / "evidence"
    / "catalog_collector_hardening_20260718.json"
)


def _fake_fetcher(url: str, _timeout: float) -> FetchResult:
    common = {
        "collected_at_utc": "2026-07-18T01:02:03+00:00",
        "http_status": 200,
        "outcome": "success",
        "response_bytes": 123,
        "response_sha256": "a" * 64,
        "safe_rate_headers": {},
    }
    if "/api/datasets?" in url:
        return FetchResult(
            [
                {
                    "id": "lab/texas-holdem-hands",
                    "sha": "b" * 40,
                    "tags": ["license:mit", "task_categories:tabular-classification"],
                    "downloads": 12,
                    "likes": 2,
                },
                {
                    "id": "poker-owner/unrelated-music",
                    "tags": ["audio"],
                },
            ],
            common,
        )
    if "/api/models?" in url:
        return FetchResult(
            [
                {
                    "id": "lab/poker-agent",
                    "sha": "c" * 40,
                    "tags": ["reinforcement-learning"],
                    "pipeline_tag": "reinforcement-learning",
                }
            ],
            common,
        )
    if "/datasets/list?" in url:
        return FetchResult(
            [
                {
                    "ref": "owner/poker-hands",
                    "title": "Poker Hands",
                    "subtitle": "Classification data",
                    "url": "https://www.kaggle.com/datasets/owner/poker-hands",
                    "currentVersionNumber": 2,
                    "licenseName": "CC0: Public Domain",
                    "files": [{"name": "must-not-survive.csv"}],
                    "creatorName": "must not survive",
                }
            ],
            common,
        )
    if "/kernels/list?" in url:
        return FetchResult(
            None,
            {
                "collected_at_utc": "2026-07-18T01:02:03+00:00",
                "http_status": 401,
                "outcome": "http_401",
                "safe_rate_headers": {},
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _source(snapshot: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    return next(source for source in snapshot["sources"] if source["source_id"] == source_id)


def test_public_request_has_no_auth_cookie_and_rejects_other_hosts() -> None:
    request = build_public_request("https://huggingface.co/api/models?search=poker")
    headers = {name.casefold(): value for name, value in request.header_items()}

    assert request.get_method() == "GET"
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert set(headers) == {"accept", "user-agent"}

    with pytest.raises(ValueError, match="allowlisted"):
        build_public_request("https://example.com/api/models?search=poker")

    for unsafe in (
        "http://huggingface.co/api/models",
        "https://huggingface.co.evil.example/api/models",
        "https://www.kaggle.com.evil.example/api/v1/datasets/list",
        "https://user:password@huggingface.co/api/models",
        "https://huggingface.co:444/api/models",
        "https://huggingface.co/api/models#fragment",
    ):
        with pytest.raises(ValueError, match="allowlisted"):
            build_public_request(unsafe)


def test_public_opener_disables_proxies_and_redirects() -> None:
    opener = _build_public_opener()
    proxy_handlers = [handler for handler in opener.handlers if isinstance(handler, _NoProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    redirect = next(handler for handler in opener.handlers if isinstance(handler, _NoRedirectHandler))
    assert redirect.redirect_request(None, None, 302, "Found", {}, "https://evil.test/") is None


def test_generated_timestamp_must_be_explicit_utc() -> None:
    with pytest.raises(ValueError, match="UTC"):
        collect_snapshot(
            queries=["poker"],
            hf_limit=2,
            kaggle_pages=1,
            generated_at="2026-07-18T01:02:03",
            fetcher=_fake_fetcher,
        )


def test_snapshot_separates_evidence_and_triage_and_minimizes_fields() -> None:
    snapshot = collect_snapshot(
        queries=["poker"],
        hf_limit=2,
        kaggle_pages=1,
        generated_at="2026-07-18T01:02:03+00:00",
        fetcher=_fake_fetcher,
    )

    assert snapshot["collector"]["authentication"] == "anonymous_only"
    assert snapshot["collector"]["credential_files_or_platform_tokens_read"] is False
    assert snapshot["summary"] == {
        "request_count": 4,
        "successful_requests": 3,
        "failed_or_blocked_requests": 1,
        "unique_candidates": 4,
        "retained_for_manual_review": 3,
        "excluded_at_keyword_screen": 1,
        "by_source": snapshot["summary"]["by_source"],
    }

    hf_datasets = _source(snapshot, "huggingface_datasets")["candidates"]
    assert (
        next(item for item in hf_datasets if item["id"].endswith("unrelated-music"))["triage"][
            "decision"
        ]
        == "exclude_at_keyword_screen"
    )
    kaggle = _source(snapshot, "kaggle_datasets")["candidates"][0]
    assert kaggle["revision_version"] == 2
    assert kaggle["declared_license"] == "CC0: Public Domain"
    assert "files" not in kaggle
    assert "creatorName" not in kaggle
    assert _source(snapshot, "kaggle_code")["requests"][0]["outcome"] == "http_401"


def test_duplicate_results_aggregate_query_provenance() -> None:
    snapshot = collect_snapshot(
        queries=["poker", "poker hand"],
        hf_limit=2,
        kaggle_pages=1,
        generated_at="2026-07-18T01:02:03+00:00",
        fetcher=_fake_fetcher,
    )

    item = next(
        candidate
        for candidate in _source(snapshot, "huggingface_datasets")["candidates"]
        if candidate["id"] == "lab/texas-holdem-hands"
    )
    assert item["matched_queries"] == ["poker", "poker hand"]
    assert item["rank_by_query"] == {"poker": 1, "poker hand": 1}


def test_public_kaggle_code_metadata_would_be_sanitized_without_content() -> None:
    def code_fetcher(url: str, timeout: float) -> FetchResult:
        if "/kernels/list?" in url:
            return FetchResult(
                [
                    {
                        "ref": "owner/texas-holdem-agent",
                        "title": "Texas Holdem Agent",
                        "url": "https://www.kaggle.com/code/owner/texas-holdem-agent",
                        "lastRunTime": "2026-01-01T00:00:00Z",
                        "language": "python",
                        "kernelType": "notebook",
                        "totalVotes": 7,
                        "text": "must not survive",
                        "source": "must not survive",
                    }
                ],
                {
                    "collected_at_utc": "2026-07-18T01:02:03+00:00",
                    "http_status": 200,
                    "outcome": "success",
                    "response_bytes": 100,
                    "response_sha256": "d" * 64,
                    "safe_rate_headers": {},
                },
            )
        return _fake_fetcher(url, timeout)

    snapshot = collect_snapshot(
        queries=["poker"],
        hf_limit=2,
        kaggle_pages=1,
        generated_at="2026-07-18T01:02:03+00:00",
        fetcher=code_fetcher,
    )
    candidate = _source(snapshot, "kaggle_code")["candidates"][0]

    assert candidate["id"] == "owner/texas-holdem-agent"
    assert candidate["triage"]["decision"] == "retain_for_manual_review"
    assert "text" not in candidate
    assert "source" not in candidate


def test_markdown_is_summary_not_a_quality_claim(tmp_path: Path) -> None:
    snapshot = collect_snapshot(
        queries=["poker"],
        hf_limit=2,
        kaggle_pages=1,
        generated_at="2026-07-18T01:02:03+00:00",
        fetcher=_fake_fetcher,
    )
    rendered = render_markdown(snapshot)
    destination = tmp_path / "receipt.md"
    destination.write_text(rendered, encoding="utf-8")

    assert "not an exhaustive internet search" in rendered
    assert "not recommendations or benchmark results" in rendered
    assert "lab/texas-holdem-hands" in rendered
    assert "must-not-survive" not in rendered


def test_committed_live_snapshot_is_internally_consistent_and_sanitized() -> None:
    raw_text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    snapshot = json.loads(raw_text)
    hardening = json.loads(HARDENING_RECEIPT_PATH.read_text(encoding="utf-8"))
    script_path = BACKEND_ROOT / "scripts" / "catalog_search_receipt.py"

    assert snapshot["schema_version"] == 1
    historical_hash = snapshot["collector"]["script_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", historical_hash)
    assert hardening["historical_snapshot_collector_sha256"] == historical_hash
    assert hardening["hardened_collector_sha256"] == hashlib.sha256(
        script_path.read_bytes()
    ).hexdigest()
    assert hardening["evidence_boundary"].startswith(
        "This receipt records a post-collection hardening change."
    )
    assert snapshot["collector"]["authentication"] == "anonymous_only"
    assert snapshot["collector"]["remote_files_downloaded"] is False
    assert snapshot["collector"]["remote_content_executed"] is False
    assert set(snapshot["collector"]["request_headers"]) == {"Accept", "User-Agent"}
    assert "C:\\" not in raw_text
    assert "kaggle.json" not in raw_text.casefold()
    assert "modal2.txt" not in raw_text.casefold()
    assert "chave.txt" not in raw_text.casefold()
    assert re.search(r"\bhf_[A-Za-z0-9]{20,}\b", raw_text) is None

    requests = [request for source in snapshot["sources"] for request in source["requests"]]
    candidates = [candidate for source in snapshot["sources"] for candidate in source["candidates"]]
    assert len(requests) == snapshot["summary"]["request_count"]
    assert (
        sum(request["outcome"] == "success" for request in requests)
        == snapshot["summary"]["successful_requests"]
    )
    assert len(candidates) == snapshot["summary"]["unique_candidates"]
    assert all(request["query"] in snapshot["methodology"]["queries"] for request in requests)
    assert all(
        request["request_url"].startswith(
            ("https://huggingface.co/api/", "https://www.kaggle.com/api/v1/")
        )
        for request in requests
    )
    for request in requests:
        if request["outcome"] == "success":
            assert re.fullmatch(r"[0-9a-f]{64}", request["response_sha256"])

    forbidden_remote_content = {"files", "siblings", "text", "source", "content"}
    assert all(forbidden_remote_content.isdisjoint(candidate) for candidate in candidates)
    assert all(
        len(source["candidates"]) == len({item["id"] for item in source["candidates"]})
        for source in snapshot["sources"]
    )

    kaggle_code = _source(snapshot, "kaggle_code")
    assert not kaggle_code["candidates"]
    assert {request["outcome"] for request in kaggle_code["requests"]} == {"http_401"}
