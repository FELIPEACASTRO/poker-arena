"""Fail the local quality gate when high-confidence credentials enter the package.

Only the finding kind, a one-way path fingerprint and line are emitted. Secret values and
filenames are never printed, including on failures. Dependencies, generated caches and
known binary assets are intentionally excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT_BYTES = 16 * 1024 * 1024
SKIP_DIRECTORIES = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    ".poker-arena-runtime",
    ".npm-cache-deps",
    ".uv-cache-deps",
    "npm-cache",
    "uv-cache",
    "vendor",
}
SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "_netrc",
    "chave.txt",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "kaggle.json",
    "modal.toml",
    "modal2.txt",
    "service-account.json",
}
SAFE_ENV_TEMPLATE_FILENAMES = {
    ".env.e2e",
    ".env.example",
    ".env.sample",
    ".env.template",
}
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".conf",
    ".css",
    ".csv",
    ".graphql",
    ".html",
    ".ipynb",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".key",
    ".md",
    ".pem",
    ".properties",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
BINARY_SUFFIXES = {
    ".7z",
    ".avi",
    ".bmp",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".npy",
    ".npz",
    ".onnx",
    ".parquet",
    ".pdf",
    ".png",
    ".pyc",
    ".pyd",
    ".so",
    ".tar",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}

DIRECT_PATTERNS = (
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("openai_token", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_token", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openrouter_token", re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}\b")),
    ("groq_token", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("replicate_token", re.compile(r"\br8_[A-Za-z0-9]{20,}\b")),
    ("kaggle_token", re.compile(r"\bKGAT_[A-Za-z0-9_-]{20,}\b")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("modal_token", re.compile(r"\b(?:ak|as)-[A-Za-z0-9]{20,}\b")),
    (
        "jwt_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    ("kaggle_key", re.compile(r'"key"\s*:\s*"[0-9a-fA-F]{32}"')),
)
CREDENTIAL_FIELD_PATTERN = (
    r"(?:HF|HUGGINGFACE|HUGGING_FACE|KAGGLE|MODAL|OPENAI|GITHUB|GH|ANTHROPIC|"
    r"AWS|AZURE|GOOGLE|GCP|CLOUDFLARE|OPENROUTER|REPLICATE|WANDB|COMET|GROQ|POKER)_"
    r"[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)|"
    r"(?:API[_-]?(?:KEY|TOKEN)|ACCESS[_-]?TOKEN|AUTH[_-]?TOKEN|SECRET[_-]?KEY|PASSWORD)|"
    r"(?:DATABASE_URL|REDIS_URL|DSN|CONNECTION_STRING)"
)
ASSIGNMENT_PATTERN = re.compile(
    r"(?im)(?:^|[{,;])\s*(?:export\s+|const\s+|let\s+|var\s+|env\s+|arg\s+)?"
    r"(?:\$env:|process\.env\.|\$)?"
    rf"[\"']?(?P<name>{CREDENTIAL_FIELD_PATTERN})[\"']?"
    r"\s*(?P<separator>[:=])\s*(?P<quote>[\"']?)(?P<secret>[^\s\"'#,;\}\]\)]{8,})"
)
XML_ASSIGNMENT_PATTERN = re.compile(
    rf"(?is)<(?P<name>{CREDENTIAL_FIELD_PATTERN})(?:\s[^>]*)?>\s*"
    r"(?P<secret>[^<\s]{8,})\s*</[^>]+>"
)
NPM_AUTH_PATTERN = re.compile(
    r"(?im)^\s*(?://[^\r\n]*:)?_(?:authToken|auth|password)\s*=\s*"
    r"[\"']?(?P<secret>[^\s\"'#,;]{8,})"
)
NETRC_PASSWORD_PATTERN = re.compile(
    r"(?im)^\s*(?:machine\s+\S+\s+)?(?:login\s+\S+\s+)?password\s+"
    r"(?P<secret>\S{8,})"
)
EXACT_PLACEHOLDERS = {"change-me", "changeme", "dummy", "example", "fake", "placeholder", "redacted"}
PLACEHOLDER_PREFIXES = (
    "change-me-",
    "changeme-",
    "must_not_be_echoed",
    "not-a-real-",
    "required_secret",
    "synthetic-",
    "your-",
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    kind: str


def _is_placeholder(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.casefold()
    if stripped.startswith(("<", "{", "[", "(")):
        return True
    if lowered.startswith(
        ("_required_secret(", "userdata.get", "os.getenv", "os.environ", "process.env", "getenv(")
    ):
        return True
    if "{{" in value or "${" in value:
        return True
    return lowered in EXACT_PLACEHOLDERS or lowered.startswith(PLACEHOLDER_PREFIXES)


def _is_sensitive_filename(filename: str) -> bool:
    lowered = filename.casefold()
    return lowered in SENSITIVE_FILENAMES or (
        lowered.startswith(".env.") and lowered not in SAFE_ENV_TEMPLATE_FILENAMES
    )


def _assignment_is_placeholder(match: re.Match[str], path: Path) -> bool:
    value = match.group("secret")
    if _is_placeholder(value):
        return True
    # In source code, ``{"TOKEN": token_variable}`` is a reference, not a literal
    # credential.  Keep unquoted dotenv/YAML assignments fail-closed because there an
    # identifier-looking value is itself the deployed secret.
    return (
        path.suffix.casefold() in {".js", ".jsx", ".py", ".ts", ".tsx"}
        and match.group("separator") == ":"
        and not match.group("quote")
        and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_.$]*", value) is not None
    )


def _looks_binary(probe: bytes) -> bool:
    """Identify binary content by bytes, never by a spoofable filename suffix."""

    if not probe:
        return False
    if probe.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    if probe.startswith(
        (b"\x89PNG\r\n\x1a\n", b"PK\x03\x04", b"%PDF-", b"GIF8", b"\xff\xd8\xff", b"MZ", b"\x7fELF", b"\x1f\x8b", b"7z\xbc\xaf\x27\x1c")
    ):
        return True
    if b"\x00" not in probe:
        return False
    even_nuls = probe[0::2].count(0)
    odd_nuls = probe[1::2].count(0)
    if odd_nuls > even_nuls * 2 or even_nuls > odd_nuls * 2:
        encoding = "utf-16-le" if odd_nuls > even_nuls else "utf-16-be"
        try:
            decoded = probe.decode(encoding)
        except UnicodeDecodeError:
            return True
        control_count = sum(
            ord(char) < 32 and char not in "\n\r\t" for char in decoded
        )
        return control_count > max(2, len(decoded) // 100)
    return True


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _decode_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    probe = raw[:4096]
    if probe and b"\x00" in probe:
        even_nuls = probe[0::2].count(0)
        odd_nuls = probe[1::2].count(0)
        if odd_nuls > even_nuls * 2:
            return raw.decode("utf-16-le")
        if even_nuls > odd_nuls * 2:
            return raw.decode("utf-16-be")
    return raw.decode("utf-8-sig")


def scan(root: Path) -> list[Finding]:
    root = root.resolve(strict=True)
    findings: set[Finding] = set()

    def record_walk_error(error: OSError) -> None:
        candidate = Path(error.filename) if error.filename else root
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            relative = "."
        findings.add(Finding(relative, 1, "unreadable_directory"))

    for current, directories, files in os.walk(
        root, followlinks=False, onerror=record_walk_error
    ):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in directories:
            if (
                name in SKIP_DIRECTORIES
                or name.startswith(".e2e-run-")
                or name.startswith(".qa-run-")
                or name.startswith(".pytest-")
            ):
                continue
            directory = current_path / name
            if _is_reparse_point(directory):
                findings.add(
                    Finding(directory.relative_to(root).as_posix(), 1, "source_reparse_point")
                )
                continue
            kept_directories.append(name)
        directories[:] = kept_directories
        for filename in files:
            path = current_path / filename
            relative = path.relative_to(root).as_posix()
            if _is_reparse_point(path):
                findings.add(Finding(relative, 1, "source_reparse_point"))
                continue
            if _is_sensitive_filename(filename):
                findings.add(Finding(relative, 1, "sensitive_filename"))
            try:
                with path.open("rb") as stream:
                    size = os.fstat(stream.fileno()).st_size
                    probe = stream.read(8192)
                    if _looks_binary(probe):
                        continue
                    if size > MAX_TEXT_BYTES:
                        findings.add(Finding(relative, 1, "oversized_text_unscanned"))
                        continue
                    raw = probe + stream.read()
                try:
                    text = _decode_text(raw)
                except UnicodeDecodeError:
                    text = raw.decode("cp1252")
            except OSError:
                findings.add(Finding(relative, 1, "unreadable_text"))
                continue
            except UnicodeDecodeError:
                findings.add(Finding(relative, 1, "unsupported_text_encoding"))
                continue
            for kind, pattern in DIRECT_PATTERNS:
                for match in pattern.finditer(text):
                    findings.add(Finding(relative, _line_number(text, match.start()), kind))
            for match in ASSIGNMENT_PATTERN.finditer(text):
                if not _assignment_is_placeholder(match, path):
                    findings.add(
                        Finding(
                            relative,
                            _line_number(text, match.start("name")),
                            "credential_assignment",
                        )
                    )
            for match in XML_ASSIGNMENT_PATTERN.finditer(text):
                if not _is_placeholder(match.group("secret")):
                    findings.add(
                        Finding(
                            relative,
                            _line_number(text, match.start("name")),
                            "credential_assignment",
                        )
                    )
            for pattern in (NPM_AUTH_PATTERN, NETRC_PASSWORD_PATTERN):
                for match in pattern.finditer(text):
                    if not _is_placeholder(match.group("secret")):
                        findings.add(
                            Finding(
                                relative,
                                _line_number(text, match.start()),
                                "credential_assignment",
                            )
                        )
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Project root to scan (defaults to this checkout).",
    )
    args = parser.parse_args(argv)
    findings = scan(args.root)
    if findings:
        print(f"SECRET_SCAN_FAILED findings={len(findings)}")
        for finding in findings:
            path_digest = hashlib.sha256(finding.path.encode("utf-8")).hexdigest()[:16]
            print(f"- {finding.kind}: path_sha256={path_digest} line={finding.line}")
        return 1
    print("SECRET_SCAN_OK findings=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
