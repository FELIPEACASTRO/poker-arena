"""Fail-closed validation for versioned machine-learning dataset manifests.

The validator is deliberately read-only and uses only the standard library.  It
does not download data, repair manifests, or reveal values from a manifest in
its machine-readable report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat as stat_module
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final

SCHEMA_VERSION: Final = 1
PROFILE_REVISION: Final = "poker-arena-dataset-manifest-v1-2026-07-18"
MAX_MANIFEST_BYTES: Final = 10 * 1024 * 1024
MAX_SAMPLES: Final = 1_000_000
MAX_SAMPLE_FILE_BYTES: Final = 1024 * 1024 * 1024
MAX_TOTAL_SAMPLE_BYTES: Final = 100 * 1024 * 1024 * 1024
MAX_TOTAL_SAMPLE_FILES: Final = 100_000
MAX_REPORTED_ERRORS: Final = 256
MAX_EVENT_TIME_FUTURE_SKEW: Final = timedelta(minutes=5)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HASHED_PLAYER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_RFC3339_UTC_PATTERN: Final = (
    r"^(?!0000)[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
_RFC3339_UTC_RE = re.compile(_RFC3339_UTC_PATTERN)
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_ISO_3166_ALPHA2: Final = frozenset(
    """AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ
    BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU
    CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB
    GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL
    IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI
    LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV
    MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN
    PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR
    SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US
    UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW""".split()  # noqa: SIM905
)
_KEY_VERSION_RE = re.compile(r"^kv-[A-Za-z0-9][A-Za-z0-9._-]{2,62}$")
_SEPARATION_CONTEXT_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,127}$")
_OPAQUE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,126}[A-Za-z0-9]$")
_SOURCE_REFERENCE_RE = re.compile(
    r"^(?=.{3,256}$)(?!.*(?:\.\.|//))"
    r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?)*$"
)
_SAFE_GROUP_FIELDS: Final = frozenset(
    {
        "source",
        "session",
        "client",
        "theme",
        "deck",
        "hashed_player_id",
        "player_pseudonym",
        "split_group",
    }
)
_UNKNOWN_LICENSES: Final = frozenset(
    {"", "unknown", "unspecified", "unlicensed", "none", "null", "n/a", "na", "tbd"}
)
_UNKNOWN_POLICY_VALUES: Final = _UNKNOWN_LICENSES | frozenset({"other", "pending"})
_CONSENT_STATUSES: Final = frozenset({"obtained", "not-required"})
_LEGAL_BASES: Final = frozenset(
    {"consent", "contract", "legitimate-interest", "public-task", "research-exemption"}
)
_REDACTION_VERIFICATION: Final = frozenset({"automated", "human", "automated-and-human"})
_PERMITTED_USES: Final = frozenset(
    {"research", "model-training", "model-evaluation", "internal-demo", "redistribution"}
)
_PLATFORM_TERMS_STATUSES: Final = frozenset({"reviewed-compatible", "not-applicable"})
_PLAYER_IDENTITY_SCHEMES: Final = frozenset({"hmac-sha256"})
_PLAYER_IDENTITY_PURPOSES: Final = frozenset({"split-leakage-prevention"})
_TOP_LEVEL_FIELDS: Final = frozenset(
    {"schema_version", "profile_revision", "dataset", "policy", "samples"}
)
_DATASET_FIELDS: Final = frozenset({"name", "version"})
_POLICY_FIELDS: Final = frozenset(
    {
        "allowed_splits",
        "allowed_licenses",
        "group_disjoint_keys",
        "reject_duplicates_within_split",
        "consent",
        "legal_basis",
        "redaction",
        "permitted_use",
        "real_money",
        "platform_terms",
        "jurisdiction",
        "retention",
        "deletion",
        "player_identity",
    }
)
_POLICY_OPTIONAL_FIELDS: Final = frozenset({"temporal_order"})
_CONSENT_FIELDS: Final = frozenset({"status", "evidence_reference"})
_LEGAL_BASIS_FIELDS: Final = frozenset({"basis", "evidence_reference"})
_REDACTION_FIELDS: Final = frozenset(
    {
        "direct_identifiers_removed",
        "screen_names_removed",
        "free_text_reviewed",
        "verification",
    }
)
_PLATFORM_TERMS_FIELDS: Final = frozenset({"status", "evidence_reference"})
_RETENTION_FIELDS: Final = frozenset({"expires_at", "review_interval_days"})
_PLAYER_IDENTITY_FIELDS: Final = frozenset(
    {"scheme", "key_version", "separation_context", "purpose"}
)
_DELETION_FIELDS: Final = frozenset(
    {"on_request", "on_retention_expiry", "procedure_id", "verification_required"}
)
_TEMPORAL_ORDER_FIELDS: Final = frozenset({"split_order", "allow_equal_boundary"})
_SAMPLE_FIELDS: Final = frozenset(
    {
        "id",
        "path",
        "sha256",
        "source",
        "source_version",
        "session",
        "client",
        "theme",
        "deck",
        "hashed_player_id",
        "event_time",
        "split_group",
        "split",
        "license",
    }
)
_SAMPLE_OPTIONAL_FIELDS: Final = frozenset({"player_pseudonym"})


class _DuplicateJsonKey(ValueError):
    """Raised when JSON parsing would otherwise silently discard a value."""


class _SampleFileTooLarge(RuntimeError):
    """Raised before hashing a sample that exceeds the per-file resource cap."""


class _SampleFileChanged(RuntimeError):
    """Raised when a sample's identity or metadata changes while it is hashed."""


class _ManifestTooLarge(RuntimeError):
    """Raised before parsing a manifest beyond the bounded input size."""


class _ManifestChanged(RuntimeError):
    """Raised when the manifest path and opened descriptor do not identify one snapshot."""


@dataclass(frozen=True, slots=True)
class ManifestReceipt:
    """Sanitized identity of the exact manifest bytes observed by the validator."""

    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "identity": f"{self.device:x}:{self.inode:x}",
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
        }


@dataclass(frozen=True, slots=True)
class _ManifestSnapshot:
    path: Path
    resolved_path: Path
    payload: bytes
    fingerprint: tuple[int, int, int, int, int]
    receipt: ManifestReceipt


@dataclass(frozen=True, slots=True)
class _SampleFile:
    path: Path
    resolved_path: Path
    fingerprint: tuple[int, int, int, int, int]
    size_bytes: int

    @property
    def file_id(self) -> tuple[int, int]:
        return (self.fingerprint[0], self.fingerprint[1])


@dataclass(frozen=True, slots=True)
class _HashCandidate:
    sample_index: int
    file: _SampleFile
    expected_digest: str


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A sanitized validation failure safe to return from the CLI."""

    code: str
    message: str
    sample_index: int | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {"code": self.code, "message": self.message}
        if self.sample_index is not None:
            result["sample_index"] = self.sample_index
        if self.field is not None:
            result["field"] = self.field
        return result


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete, immutable result of a dataset-manifest check."""

    valid: bool
    schema_version: int | None
    sample_count: int
    verified_files: int
    errors: tuple[ValidationIssue, ...]
    profile_revision: str | None = None
    manifest_receipt: ManifestReceipt | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "schema_version": self.schema_version,
            "profile_revision": self.profile_revision,
            "sample_count": self.sample_count,
            "verified_files": self.verified_files,
            "manifest_receipt": (
                self.manifest_receipt.as_dict() if self.manifest_receipt is not None else None
            ),
            "error_count": len(self.errors),
            "errors": [issue.as_dict() for issue in self.errors],
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _parse_json_int(value: str) -> int:
    """Reject pathological integer tokens before constructing a Python bigint."""

    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 19:
        raise ValueError("JSON integer exceeds the manifest numeric profile")
    return int(value)


def _parse_json_float(value: str) -> float:
    if len(value) > 64:
        raise ValueError("JSON number exceeds the manifest numeric profile")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number must be finite")
    return parsed


def _reject_json_constant(_value: str) -> float:
    raise ValueError("non-finite JSON constants are forbidden")


def _issue(
    errors: list[ValidationIssue],
    code: str,
    message: str,
    *,
    sample_index: int | None = None,
    field: str | None = None,
) -> None:
    if len(errors) >= MAX_REPORTED_ERRORS:
        return
    if len(errors) == MAX_REPORTED_ERRORS - 1:
        errors.append(
            ValidationIssue(
                "error_limit_reached",
                "Additional validation errors were suppressed by the safe report limit.",
            )
        )
        return
    errors.append(ValidationIssue(code, message, sample_index, field))


def _is_nonempty_string(value: object, *, max_length: int = 256) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and value == value.strip()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _check_exact_fields(
    value: object,
    required: frozenset[str],
    errors: list[ValidationIssue],
    *,
    field: str,
    sample_index: int | None = None,
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _issue(
            errors,
            "invalid_type",
            "Expected a JSON object.",
            sample_index=sample_index,
            field=field,
        )
        return None
    for missing in sorted(required - value.keys()):
        if len(errors) >= MAX_REPORTED_ERRORS:
            break
        _issue(
            errors,
            "missing_field",
            "A required field is missing.",
            sample_index=sample_index,
            field=f"{field}.{missing}",
        )
    for _extra in sorted(value.keys() - required - optional):
        if len(errors) >= MAX_REPORTED_ERRORS:
            break
        _issue(
            errors,
            "unexpected_field",
            "An unrecognized field is not allowed by this schema version.",
            sample_index=sample_index,
            # Do not echo attacker-controlled key names in the CLI report.
            field=field,
        )
    return value


def _safe_policy_string(
    value: object,
    errors: list[ValidationIssue],
    *,
    field: str,
    allowed: frozenset[str] | None = None,
) -> str | None:
    if not _is_nonempty_string(value):
        _issue(errors, "invalid_policy", "Policy value must be a safe string.", field=field)
        return None
    if not isinstance(value, str):
        _issue(errors, "invalid_policy", "Policy value must be a safe string.", field=field)
        return None
    if value.casefold() in _UNKNOWN_POLICY_VALUES or (allowed is not None and value not in allowed):
        _issue(errors, "invalid_policy", "Policy value is not explicitly supported.", field=field)
        return None
    return value


def _safe_opaque_reference(
    value: object,
    errors: list[ValidationIssue],
    *,
    field: str,
) -> str | None:
    """Accept an identifier, never a URL, free text, path, or credential carrier."""

    if not isinstance(value, str) or not _OPAQUE_REFERENCE_RE.fullmatch(value):
        _issue(
            errors,
            "invalid_policy",
            "Evidence and procedure references must be canonical opaque identifiers.",
            field=field,
        )
        return None
    if value.casefold() in _UNKNOWN_POLICY_VALUES:
        _issue(
            errors,
            "invalid_policy",
            "Evidence and procedure references cannot use unknown markers.",
            field=field,
        )
        return None
    return value


def _is_safe_source_reference(value: object) -> bool:
    """Restrict source metadata to a non-secret registry-style identifier."""

    return bool(
        isinstance(value, str)
        and _SOURCE_REFERENCE_RE.fullmatch(value)
        and value.casefold() not in _UNKNOWN_POLICY_VALUES
    )


def _is_canonical_identifier(value: object) -> bool:
    return bool(isinstance(value, str) and _CANONICAL_ID_RE.fullmatch(value))


def _is_canonical_posix_path(value: object) -> bool:
    """Validate one OS-independent lexical path before passing it to pathlib."""

    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        return False
    if value != value.lower() or "\\" in value or ":" in value:
        return False
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() != value:
        return False
    segments = value.split("/")
    return not any(
        not segment
        or segment in {".", ".."}
        or not _SAFE_PATH_SEGMENT_RE.fullmatch(segment)
        or segment.split(".", maxsplit=1)[0] in _WINDOWS_RESERVED_NAMES
        for segment in segments
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not _RFC3339_UTC_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return parsed


def _string_list(
    value: object,
    errors: list[ValidationIssue],
    *,
    field: str,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        _issue(errors, "invalid_policy", "Policy list must be non-empty.", field=field)
        return ()
    result: list[str] = []
    for item in value:
        if not _is_nonempty_string(item):
            _issue(errors, "invalid_policy", "Policy entries must be safe strings.", field=field)
            continue
        if not isinstance(item, str):
            _issue(errors, "invalid_policy", "Policy entries must be safe strings.", field=field)
            continue
        if item in result:
            _issue(errors, "invalid_policy", "Policy entries must be unique.", field=field)
            continue
        result.append(item)
    return tuple(result)


def _parse_group_policy(
    value: object, errors: list[ValidationIssue]
) -> tuple[tuple[str, ...], ...]:
    field = "policy.group_disjoint_keys"
    if not isinstance(value, list) or not value:
        _issue(
            errors,
            "invalid_policy",
            "At least one disjoint group key is required.",
            field=field,
        )
        return ()
    groups: list[tuple[str, ...]] = []
    for group in value:
        if not isinstance(group, list) or not group:
            _issue(
                errors,
                "invalid_policy",
                "Each group key must be a non-empty list.",
                field=field,
            )
            continue
        if any(not isinstance(key, str) or key not in _SAFE_GROUP_FIELDS for key in group):
            _issue(
                errors,
                "invalid_policy",
                "A group key contains an unsupported field.",
                field=field,
            )
            continue
        normalized = tuple(group)
        if len(set(normalized)) != len(normalized) or normalized in groups:
            _issue(
                errors,
                "invalid_policy",
                "Group keys and their fields must be unique.",
                field=field,
            )
            continue
        groups.append(normalized)
    return tuple(groups)


def _stat_fingerprint(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _manifest_stat_fingerprint(
    stat_result: os.stat_result,
) -> tuple[int, int, int, int, int]:
    """Separate seam so adversarial tests can target sample and manifest races independently."""

    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _hash_file(sample_file: _SampleFile, root: Path) -> str:
    """Hash one bounded, stable file descriptor and reject observable replacement."""

    digest = hashlib.sha256()
    with sample_file.path.open("rb") as handle:
        descriptor_before = os.fstat(handle.fileno())
        if descriptor_before.st_size > MAX_SAMPLE_FILE_BYTES:
            raise _SampleFileTooLarge
        try:
            resolved_before = sample_file.path.resolve(strict=True)
            resolved_before.relative_to(root)
            path_before = sample_file.path.stat()
        except (OSError, ValueError) as exc:
            raise _SampleFileChanged from exc
        if (
            resolved_before != sample_file.resolved_path
            or _stat_fingerprint(descriptor_before) != sample_file.fingerprint
            or _stat_fingerprint(path_before) != sample_file.fingerprint
        ):
            raise _SampleFileChanged

        total_bytes = 0
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total_bytes += len(chunk)
            if total_bytes > MAX_SAMPLE_FILE_BYTES:
                raise _SampleFileTooLarge
            digest.update(chunk)

        descriptor_after = os.fstat(handle.fileno())
        try:
            resolved_after = sample_file.path.resolve(strict=True)
            resolved_after.relative_to(root)
            path_after = sample_file.path.stat()
        except (OSError, ValueError) as exc:
            raise _SampleFileChanged from exc
        if (
            resolved_after != sample_file.resolved_path
            or _stat_fingerprint(descriptor_before) != _stat_fingerprint(descriptor_after)
            or _stat_fingerprint(descriptor_after) != _stat_fingerprint(path_after)
            or total_bytes != descriptor_after.st_size
        ):
            raise _SampleFileChanged
    return digest.hexdigest()


def _safe_file(root: Path, relative_path: str) -> tuple[_SampleFile | None, str | None]:
    if not _is_canonical_posix_path(relative_path):
        return None, "invalid_path"
    path = root.joinpath(*relative_path.split("/"))
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        path_stat = path.stat()
    except (OSError, ValueError):
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, ValueError):
            return None, "path_outside_root"
        return None, "file_missing"
    if not stat_module.S_ISREG(path_stat.st_mode):
        return None, "file_missing"
    fingerprint = _stat_fingerprint(path_stat)
    return (
        _SampleFile(
            path=path,
            resolved_path=resolved,
            fingerprint=fingerprint,
            size_bytes=path_stat.st_size,
        ),
        None,
    )


def _capture_manifest(path: Path) -> _ManifestSnapshot:
    with path.open("rb") as handle:
        descriptor_before = os.fstat(handle.fileno())
        if descriptor_before.st_size > MAX_MANIFEST_BYTES:
            raise _ManifestTooLarge
        try:
            resolved_before = path.resolve(strict=True)
            path_before = path.stat()
        except (OSError, ValueError) as exc:
            raise _ManifestChanged from exc
        if _manifest_stat_fingerprint(descriptor_before) != _manifest_stat_fingerprint(path_before):
            raise _ManifestChanged
        payload = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise _ManifestTooLarge
        descriptor_after = os.fstat(handle.fileno())
        try:
            resolved_after = path.resolve(strict=True)
            path_after = path.stat()
        except (OSError, ValueError) as exc:
            raise _ManifestChanged from exc
        fingerprint = _manifest_stat_fingerprint(descriptor_after)
        if (
            resolved_before != resolved_after
            or _manifest_stat_fingerprint(descriptor_before) != fingerprint
            or fingerprint != _manifest_stat_fingerprint(path_after)
            or len(payload) != descriptor_after.st_size
        ):
            raise _ManifestChanged
    digest = hashlib.sha256(payload).hexdigest()
    return _ManifestSnapshot(
        path=path,
        resolved_path=resolved_after,
        payload=payload,
        fingerprint=fingerprint,
        receipt=ManifestReceipt(
            sha256=digest,
            size_bytes=len(payload),
            device=fingerprint[0],
            inode=fingerprint[1],
            mtime_ns=fingerprint[3],
            ctime_ns=fingerprint[4],
        ),
    )


def _manifest_matches(snapshot: _ManifestSnapshot) -> bool:
    try:
        current = _capture_manifest(snapshot.path)
    except (OSError, _ManifestChanged, _ManifestTooLarge):
        return False
    return (
        current.resolved_path == snapshot.resolved_path
        and current.fingerprint == snapshot.fingerprint
        and current.receipt.sha256 == snapshot.receipt.sha256
    )


def _load_manifest(
    path: Path, errors: list[ValidationIssue]
) -> tuple[dict[str, Any] | None, _ManifestSnapshot | None]:
    try:
        snapshot = _capture_manifest(path)
    except FileNotFoundError:
        _issue(errors, "manifest_missing", "Manifest file does not exist.")
        return None, None
    except _ManifestTooLarge:
        _issue(errors, "manifest_too_large", "Manifest exceeds the safe size limit.")
        return None, None
    except _ManifestChanged:
        _issue(
            errors,
            "manifest_changed_during_validation",
            "Manifest changed identity or metadata while being read.",
        )
        return None, None
    except OSError:
        _issue(errors, "manifest_unreadable", "Manifest file could not be read.")
        return None, None
    try:
        raw = snapshot.payload.decode("utf-8")
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_parse_json_int,
            parse_float=_parse_json_float,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
        OverflowError,
    ):
        _issue(errors, "invalid_json", "Manifest is not valid unambiguous UTF-8 JSON.")
        return None, snapshot
    if not isinstance(parsed, dict):
        _issue(errors, "invalid_type", "Manifest root must be a JSON object.", field="manifest")
        return None, snapshot
    return parsed, snapshot


def validate_manifest(
    manifest_path: str | Path,
    dataset_root: str | Path,
    *,
    requested_use: str | None = None,
    now: datetime | None = None,
) -> ValidationReport:
    """Validate every manifest field and referenced file without modifying anything.

    Any parse, policy, provenance, path, file, hash, duplicate, leakage, or
    requested-use authorization error produces ``valid=False``. Reports
    intentionally never contain manifest values or absolute paths.
    """

    if now is None:
        validation_time = datetime.now(UTC)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    else:
        validation_time = now.astimezone(UTC)

    errors: list[ValidationIssue] = []
    try:
        root = Path(dataset_root).resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError
    except (OSError, RuntimeError):
        _issue(errors, "invalid_root", "Dataset root must be an existing directory.")
        return ValidationReport(False, None, 0, 0, tuple(errors))

    data, manifest_snapshot = _load_manifest(Path(manifest_path), errors)

    def finish_report(
        schema_version: int | None,
        sample_count: int,
        verified_files: int,
        *,
        profile_revision: str | None = None,
    ) -> ValidationReport:
        if manifest_snapshot is not None and not _manifest_matches(manifest_snapshot):
            _issue(
                errors,
                "manifest_changed_during_validation",
                "Manifest changed after its validated snapshot was read.",
            )
        return ValidationReport(
            valid=not errors,
            schema_version=schema_version,
            sample_count=sample_count,
            verified_files=verified_files,
            errors=tuple(errors),
            profile_revision=profile_revision,
            manifest_receipt=(manifest_snapshot.receipt if manifest_snapshot is not None else None),
        )

    if data is None:
        return finish_report(None, 0, 0)

    top = _check_exact_fields(data, _TOP_LEVEL_FIELDS, errors, field="manifest")
    if top is None:
        return finish_report(None, 0, 0)

    raw_schema_version = top.get("schema_version")
    schema_version = (
        SCHEMA_VERSION
        if type(raw_schema_version) is int and raw_schema_version == SCHEMA_VERSION
        else None
    )
    if schema_version is None:
        _issue(
            errors,
            "unsupported_schema",
            "Only the explicitly supported schema version can be checked.",
            field="schema_version",
        )
        return finish_report(None, 0, 0)

    raw_profile_revision = top.get("profile_revision")
    profile_revision = PROFILE_REVISION if raw_profile_revision == PROFILE_REVISION else None
    if profile_revision is None:
        _issue(
            errors,
            "unsupported_profile_revision",
            "Manifest profile revision is missing or is not the immutable supported revision.",
            field="profile_revision",
        )

    dataset = _check_exact_fields(top.get("dataset"), _DATASET_FIELDS, errors, field="dataset")
    if dataset is not None:
        for name in _DATASET_FIELDS:
            if not _is_nonempty_string(dataset.get(name)):
                _issue(
                    errors,
                    "invalid_string",
                    "Dataset identity fields must be safe non-empty strings.",
                    field=f"dataset.{name}",
                )

    policy = _check_exact_fields(
        top.get("policy"),
        _POLICY_FIELDS,
        errors,
        field="policy",
        optional=_POLICY_OPTIONAL_FIELDS,
    )
    allowed_splits: tuple[str, ...] = ()
    allowed_licenses: tuple[str, ...] = ()
    permitted_uses: tuple[str, ...] = ()
    group_keys: tuple[tuple[str, ...], ...] = ()
    reject_within_split = False
    temporal_split_order: tuple[str, ...] = ()
    allow_equal_temporal_boundary = False
    retention_expiry: datetime | None = None
    if policy is not None:
        allowed_splits = _string_list(
            policy.get("allowed_splits"), errors, field="policy.allowed_splits"
        )
        if any(not _CANONICAL_ID_RE.fullmatch(split) for split in allowed_splits):
            _issue(
                errors,
                "invalid_policy",
                "Allowed splits must use canonical lowercase ASCII identifiers.",
                field="policy.allowed_splits",
            )
        allowed_licenses = _string_list(
            policy.get("allowed_licenses"), errors, field="policy.allowed_licenses"
        )
        if any(license_id.casefold() in _UNKNOWN_LICENSES for license_id in allowed_licenses):
            _issue(
                errors,
                "invalid_policy",
                "Unknown license markers cannot be approved.",
                field="policy.allowed_licenses",
            )
            allowed_licenses = tuple(
                license_id
                for license_id in allowed_licenses
                if license_id.casefold() not in _UNKNOWN_LICENSES
            )
        group_keys = _parse_group_policy(policy.get("group_disjoint_keys"), errors)
        reject_value = policy.get("reject_duplicates_within_split")
        if type(reject_value) is not bool:
            _issue(
                errors,
                "invalid_policy",
                "Duplicate policy must be a JSON boolean.",
                field="policy.reject_duplicates_within_split",
            )
        else:
            reject_within_split = reject_value

        consent = _check_exact_fields(
            policy.get("consent"), _CONSENT_FIELDS, errors, field="policy.consent"
        )
        consent_status: str | None = None
        if consent is not None:
            consent_status = _safe_policy_string(
                consent.get("status"),
                errors,
                field="policy.consent.status",
                allowed=_CONSENT_STATUSES,
            )
            _safe_opaque_reference(
                consent.get("evidence_reference"),
                errors,
                field="policy.consent.evidence_reference",
            )

        legal_basis = _check_exact_fields(
            policy.get("legal_basis"),
            _LEGAL_BASIS_FIELDS,
            errors,
            field="policy.legal_basis",
        )
        legal_basis_value: str | None = None
        if legal_basis is not None:
            legal_basis_value = _safe_policy_string(
                legal_basis.get("basis"),
                errors,
                field="policy.legal_basis.basis",
                allowed=_LEGAL_BASES,
            )
            _safe_opaque_reference(
                legal_basis.get("evidence_reference"),
                errors,
                field="policy.legal_basis.evidence_reference",
            )
        if legal_basis_value == "consent" and consent_status != "obtained":
            _issue(
                errors,
                "invalid_policy",
                "Consent legal basis requires recorded obtained consent.",
                field="policy.legal_basis",
            )

        redaction = _check_exact_fields(
            policy.get("redaction"),
            _REDACTION_FIELDS,
            errors,
            field="policy.redaction",
        )
        if redaction is not None:
            for redaction_field in (
                "direct_identifiers_removed",
                "screen_names_removed",
                "free_text_reviewed",
            ):
                if redaction.get(redaction_field) is not True:
                    _issue(
                        errors,
                        "invalid_policy",
                        "Required redaction control must be explicitly true.",
                        field=f"policy.redaction.{redaction_field}",
                    )
            _safe_policy_string(
                redaction.get("verification"),
                errors,
                field="policy.redaction.verification",
                allowed=_REDACTION_VERIFICATION,
            )

        permitted_uses = _string_list(
            policy.get("permitted_use"), errors, field="policy.permitted_use"
        )
        if any(use not in _PERMITTED_USES for use in permitted_uses):
            _issue(
                errors,
                "invalid_policy",
                "A permitted use is outside the supported allowlist.",
                field="policy.permitted_use",
            )

        if policy.get("real_money") is not False:
            _issue(
                errors,
                "real_money_forbidden",
                "Datasets involving real-money play are not permitted by this contract.",
                field="policy.real_money",
            )

        platform_terms = _check_exact_fields(
            policy.get("platform_terms"),
            _PLATFORM_TERMS_FIELDS,
            errors,
            field="policy.platform_terms",
        )
        if platform_terms is not None:
            _safe_policy_string(
                platform_terms.get("status"),
                errors,
                field="policy.platform_terms.status",
                allowed=_PLATFORM_TERMS_STATUSES,
            )
            _safe_opaque_reference(
                platform_terms.get("evidence_reference"),
                errors,
                field="policy.platform_terms.evidence_reference",
            )

        jurisdictions = _string_list(
            policy.get("jurisdiction"), errors, field="policy.jurisdiction"
        )
        if any(jurisdiction not in _ISO_3166_ALPHA2 for jurisdiction in jurisdictions):
            _issue(
                errors,
                "invalid_policy",
                "Jurisdictions must use explicit canonical codes.",
                field="policy.jurisdiction",
            )

        retention = _check_exact_fields(
            policy.get("retention"),
            _RETENTION_FIELDS,
            errors,
            field="policy.retention",
        )
        if retention is not None:
            retention_expiry = _parse_timestamp(retention.get("expires_at"))
            if retention_expiry is None:
                _issue(
                    errors,
                    "invalid_policy",
                    "Retention expiry must be a timezone-aware ISO-8601 timestamp.",
                    field="policy.retention.expires_at",
                )
            elif retention_expiry <= validation_time:
                _issue(
                    errors,
                    "retention_expired",
                    "Retention expiry must be later than the validation time.",
                    field="policy.retention.expires_at",
                )
            review_interval = retention.get("review_interval_days")
            if type(review_interval) is not int or not 1 <= review_interval <= 3650:
                _issue(
                    errors,
                    "invalid_policy",
                    "Retention review interval must be between 1 and 3650 days.",
                    field="policy.retention.review_interval_days",
                )

        player_identity = _check_exact_fields(
            policy.get("player_identity"),
            _PLAYER_IDENTITY_FIELDS,
            errors,
            field="policy.player_identity",
        )
        if player_identity is not None:
            _safe_policy_string(
                player_identity.get("scheme"),
                errors,
                field="policy.player_identity.scheme",
                allowed=_PLAYER_IDENTITY_SCHEMES,
            )
            key_version = player_identity.get("key_version")
            if not isinstance(key_version, str) or not _KEY_VERSION_RE.fullmatch(key_version):
                _issue(
                    errors,
                    "invalid_policy",
                    "Player identity key version must be an opaque version identifier.",
                    field="policy.player_identity.key_version",
                )
            separation_context = _safe_policy_string(
                player_identity.get("separation_context"),
                errors,
                field="policy.player_identity.separation_context",
            )
            if separation_context is not None and not _SEPARATION_CONTEXT_RE.fullmatch(
                separation_context
            ):
                _issue(
                    errors,
                    "invalid_policy",
                    "Player identity separation context must be a public canonical label.",
                    field="policy.player_identity.separation_context",
                )
            _safe_policy_string(
                player_identity.get("purpose"),
                errors,
                field="policy.player_identity.purpose",
                allowed=_PLAYER_IDENTITY_PURPOSES,
            )

        deletion = _check_exact_fields(
            policy.get("deletion"),
            _DELETION_FIELDS,
            errors,
            field="policy.deletion",
        )
        if deletion is not None:
            for deletion_field in (
                "on_request",
                "on_retention_expiry",
                "verification_required",
            ):
                if deletion.get(deletion_field) is not True:
                    _issue(
                        errors,
                        "invalid_policy",
                        "Deletion control must be explicitly true.",
                        field=f"policy.deletion.{deletion_field}",
                    )
            _safe_opaque_reference(
                deletion.get("procedure_id"),
                errors,
                field="policy.deletion.procedure_id",
            )

        if "temporal_order" in policy:
            temporal_order = _check_exact_fields(
                policy.get("temporal_order"),
                _TEMPORAL_ORDER_FIELDS,
                errors,
                field="policy.temporal_order",
            )
            if temporal_order is not None:
                temporal_split_order = _string_list(
                    temporal_order.get("split_order"),
                    errors,
                    field="policy.temporal_order.split_order",
                )
                if (
                    len(temporal_split_order) < 2
                    or set(temporal_split_order) != set(allowed_splits)
                    or len(temporal_split_order) != len(allowed_splits)
                ):
                    _issue(
                        errors,
                        "invalid_policy",
                        "Temporal split order must cover each allowed split exactly once.",
                        field="policy.temporal_order.split_order",
                    )
                    temporal_split_order = ()
                allow_equal = temporal_order.get("allow_equal_boundary")
                if type(allow_equal) is not bool:
                    _issue(
                        errors,
                        "invalid_policy",
                        "Temporal boundary policy must be a JSON boolean.",
                        field="policy.temporal_order.allow_equal_boundary",
                    )
                else:
                    allow_equal_temporal_boundary = allow_equal

    if requested_use is not None:
        if requested_use not in _PERMITTED_USES:
            _issue(
                errors,
                "invalid_requested_use",
                "Requested dataset use is outside the supported purpose vocabulary.",
                field="requested_use",
            )
        elif requested_use not in permitted_uses:
            _issue(
                errors,
                "use_not_permitted",
                "Requested dataset use is not permitted by the manifest policy.",
                field="requested_use",
            )

    raw_samples = top.get("samples")
    if not isinstance(raw_samples, list):
        _issue(errors, "invalid_type", "Samples must be a JSON array.", field="samples")
        return finish_report(schema_version, 0, 0, profile_revision=profile_revision)
    sample_count = len(raw_samples)
    if not raw_samples:
        _issue(errors, "empty_samples", "A dataset manifest must contain samples.", field="samples")
    if sample_count > MAX_SAMPLES:
        _issue(
            errors,
            "too_many_samples",
            "Manifest exceeds the safe sample limit.",
            field="samples",
        )
        return finish_report(
            schema_version,
            sample_count,
            0,
            profile_revision=profile_revision,
        )

    seen_ids: set[str] = set()
    seen_lexical_paths: set[str] = set()
    seen_resolved_paths: set[str] = set()
    seen_file_ids: set[tuple[int, int]] = set()
    seen_hashes: dict[str, tuple[str, int]] = {}
    seen_groups: list[dict[tuple[str, ...], tuple[str, int]]] = [dict() for _ in group_keys]
    mandatory_disjoint_fields: dict[str, tuple[str, dict[str, tuple[str, int]]]] = {
        "hashed_player_id": ("player_leakage", {}),
        "session": ("session_leakage", {}),
        "split_group": ("split_group_leakage", {}),
        "player_pseudonym": ("player_pseudonym_leakage", {}),
    }
    event_times_by_split: dict[str, list[tuple[datetime, int]]] = {}
    hash_candidates: list[_HashCandidate] = []
    verified_files = 0

    for index, raw_sample in enumerate(raw_samples):
        if len(errors) >= MAX_REPORTED_ERRORS:
            break
        sample_error_start = len(errors)
        sample = _check_exact_fields(
            raw_sample,
            _SAMPLE_FIELDS,
            errors,
            field="sample",
            sample_index=index,
            optional=_SAMPLE_OPTIONAL_FIELDS,
        )
        if sample is None:
            continue

        valid_strings = True
        for field in sorted(
            _SAMPLE_FIELDS - {"sha256", "hashed_player_id", "event_time", "source"}
        ):
            max_length = 1024 if field == "path" else 2048 if field == "source" else 256
            if not _is_nonempty_string(sample.get(field), max_length=max_length):
                _issue(
                    errors,
                    "invalid_string",
                    "Required provenance values must be safe non-empty strings.",
                    sample_index=index,
                    field=field,
                )
                valid_strings = False
        for identifier_field in ("id", "session", "client", "theme", "deck", "split_group"):
            if not _is_canonical_identifier(sample.get(identifier_field)):
                _issue(
                    errors,
                    "invalid_canonical_id",
                    "Leakage and sample identifiers must use canonical lowercase ASCII.",
                    sample_index=index,
                    field=identifier_field,
                )
                valid_strings = False
        if not _is_safe_source_reference(sample.get("source")):
            _issue(
                errors,
                "invalid_source_reference",
                "Source must be a canonical registry-style identifier, not a URL or free text.",
                sample_index=index,
                field="source",
            )
            valid_strings = False
        if "player_pseudonym" in sample and not _is_canonical_identifier(
            sample.get("player_pseudonym")
        ):
            _issue(
                errors,
                "invalid_canonical_id",
                "Player pseudonym must use canonical lowercase ASCII when provided.",
                sample_index=index,
                field="player_pseudonym",
            )
            valid_strings = False

        sample_id = sample.get("id")
        if isinstance(sample_id, str):
            if sample_id in seen_ids:
                _issue(
                    errors,
                    "duplicate_id",
                    "Sample identifiers must be unique.",
                    sample_index=index,
                    field="id",
                )
            seen_ids.add(sample_id)

        split = sample.get("split")
        if not isinstance(split, str) or split not in allowed_splits:
            _issue(
                errors,
                "unapproved_split",
                "Sample split is not explicitly approved by policy.",
                sample_index=index,
                field="split",
            )

        hashed_player_id = sample.get("hashed_player_id")
        valid_hashed_player_id = bool(
            isinstance(hashed_player_id, str) and _HASHED_PLAYER_ID_RE.fullmatch(hashed_player_id)
        )
        if not valid_hashed_player_id:
            _issue(
                errors,
                "invalid_hashed_player_id",
                "Player identity must be a canonical lowercase 64-character digest.",
                sample_index=index,
                field="hashed_player_id",
            )

        event_time = _parse_timestamp(sample.get("event_time"))
        if event_time is None:
            _issue(
                errors,
                "invalid_event_time",
                "Event time must be a valid timezone-aware ISO-8601 timestamp.",
                sample_index=index,
                field="event_time",
            )
        else:
            if event_time > validation_time + MAX_EVENT_TIME_FUTURE_SKEW:
                _issue(
                    errors,
                    "future_event_time",
                    "Event time is materially later than the validation time.",
                    sample_index=index,
                    field="event_time",
                )
            elif isinstance(split, str):
                event_times_by_split.setdefault(split, []).append((event_time, index))
            if retention_expiry is not None and event_time >= retention_expiry:
                _issue(
                    errors,
                    "retention_violation",
                    "Event time must precede the declared retention expiry.",
                    sample_index=index,
                    field="event_time",
                )

        license_id = sample.get("license")
        if (
            not isinstance(license_id, str)
            or license_id.casefold() in _UNKNOWN_LICENSES
            or license_id not in allowed_licenses
        ):
            _issue(
                errors,
                "unapproved_license",
                "Sample license is absent, unknown, or not explicitly approved.",
                sample_index=index,
                field="license",
            )

        raw_hash = sample.get("sha256")
        digest = raw_hash if isinstance(raw_hash, str) else ""
        valid_hash = bool(_SHA256_RE.fullmatch(digest))
        if not valid_hash:
            _issue(
                errors,
                "invalid_sha256",
                "SHA-256 must contain exactly 64 hexadecimal characters.",
                sample_index=index,
                field="sha256",
            )

        if valid_hash and isinstance(split, str):
            previous_hash = seen_hashes.get(digest)
            if previous_hash is not None:
                previous_split, _ = previous_hash
                code = (
                    "duplicate_sha_cross_split"
                    if previous_split != split
                    else "duplicate_sha_within_split"
                )
                if previous_split != split or reject_within_split:
                    _issue(
                        errors,
                        code,
                        "Duplicate file content violates the declared split policy.",
                        sample_index=index,
                        field="sha256",
                    )
            else:
                seen_hashes[digest] = (split, index)

        if isinstance(split, str):
            for identity_field, (code, seen_values) in mandatory_disjoint_fields.items():
                value = sample.get(identity_field)
                if identity_field == "hashed_player_id" and not valid_hashed_player_id:
                    continue
                if not isinstance(value, str) or not _is_nonempty_string(value):
                    continue
                previous_identity = seen_values.get(value)
                if previous_identity is not None and previous_identity[0] != split:
                    _issue(
                        errors,
                        code,
                        "A mandatory identity group occurs in more than one split.",
                        sample_index=index,
                        field=identity_field,
                    )
                elif previous_identity is None:
                    seen_values[value] = (split, index)

        if valid_strings and isinstance(split, str):
            for group_index, keys in enumerate(group_keys):
                if any(not _is_nonempty_string(sample.get(key)) for key in keys):
                    _issue(
                        errors,
                        "missing_group_value",
                        "Every policy-defined group field must be present and valid.",
                        sample_index=index,
                        field="group_disjoint_keys",
                    )
                    continue
                group = tuple(str(sample[key]) for key in keys)
                previous_group = seen_groups[group_index].get(group)
                if previous_group is not None and previous_group[0] != split:
                    _issue(
                        errors,
                        "group_leakage",
                        "A policy-defined group occurs in more than one split.",
                        sample_index=index,
                        field="group_disjoint_keys",
                    )
                elif previous_group is None:
                    seen_groups[group_index][group] = (split, index)

        relative_path = sample.get("path")
        if not isinstance(relative_path, str) or not _is_nonempty_string(
            relative_path, max_length=1024
        ):
            continue
        if not _is_canonical_posix_path(relative_path):
            _issue(
                errors,
                "invalid_path",
                "Sample path must be a canonical lowercase POSIX relative path.",
                sample_index=index,
                field="path",
            )
            continue
        if relative_path in seen_lexical_paths:
            _issue(
                errors,
                "duplicate_path",
                "Sample paths must be lexically unique.",
                sample_index=index,
                field="path",
            )
        else:
            seen_lexical_paths.add(relative_path)

        sample_file, path_error = _safe_file(root, relative_path)
        if path_error is not None:
            messages = {
                "invalid_path": "Sample path is not canonical.",
                "path_outside_root": "Referenced sample must remain inside the dataset root.",
                "file_missing": "Referenced sample file does not exist or is not a regular file.",
            }
            _issue(
                errors,
                path_error,
                messages[path_error],
                sample_index=index,
                field="path",
            )
            continue
        if sample_file is None:
            continue
        if sample_file.size_bytes > MAX_SAMPLE_FILE_BYTES:
            _issue(
                errors,
                "file_too_large",
                "Referenced sample exceeds the per-file safe size limit.",
                sample_index=index,
                field="path",
            )
        resolved_key = os.path.normcase(str(sample_file.resolved_path))
        if resolved_key in seen_resolved_paths:
            _issue(
                errors,
                "duplicate_resolved_path",
                "Multiple manifest paths resolve to the same sample file.",
                sample_index=index,
                field="path",
            )
        else:
            seen_resolved_paths.add(resolved_key)
        if sample_file.file_id in seen_file_ids:
            _issue(
                errors,
                "duplicate_file_identity",
                "Multiple manifest paths reference the same filesystem file identity.",
                sample_index=index,
                field="path",
            )
        else:
            seen_file_ids.add(sample_file.file_id)

        if valid_hash and len(errors) == sample_error_start:
            hash_candidates.append(
                _HashCandidate(
                    sample_index=index,
                    file=sample_file,
                    expected_digest=digest,
                )
            )

    if temporal_split_order:
        for earlier_index, earlier_split in enumerate(temporal_split_order):
            earlier_events = event_times_by_split.get(earlier_split, [])
            if not earlier_events:
                continue
            latest_earlier = max(earlier_events, key=lambda item: item[0])
            for later_split in temporal_split_order[earlier_index + 1 :]:
                later_events = event_times_by_split.get(later_split, [])
                if not later_events:
                    continue
                earliest_later = min(later_events, key=lambda item: item[0])
                violates_boundary = (
                    latest_earlier[0] > earliest_later[0]
                    if allow_equal_temporal_boundary
                    else latest_earlier[0] >= earliest_later[0]
                )
                if violates_boundary:
                    _issue(
                        errors,
                        "temporal_split_overlap",
                        "Declared temporal split order is violated.",
                        sample_index=earliest_later[1],
                        field="event_time",
                    )

    # Content hashing is a second phase. No sample bytes are read when policy,
    # structure, paths, aliases, grouping, or temporal gates already failed.
    if not errors:
        total_files = len(hash_candidates)
        total_bytes = sum(candidate.file.size_bytes for candidate in hash_candidates)
        if total_files > MAX_TOTAL_SAMPLE_FILES:
            _issue(
                errors,
                "aggregate_file_limit",
                "Dataset exceeds the aggregate file-count validation limit.",
                field="samples",
            )
        if total_bytes > MAX_TOTAL_SAMPLE_BYTES:
            _issue(
                errors,
                "aggregate_bytes_limit",
                "Dataset exceeds the aggregate byte validation limit.",
                field="samples",
            )

    if not errors:
        for candidate in hash_candidates:
            try:
                actual_digest = _hash_file(candidate.file, root)
            except _SampleFileTooLarge:
                _issue(
                    errors,
                    "file_too_large",
                    "Referenced sample exceeds the per-file safe size limit.",
                    sample_index=candidate.sample_index,
                    field="path",
                )
                continue
            except _SampleFileChanged:
                _issue(
                    errors,
                    "file_changed_during_validation",
                    "Referenced sample changed identity or metadata while being validated.",
                    sample_index=candidate.sample_index,
                    field="path",
                )
                continue
            except OSError:
                _issue(
                    errors,
                    "file_unreadable",
                    "Referenced sample file could not be read.",
                    sample_index=candidate.sample_index,
                    field="path",
                )
                continue
            if actual_digest != candidate.expected_digest:
                _issue(
                    errors,
                    "hash_mismatch",
                    "Referenced sample does not match its recorded SHA-256.",
                    sample_index=candidate.sample_index,
                    field="sha256",
                )
            else:
                verified_files += 1

    return finish_report(
        schema_version,
        sample_count,
        verified_files,
        profile_revision=profile_revision,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m poker_arena.ml.data_manifest",
        description="Read-only validation of a Poker Arena ML dataset manifest.",
    )
    parser.add_argument("--manifest", required=True, help="Path to the JSON manifest")
    parser.add_argument("--root", required=True, help="Root containing referenced samples")
    parser.add_argument(
        "--purpose",
        choices=sorted(_PERMITTED_USES),
        help="Optionally authorize one concrete use declared by policy.permitted_use",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check-only CLI, returning zero only for a fully valid dataset."""

    arguments = _parser().parse_args(argv)
    report = validate_manifest(
        arguments.manifest,
        arguments.root,
        requested_use=arguments.purpose,
    )
    print(
        json.dumps(
            report.as_dict(),
            ensure_ascii=True,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if report.valid else 1


if __name__ == "__main__":  # pragma: no cover - exercised through ``main`` in tests
    raise SystemExit(main())
