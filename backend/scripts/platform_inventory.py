"""Build and optionally probe a reproducible inventory of research platforms.

The input is the Markdown catalogue supplied with the thesis project.  Probing is
deliberately shallow: one HEAD request per official root URL, with a GET fallback only
when the server rejects HEAD.  The tool does not bypass authentication, robots,
paywalls, rate limits, or anti-bot controls; those outcomes are evidence and are kept in
the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit

SECTION_RE = re.compile(r"^##\s+(?P<number>\d+)\.\s+(?P<title>.+?)\s*$")
ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*\[(?P<label>https?://[^]]+)\]"
    r"\((?P<url>https?://[^)]+)\)\s*\|\s*$"
)
USER_AGENT = "PokerArenaResearchAudit/1.0 (+local thesis evidence probe)"


def _validated_public_target(url: str) -> tuple[Any, tuple[str, ...]]:
    """Return a parsed URL and the exact public addresses approved for connection."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("platform URL must use public HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("platform URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("platform URL must not contain a query or fragment")
    hostname = parsed.hostname.rstrip(".").casefold()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        raise ValueError("platform URL is not public")

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = {ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos}
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("platform URL resolves outside the public Internet")
    return parsed, tuple(sorted(str(address) for address in addresses))


def _validate_public_http_url(url: str) -> None:
    """Reject credentials, URL-carried state and non-public resolution."""

    _validated_public_target(url)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to the validated address without a second hostname resolution."""

    def __init__(self, host: str, port: int, connect_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._connect_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Pin the TCP peer while retaining the original hostname for SNI/certificate checks."""

    def __init__(self, host: str, port: int, connect_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._connect_ip = connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._connect_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except BaseException:
            raw_socket.close()
            raise


@dataclass(frozen=True)
class Platform:
    inventory_id: str
    section: int
    section_title: str
    name: str
    url: str


@dataclass(frozen=True)
class Probe:
    checked_at: str
    state: str
    http_status: int | None
    method: str
    final_url: str | None
    redirected: bool
    error_type: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_platforms(markdown: str) -> list[Platform]:
    section: int | None = None
    section_title = ""
    platforms: list[Platform] = []
    seen_urls: set[str] = set()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section_match = SECTION_RE.match(line)
            if section_match and 1 <= int(section_match.group("number")) <= 12:
                section = int(section_match.group("number"))
                section_title = section_match.group("title")
            else:
                section = None
            continue
        if section is None:
            continue
        row_match = ROW_RE.match(line)
        if not row_match:
            continue
        url = row_match.group("url").strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        platforms.append(
            Platform(
                inventory_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                section=section,
                section_title=section_title,
                name=row_match.group("name").strip(),
                url=url,
            )
        )
    return platforms


def _request(url: str, method: str, timeout: float) -> tuple[int, str]:
    if method not in {"HEAD", "GET"}:
        raise ValueError("unsupported probe method")
    current_url = url
    current_method = method
    for redirect_count in range(6):
        parsed, addresses = _validated_public_target(current_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection_type = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_type(parsed.hostname or "", port, addresses[0], timeout)
        target = parsed.path or "/"
        try:
            connection.request(current_method, target, headers={"User-Agent": USER_AGENT})
            response = connection.getresponse()
            location = response.getheader("Location")
            if response.status in {301, 302, 303, 307, 308} and location:
                if redirect_count >= 5:
                    raise ValueError("platform URL exceeded safe redirect limit")
                current_url = urljoin(current_url, location)
                _validate_public_http_url(current_url)
                if response.status == 303:
                    current_method = "GET"
                response.read(1024)
                continue
            if response.status >= 400:
                raise HTTPError(current_url, response.status, response.reason, response.headers, None)
            if current_method == "GET":
                response.read(1024)
            return int(response.status), current_url
        finally:
            connection.close()
    raise AssertionError("unreachable redirect loop")


def probe_url(url: str, *, timeout: float, checked_at: str) -> Probe:
    method = "HEAD"
    try:
        try:
            status, final_url = _request(url, method, timeout)
        except HTTPError as error:
            if error.code not in {405, 501}:
                raise
            method = "GET"
            status, final_url = _request(url, method, timeout)
        return Probe(
            checked_at=checked_at,
            state="reachable",
            http_status=status,
            method=method,
            final_url=final_url,
            redirected=final_url.rstrip("/") != url.rstrip("/"),
            error_type=None,
        )
    except HTTPError as error:
        return Probe(
            checked_at=checked_at,
            state="http_error",
            http_status=error.code,
            method=method,
            final_url=error.geturl(),
            redirected=error.geturl().rstrip("/") != url.rstrip("/"),
            error_type="HTTPError",
        )
    except TimeoutError:
        return Probe(checked_at, "network_error", None, method, None, False, "Timeout")
    except ssl.SSLError:
        return Probe(checked_at, "network_error", None, method, None, False, "SSLError")
    except URLError as error:
        reason = error.reason
        error_type = type(reason).__name__ if reason is not None else "URLError"
        return Probe(checked_at, "network_error", None, method, None, False, error_type)
    except OSError as error:
        return Probe(checked_at, "network_error", None, method, None, False, type(error).__name__)
    except ValueError:
        return Probe(checked_at, "blocked", None, method, None, False, "UnsafeURL")


def build_receipt(
    source: Path,
    platforms: list[Platform],
    *,
    probes: dict[str, Probe] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    sections: dict[str, int] = {}
    for platform in platforms:
        key = str(platform.section)
        sections[key] = sections.get(key, 0) + 1
    records: list[dict[str, Any]] = []
    for platform in platforms:
        record: dict[str, Any] = asdict(platform)
        if probes is not None:
            record["probe"] = asdict(probes[platform.inventory_id])
        records.append(record)
    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "source": {"filename": source.name, "sha256": sha256_file(source)},
        "method": {
            "scope": "Markdown sections 1-12; exact official URLs; deduplicated by URL",
            "probe": (
                "HEAD once per URL; GET up to 1024 bytes only for HTTP 405/501; at most five "
                "public redirects; direct DNS-pinned TCP/TLS with no environment proxy; no "
                "authentication or control bypass"
            ),
        },
        "platform_count": len(platforms),
        "section_counts": sections,
        "platforms": records,
    }


def _probe_all(platforms: list[Platform], *, workers: int, timeout: float) -> dict[str, Probe]:
    checked_at = datetime.now(UTC).isoformat()
    results: dict[str, Probe] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe_url, platform.url, timeout=timeout, checked_at=checked_at): platform
            for platform in platforms
        }
        for future in as_completed(futures):
            platform = futures[future]
            results[platform.inventory_id] = future.result()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Markdown catalogue to inventory")
    parser.add_argument("--output", type=Path, required=True, help="JSON receipt path")
    parser.add_argument("--probe", action="store_true", help="shallow-probe every official URL")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args(argv)

    if not args.source.is_file():
        parser.error("source Markdown does not exist")
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    if not 1 <= args.timeout <= 60:
        parser.error("timeout must be between 1 and 60 seconds")

    platforms = parse_platforms(args.source.read_text(encoding="utf-8-sig"))
    if not platforms:
        parser.error("no platforms found in sections 1-12")
    probes = _probe_all(platforms, workers=args.workers, timeout=args.timeout) if args.probe else None
    receipt = build_receipt(args.source, platforms, probes=probes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"platform_count": len(platforms), "probed": probes is not None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
