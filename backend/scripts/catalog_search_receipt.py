"""Create an anonymous, metadata-only Hugging Face and Kaggle search receipt.

The collector deliberately does not import either platform SDK, inspect environment
variables, or read credential files.  Every request is a public GET with a fixed set
of non-sensitive headers.  It never downloads repository files, datasets, notebooks,
or model weights and it never executes remote content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA_VERSION = 1
USER_AGENT = "PokerArena-Catalog-Research/1.0 (+metadata-only; anonymous)"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HF_API_ROOT = "https://huggingface.co/api"
KAGGLE_API_ROOT = "https://www.kaggle.com/api/v1"
OFFICIAL_HF_DOCS = "https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api"
OFFICIAL_KAGGLE_CLI = "https://github.com/Kaggle/kaggle-cli"
DEFAULT_QUERIES = (
    "poker",
    "texas holdem",
    "poker hand",
    "poker agent",
    "playing card recognition",
)
SAFE_RATE_HEADERS = (
    "Retry-After",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
)


@dataclass(frozen=True)
class FetchResult:
    """A bounded public response and its sanitized transport receipt."""

    payload: Any | None
    receipt: dict[str, Any]


Fetcher = Callable[[str, float], FetchResult]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat every redirect as a response error; never cross the original allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


class _NoProxyHandler(ProxyHandler):
    """Explicit direct-connection handler retained in the opener for auditability."""

    def __init__(self) -> None:
        super().__init__({})

    def http_open(self, req):  # noqa: ANN001, ANN201
        return None

    https_open = http_open


def _build_public_opener():
    """Build an opener that ignores environment/system proxies and refuses redirects."""

    return build_opener(_NoProxyHandler(), _NoRedirectHandler())


_PUBLIC_OPENER = _build_public_opener()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _validate_utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("generated_at must include the UTC offset")
    return value


def build_public_request(url: str) -> Request:
    """Build the only request shape permitted by this collector."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("catalog endpoint is not allowlisted") from exc
    allowed = (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and not parsed.fragment
        and (
            (parsed.hostname == "huggingface.co" and parsed.path.startswith("/api/"))
            or (parsed.hostname == "www.kaggle.com" and parsed.path.startswith("/api/v1/"))
        )
    )
    if not allowed:
        raise ValueError("catalog endpoint is not allowlisted")
    return Request(  # noqa: S310 - HTTPS scheme and exact hosts/paths are validated above
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )


def _safe_rate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {name.lower(): value for name in SAFE_RATE_HEADERS if (value := headers.get(name))}


def fetch_public_json(url: str, timeout: float) -> FetchResult:
    """Fetch bounded JSON without credentials, cookies, response bodies on errors, or retries."""

    collected_at = utc_now()
    request = build_public_request(url)
    try:
        with _PUBLIC_OPENER.open(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return FetchResult(
                    None,
                    {
                        "collected_at_utc": collected_at,
                        "http_status": response.status,
                        "outcome": "response_too_large",
                        "response_bytes_observed": len(raw),
                        "safe_rate_headers": _safe_rate_headers(response.headers),
                    },
                )
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return FetchResult(
                    None,
                    {
                        "collected_at_utc": collected_at,
                        "http_status": response.status,
                        "outcome": "invalid_json",
                        "response_bytes": len(raw),
                        "response_sha256": hashlib.sha256(raw).hexdigest(),
                        "safe_rate_headers": _safe_rate_headers(response.headers),
                    },
                )
            return FetchResult(
                payload,
                {
                    "collected_at_utc": collected_at,
                    "http_status": response.status,
                    "outcome": "success",
                    "response_bytes": len(raw),
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "safe_rate_headers": _safe_rate_headers(response.headers),
                },
            )
    except HTTPError as exc:
        # Do not read or retain the error body: it is unnecessary and may contain server context.
        return FetchResult(
            None,
            {
                "collected_at_utc": collected_at,
                "http_status": exc.code,
                "outcome": f"http_{exc.code}",
                "safe_rate_headers": _safe_rate_headers(exc.headers),
            },
        )
    except (TimeoutError, URLError):
        return FetchResult(
            None,
            {
                "collected_at_utc": collected_at,
                "http_status": None,
                "outcome": "network_or_timeout_error",
                "safe_rate_headers": {},
            },
        )


def _license_from_tags(tags: Sequence[Any]) -> str | None:
    licenses = sorted(
        tag.removeprefix("license:")
        for tag in tags
        if isinstance(tag, str) and tag.startswith("license:")
    )
    return ",".join(licenses) if licenses else None


def _safe_string(value: Any, *, maximum: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    return compact[:maximum] if compact else None


def _safe_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _triage(text: str) -> dict[str, str]:
    normalized = text.casefold().replace("_", " ").replace("-", " ")
    strong_poker = re.search(
        r"\b(texas\s+hold(?:\s|'|-)?em|hold(?:\s|'|-)?em|poker\s+(?:hand|game|agent|ai|bot|card)|leduc)\b",
        normalized,
    )
    card_vision = re.search(r"\b(?:playing|poker)\s+cards?\b", normalized) and re.search(
        r"\b(?:vision|image|detect|recogn|ocr|classif)\w*\b", normalized
    )
    generic_poker = re.search(r"\bpoker\b", normalized)
    poker_face_only = re.search(r"\bpoker\s+face\b", normalized) and not strong_poker

    if strong_poker:
        return {
            "decision": "retain_for_manual_review",
            "category": "direct_poker_domain_keyword",
            "reason": "Name/title/tags contain a specific poker-game term.",
        }
    if card_vision:
        return {
            "decision": "retain_for_manual_review",
            "category": "playing_card_vision_keyword",
            "reason": "Name/title/tags combine playing-card and vision/recognition terms.",
        }
    if generic_poker and not poker_face_only:
        return {
            "decision": "retain_for_manual_review",
            "category": "broad_poker_keyword",
            "reason": "Name/title/tags contain poker, but relevance remains broad.",
        }
    return {
        "decision": "exclude_at_keyword_screen",
        "category": "low_or_ambiguous_signal",
        "reason": "Repository/item metadata lacks a specific game or card-vision signal.",
    }


def _hf_item(raw: Mapping[str, Any], artifact_type: str) -> dict[str, Any] | None:
    item_id = _safe_string(raw.get("id") or raw.get("modelId"), maximum=200)
    if not item_id:
        return None
    tags = sorted({_safe_string(tag, maximum=120) for tag in raw.get("tags", [])} - {None})
    repo_name = item_id.split("/", 1)[-1]
    searchable = " ".join(
        part
        for part in (
            repo_name,
            _safe_string(raw.get("pipeline_tag")),
            _safe_string(raw.get("library_name")),
            " ".join(tags),
        )
        if part
    )
    return {
        "id": item_id,
        "artifact_type": artifact_type,
        "url": f"https://huggingface.co/{'datasets/' if artifact_type == 'dataset' else ''}{item_id}",
        "revision_sha": _safe_string(raw.get("sha"), maximum=80),
        "last_modified": _safe_string(raw.get("lastModified"), maximum=50),
        "declared_license": _license_from_tags(tags),
        "gated": raw.get("gated") if isinstance(raw.get("gated"), (bool, str)) else None,
        "downloads": _safe_int(raw.get("downloads")),
        "likes": _safe_int(raw.get("likes")),
        "pipeline_tag": _safe_string(raw.get("pipeline_tag"), maximum=100),
        "library_name": _safe_string(raw.get("library_name"), maximum=100),
        "tags": tags,
        "triage": _triage(searchable),
    }


def _kaggle_dataset(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    item_id = _safe_string(raw.get("ref"), maximum=200)
    if not item_id:
        return None
    title = _safe_string(raw.get("title"))
    subtitle = _safe_string(raw.get("subtitle"))
    searchable = " ".join(part for part in (item_id.split("/", 1)[-1], title, subtitle) if part)
    return {
        "id": item_id,
        "artifact_type": "dataset",
        "url": _safe_string(raw.get("url"), maximum=500)
        or f"https://www.kaggle.com/datasets/{item_id}",
        "revision_version": _safe_int(raw.get("currentVersionNumber")),
        "last_modified": _safe_string(raw.get("lastUpdated"), maximum=50),
        "declared_license": _safe_string(raw.get("licenseName"), maximum=200),
        "title": title,
        "subtitle": subtitle,
        "total_bytes": _safe_int(raw.get("totalBytes")),
        "downloads": _safe_int(raw.get("downloadCount")),
        "votes": _safe_int(raw.get("voteCount")),
        "usability_rating": _safe_number(raw.get("usabilityRating")),
        "triage": _triage(searchable),
    }


def _kaggle_code(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    item_id = _safe_string(raw.get("ref"), maximum=200)
    if not item_id:
        author = _safe_string(raw.get("author"), maximum=100)
        slug = _safe_string(raw.get("slug"), maximum=100)
        item_id = f"{author}/{slug}" if author and slug else None
    if not item_id:
        return None
    title = _safe_string(raw.get("title"))
    searchable = " ".join(part for part in (item_id.split("/", 1)[-1], title) if part)
    return {
        "id": item_id,
        "artifact_type": "notebook_or_code",
        "url": _safe_string(raw.get("url"), maximum=500)
        or f"https://www.kaggle.com/code/{item_id}",
        "revision": _safe_string(raw.get("versionNumber"), maximum=80)
        or _safe_int(raw.get("versionNumber")),
        "last_modified": _safe_string(raw.get("lastRunTime") or raw.get("lastUpdated"), maximum=50),
        "language": _safe_string(raw.get("language"), maximum=80),
        "kernel_type": _safe_string(raw.get("kernelType"), maximum=80),
        "votes": _safe_int(raw.get("totalVotes")),
        "triage": _triage(searchable),
    }


def _merge_candidate(
    candidates: dict[str, dict[str, Any]], item: dict[str, Any], query: str, rank: int
) -> None:
    item_id = item["id"]
    if item_id not in candidates:
        item["matched_queries"] = [query]
        item["rank_by_query"] = {query: rank}
        candidates[item_id] = item
        return
    existing = candidates[item_id]
    if query not in existing["matched_queries"]:
        existing["matched_queries"].append(query)
    existing["rank_by_query"][query] = min(rank, existing["rank_by_query"].get(query, rank))


def _request_record(
    *, source_id: str, artifact_type: str, query: str, url: str, result: FetchResult
) -> dict[str, Any]:
    record = {
        "source_id": source_id,
        "artifact_type": artifact_type,
        "query": query,
        "request_url": url,
        **result.receipt,
    }
    record["result_count"] = len(result.payload) if isinstance(result.payload, list) else 0
    return record


def _hf_url(kind: str, query: str, limit: int) -> str:
    expand = [
        "author",
        "sha",
        "lastModified",
        "gated",
        "tags",
        "downloads",
        "likes",
    ]
    if kind == "models":
        expand.extend(("pipeline_tag", "library_name"))
    params: list[tuple[str, str | int]] = [("search", query), ("limit", limit)]
    params.extend(("expand", field) for field in expand)
    return f"{HF_API_ROOT}/{kind}?{urlencode(params)}"


def _kaggle_dataset_url(query: str, page: int) -> str:
    return f"{KAGGLE_API_ROOT}/datasets/list?{urlencode({'search': query, 'page': page})}"


def _kaggle_kernel_url(query: str) -> str:
    params = {"search": query, "page": 1, "pageSize": 100}
    return f"{KAGGLE_API_ROOT}/kernels/list?{urlencode(params)}"


def collect_snapshot(
    *,
    queries: Sequence[str] = DEFAULT_QUERIES,
    hf_limit: int = 100,
    kaggle_pages: int = 3,
    timeout: float = 20.0,
    generated_at: str | None = None,
    fetcher: Fetcher = fetch_public_json,
) -> dict[str, Any]:
    """Collect a bounded anonymous metadata snapshot from the two official services."""

    clean_queries = tuple(dict.fromkeys(query.strip() for query in queries if query.strip()))
    if not clean_queries:
        raise ValueError("at least one non-empty query is required")
    if not 1 <= hf_limit <= 500:
        raise ValueError("hf_limit must be between 1 and 500")
    if not 1 <= kaggle_pages <= 10:
        raise ValueError("kaggle_pages must be between 1 and 10")
    if not 0.5 <= timeout <= 60:
        raise ValueError("timeout must be between 0.5 and 60 seconds")

    request_records: list[dict[str, Any]] = []
    source_candidates: dict[str, dict[str, dict[str, Any]]] = {
        "huggingface_datasets": {},
        "huggingface_models": {},
        "kaggle_datasets": {},
        "kaggle_code": {},
    }

    for kind, artifact_type, source_id in (
        ("datasets", "dataset", "huggingface_datasets"),
        ("models", "model", "huggingface_models"),
    ):
        for query in clean_queries:
            url = _hf_url(kind, query, hf_limit)
            result = fetcher(url, timeout)
            request_records.append(
                _request_record(
                    source_id=source_id,
                    artifact_type=artifact_type,
                    query=query,
                    url=url,
                    result=result,
                )
            )
            if isinstance(result.payload, list):
                for rank, raw in enumerate(result.payload, start=1):
                    if isinstance(raw, Mapping) and (item := _hf_item(raw, artifact_type)):
                        _merge_candidate(source_candidates[source_id], item, query, rank)

    for query in clean_queries:
        query_offset = 0
        for page in range(1, kaggle_pages + 1):
            url = _kaggle_dataset_url(query, page)
            result = fetcher(url, timeout)
            request_records.append(
                _request_record(
                    source_id="kaggle_datasets",
                    artifact_type="dataset",
                    query=query,
                    url=url,
                    result=result,
                )
            )
            if not isinstance(result.payload, list):
                break
            for page_rank, raw in enumerate(result.payload, start=1):
                if isinstance(raw, Mapping) and (item := _kaggle_dataset(raw)):
                    absolute_rank = query_offset + page_rank
                    _merge_candidate(
                        source_candidates["kaggle_datasets"], item, query, absolute_rank
                    )
            query_offset += len(result.payload)
            if len(result.payload) < 20:
                break

    # Kaggle's current public dataset listing is anonymous, while the official code-listing
    # endpoint may require authentication.  Record that boundary; never fall back to credentials.
    for query in clean_queries:
        url = _kaggle_kernel_url(query)
        result = fetcher(url, timeout)
        request_records.append(
            _request_record(
                source_id="kaggle_code",
                artifact_type="notebook_or_code",
                query=query,
                url=url,
                result=result,
            )
        )
        if isinstance(result.payload, list):
            for rank, raw in enumerate(result.payload, start=1):
                if isinstance(raw, Mapping) and (item := _kaggle_code(raw)):
                    _merge_candidate(source_candidates["kaggle_code"], item, query, rank)

    sources: list[dict[str, Any]] = []
    source_definitions = (
        (
            "huggingface_datasets",
            "Hugging Face Hub",
            "dataset",
            f"{HF_API_ROOT}/datasets",
            OFFICIAL_HF_DOCS,
        ),
        (
            "huggingface_models",
            "Hugging Face Hub",
            "model",
            f"{HF_API_ROOT}/models",
            OFFICIAL_HF_DOCS,
        ),
        (
            "kaggle_datasets",
            "Kaggle",
            "dataset",
            f"{KAGGLE_API_ROOT}/datasets/list",
            OFFICIAL_KAGGLE_CLI,
        ),
        (
            "kaggle_code",
            "Kaggle",
            "notebook_or_code",
            f"{KAGGLE_API_ROOT}/kernels/list",
            OFFICIAL_KAGGLE_CLI,
        ),
    )
    for source_id, platform, artifact_type, endpoint, documentation in source_definitions:
        candidates = sorted(source_candidates[source_id].values(), key=lambda item: item["id"])
        for candidate in candidates:
            candidate["matched_queries"].sort()
            candidate["rank_by_query"] = dict(sorted(candidate["rank_by_query"].items()))
        sources.append(
            {
                "source_id": source_id,
                "platform": platform,
                "artifact_type": artifact_type,
                "official_endpoint": endpoint,
                "official_documentation": documentation,
                "requests": [
                    request for request in request_records if request["source_id"] == source_id
                ],
                "candidates": candidates,
            }
        )

    succeeded = sum(request["outcome"] == "success" for request in request_records)
    failed = len(request_records) - succeeded
    all_candidates = [candidate for source in sources for candidate in source["candidates"]]
    retained = sum(
        candidate["triage"]["decision"] == "retain_for_manual_review"
        for candidate in all_candidates
    )
    by_source = {
        source["source_id"]: {
            "requests": len(source["requests"]),
            "successful_requests": sum(
                request["outcome"] == "success" for request in source["requests"]
            ),
            "unique_candidates": len(source["candidates"]),
            "retained_for_manual_review": sum(
                candidate["triage"]["decision"] == "retain_for_manual_review"
                for candidate in source["candidates"]
            ),
        }
        for source in sources
    }
    generated = _validate_utc_timestamp(generated_at) if generated_at else utc_now()
    script_path = Path(__file__)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "scope": (
            "Bounded, current keyword snapshot of public catalog metadata for poker-related "
            "datasets, models and notebooks/code on Hugging Face and Kaggle."
        ),
        "collector": {
            "script": "backend/scripts/catalog_search_receipt.py",
            "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "authentication": "anonymous_only",
            "request_method": "GET",
            "request_headers": {"Accept": "application/json", "User-Agent": USER_AGENT},
            "remote_files_downloaded": False,
            "remote_content_executed": False,
            "credential_files_or_platform_tokens_read": False,
        },
        "methodology": {
            "queries": list(clean_queries),
            "hf_limit_per_query_and_type": hf_limit,
            "kaggle_dataset_max_pages_per_query": kaggle_pages,
            "timeout_seconds": timeout,
            "deduplication_key": "source_id + public artifact id",
            "triage": {
                "evidence_fields": (
                    "Public catalog ID/title/tags, declared license, revision/version, "
                    "timestamps and popularity metadata when returned."
                ),
                "inference_rule": (
                    "Deterministic keyword screen over repository/item name, title, subtitle, "
                    "pipeline and tags; owner/user names are excluded from the screen."
                ),
                "meaning": (
                    "retain_for_manual_review is only a discovery lead. It is not evidence of "
                    "quality, safety, legality, reproducibility or Poker Arena improvement."
                ),
            },
        },
        "summary": {
            "request_count": len(request_records),
            "successful_requests": succeeded,
            "failed_or_blocked_requests": failed,
            "unique_candidates": len(all_candidates),
            "retained_for_manual_review": retained,
            "excluded_at_keyword_screen": len(all_candidates) - retained,
            "by_source": by_source,
        },
        "sources": sources,
        "evidence_vs_inference": {
            "evidence": (
                "Each request receipt and returned catalog field is a timestamped platform "
                "metadata observation; response hashes bind the successful HTTP payloads."
            ),
            "inference": (
                "Keyword categories and retention decisions are local triage inferences and "
                "must be validated against cards, provenance, licenses and benchmarks before use."
            ),
        },
        "limitations": [
            "This is a bounded query snapshot, not an exhaustive search of either platform or the internet.",
            "Catalog ordering and contents can change after the recorded UTC timestamp.",
            "Hugging Face search primarily matches repository metadata/IDs; it is not full-content search.",
            "Kaggle pagination and ranking can truncate or reorder candidates; the configured page cap is explicit.",
            "The anonymous Kaggle code endpoint may return 401; this receipt records the gap and does not use credentials.",
            "Declared license labels and revisions are metadata claims, not an independent legal or provenance audit.",
            "No model/dataset/notebook files were inspected, downloaded or executed, so utility and safety remain untested.",
            "Rate-limit headers are recorded only when the service returns them; there are no automatic retries.",
        ],
    }


def render_markdown(snapshot: Mapping[str, Any]) -> str:
    summary = snapshot["summary"]
    lines = [
        "# Public Hugging Face and Kaggle poker catalog receipt",
        "",
        f"Generated (UTC): `{snapshot['generated_at_utc']}`",
        "",
        "This is a bounded anonymous metadata snapshot, not an exhaustive internet search. "
        "No credentials, remote files, model weights, datasets or notebook contents were used.",
        "",
        "## Collection result",
        "",
        f"- Requests: **{summary['request_count']}** "
        f"({summary['successful_requests']} succeeded; "
        f"{summary['failed_or_blocked_requests']} failed or blocked)",
        f"- Unique metadata candidates: **{summary['unique_candidates']}**",
        f"- Retained only for manual review: **{summary['retained_for_manual_review']}**",
        f"- Excluded by deterministic keyword screen: **{summary['excluded_at_keyword_screen']}**",
        "",
        "| Source | Requests OK/total | Unique | Manual-review leads |",
        "|---|---:|---:|---:|",
    ]
    for source_id, values in summary["by_source"].items():
        lines.append(
            f"| `{source_id}` | {values['successful_requests']}/{values['requests']} | "
            f"{values['unique_candidates']} | {values['retained_for_manual_review']} |"
        )

    lines.extend(
        [
            "",
            "## Manual-review leads",
            "",
            "The rows below are catalog observations plus a keyword-screen inference. They are "
            "not recommendations or benchmark results.",
            "",
            "| Source | Type | ID | Declared license | Revision/version | Triage |",
            "|---|---|---|---|---|---|",
        ]
    )
    for source in snapshot["sources"]:
        for candidate in source["candidates"]:
            if candidate["triage"]["decision"] != "retain_for_manual_review":
                continue
            artifact_id = str(candidate["id"]).replace("|", "\\|")
            license_name = str(candidate.get("declared_license") or "not returned").replace(
                "|", "\\|"
            )
            revision = (
                candidate.get("revision_sha") or candidate.get("revision_version") or "not returned"
            )
            lines.append(
                f"| `{source['source_id']}` | {candidate['artifact_type']} | "
                f"[{artifact_id}]({candidate['url']}) | {license_name} | `{revision}` | "
                f"{candidate['triage']['category']} |"
            )

    lines.extend(
        [
            "",
            "## Evidence boundary and limitations",
            "",
            f"Evidence: {snapshot['evidence_vs_inference']['evidence']}",
            "",
            f"Inference: {snapshot['evidence_vs_inference']['inference']}",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in snapshot["limitations"])
    lines.extend(
        [
            "",
            "The JSON companion contains every request URL, UTC collection time, HTTP status, "
            "safe rate-limit headers, response size/hash, deduplicated candidates and exclusions.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="JSON receipt path")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown summary path")
    parser.add_argument(
        "--query", action="append", dest="queries", help="Repeat to override queries"
    )
    parser.add_argument("--hf-limit", type=int, default=100)
    parser.add_argument("--kaggle-pages", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--generated-at", help="Fixed UTC timestamp for controlled test snapshots")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    snapshot = collect_snapshot(
        queries=args.queries or DEFAULT_QUERIES,
        hf_limit=args.hf_limit,
        kaggle_pages=args.kaggle_pages,
        timeout=args.timeout,
        generated_at=args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(snapshot), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
