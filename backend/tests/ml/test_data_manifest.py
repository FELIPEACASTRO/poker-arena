from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from poker_arena.ml import data_manifest as manifest_module
from poker_arena.ml.data_manifest import MAX_REPORTED_ERRORS, main, validate_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashed_player_id(player_pseudonym: str) -> str:
    return hmac.new(
        b"test-only-player-identity-key",
        player_pseudonym.encode(),
        hashlib.sha256,
    ).hexdigest()


def _sample(file_path: Path, *, split: str = "train", **overrides: object) -> dict[str, object]:
    event_times = {
        "train": "2026-01-01T00:00:00Z",
        "validation": "2026-02-01T00:00:00Z",
        "test": "2026-03-01T00:00:00Z",
    }
    player_pseudonym = f"player-{split}"
    sample: dict[str, object] = {
        "id": f"sample-{split}",
        "path": file_path.name,
        "sha256": _sha256(file_path),
        "source": f"source-{split}",
        "source_version": "2026-07-17",
        "session": f"session-{split}",
        "client": f"client-{split}",
        "theme": "classic",
        "deck": f"deck-{split}",
        "player_pseudonym": player_pseudonym,
        "hashed_player_id": _hashed_player_id(player_pseudonym),
        "event_time": event_times[split],
        "split_group": f"split-group-{split}",
        "split": split,
        "license": "CC-BY-4.0",
    }
    sample.update(overrides)
    return sample


def _manifest(samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_revision": manifest_module.PROFILE_REVISION,
        "dataset": {"name": "fixture", "version": "1.0.0"},
        "policy": {
            "allowed_splits": ["train", "validation", "test"],
            "allowed_licenses": ["CC-BY-4.0"],
            "group_disjoint_keys": [["source", "session"], ["client", "theme", "deck"]],
            "reject_duplicates_within_split": True,
            "consent": {
                "status": "obtained",
                "evidence_reference": "consent-batch-2026-01",
            },
            "legal_basis": {
                "basis": "consent",
                "evidence_reference": "legal-review-2026-01",
            },
            "redaction": {
                "direct_identifiers_removed": True,
                "screen_names_removed": True,
                "free_text_reviewed": True,
                "verification": "automated-and-human",
            },
            "permitted_use": ["research", "model-training", "model-evaluation"],
            "real_money": False,
            "platform_terms": {
                "status": "reviewed-compatible",
                "evidence_reference": "terms-review-2026-01",
            },
            "jurisdiction": ["BR"],
            "player_identity": {
                "scheme": "hmac-sha256",
                "key_version": "kv-player-identity-2026-01",
                "separation_context": "poker-arena/player-identity/v1",
                "purpose": "split-leakage-prevention",
            },
            "retention": {
                "expires_at": "2099-12-31T23:59:59Z",
                "review_interval_days": 365,
            },
            "deletion": {
                "on_request": True,
                "on_retention_expiry": True,
                "procedure_id": "deletion-procedure-v1",
                "verification_required": True,
            },
            "temporal_order": {
                "split_order": ["train", "validation", "test"],
                "allow_equal_boundary": False,
            },
        },
        "samples": samples,
    }


def _write_manifest(root: Path, data: dict[str, object]) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _codes(report: object) -> set[str]:
    return {issue.code for issue in report.errors}  # type: ignore[attr-defined]


def test_valid_manifest_verifies_every_file(tmp_path: Path) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")
    manifest = _write_manifest(
        tmp_path,
        _manifest([_sample(train), _sample(validation, split="validation")]),
    )

    report = validate_manifest(manifest, tmp_path)

    assert report.valid
    assert report.sample_count == 2
    assert report.verified_files == 2
    assert report.errors == ()
    assert report.profile_revision == manifest_module.PROFILE_REVISION
    assert report.manifest_receipt is not None
    assert report.manifest_receipt.sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    serialized_receipt = report.manifest_receipt.as_dict()
    assert serialized_receipt["size_bytes"] == manifest.stat().st_size
    assert isinstance(serialized_receipt["identity"], str)
    assert str(tmp_path) not in json.dumps(serialized_receipt)


@pytest.mark.parametrize("revision", [None, "legacy-v1", "poker-arena-dataset-manifest-v1-latest"])
def test_profile_revision_is_required_and_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision: str | None,
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    if revision is None:
        del manifest_data["profile_revision"]
    else:
        manifest_data["profile_revision"] = revision
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("invalid profile must block hashing"),
    )

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert "unsupported_profile_revision" in _codes(report)
    assert report.verified_files == 0


def test_json_integer_bomb_is_sanitized_and_fail_closed(tmp_path: Path) -> None:
    bomb = "9" * 5000
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"schema_version":' + bomb + ',"profile_revision":"x","dataset":{},'
        '"policy":{},"samples":[]}',
        encoding="utf-8",
    )

    report = validate_manifest(manifest, tmp_path)
    serialized = json.dumps(report.as_dict())

    assert not report.valid
    assert "invalid_json" in _codes(report)
    assert bomb[:100] not in serialized


@pytest.mark.parametrize("license_value", [None, "", "UNKNOWN", "CC0-1.0"])
def test_missing_or_unapproved_license_is_blocked(
    tmp_path: Path, license_value: str | None
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path)
    if license_value is None:
        del sample["license"]
    else:
        sample["license"] = license_value

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert _codes(report) & {"missing_field", "unapproved_license", "invalid_string"}


def test_duplicate_content_across_splits_is_blocked(tmp_path: Path) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"same-content")
    validation.write_bytes(b"same-content")
    report = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(train), _sample(validation, split="validation")]),
        ),
        tmp_path,
    )

    assert not report.valid
    assert "duplicate_sha_cross_split" in _codes(report)


def test_duplicate_content_inside_split_obeys_strict_policy(tmp_path: Path) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"same-content")
    second.write_bytes(b"same-content")
    second_sample = _sample(
        second,
        source="second-source",
        session="second-session",
        client="second-client",
        deck="second-deck",
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), second_sample])),
        tmp_path,
    )

    assert not report.valid
    assert "duplicate_sha_within_split" in _codes(report)


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": "source-train", "session": "session-train"},
        {"client": "client-train", "theme": "classic", "deck": "deck-train"},
    ],
)
def test_policy_group_leakage_across_splits_is_blocked(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")
    second = _sample(validation, split="validation", **overrides)

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(train), second])),
        tmp_path,
    )

    assert not report.valid
    assert "group_leakage" in _codes(report)


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        (
            {
                "hashed_player_id": _hashed_player_id("player-train"),
                "player_pseudonym": "different-pseudonym",
            },
            "player_leakage",
        ),
        ({"session": "session-train", "source": "different-source"}, "session_leakage"),
        ({"split_group": "split-group-train"}, "split_group_leakage"),
        (
            {
                "player_pseudonym": "player-train",
                "hashed_player_id": hashlib.sha256(b"different-player").hexdigest(),
            },
            "player_pseudonym_leakage",
        ),
    ],
)
def test_mandatory_identity_groups_cannot_cross_splits(
    tmp_path: Path, overrides: dict[str, object], expected_code: str
) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")

    report = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(train), _sample(validation, split="validation", **overrides)]),
        ),
        tmp_path,
    )

    assert not report.valid
    assert expected_code in _codes(report)


def test_same_player_may_repeat_inside_one_split(tmp_path: Path) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    repeated = _sample(
        second,
        id="sample-train-2",
        source="source-train-2",
        session="session-train-2",
        client="client-train-2",
        deck="deck-train-2",
        split_group="split-group-train-2",
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), repeated])),
        tmp_path,
    )

    assert report.valid


def test_temporal_split_overlap_is_blocked_when_declared(tmp_path: Path) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")
    validation_sample = _sample(
        validation,
        split="validation",
        event_time="2025-12-31T23:59:59Z",
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(train), validation_sample])),
        tmp_path,
    )

    assert not report.valid
    assert "temporal_split_overlap" in _codes(report)


def test_event_after_retention_expiry_is_blocked(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path, event_time="2031-01-01T00:00:00Z")])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    retention = policy["retention"]
    assert isinstance(retention, dict)
    retention["expires_at"] = "2030-01-01T00:00:00Z"

    report = validate_manifest(
        _write_manifest(tmp_path, manifest_data),
        tmp_path,
        now=datetime(2029, 1, 1, tzinfo=UTC),
    )

    assert not report.valid
    assert "retention_violation" in _codes(report)


def test_temporal_order_is_optional_but_event_time_remains_required(tmp_path: Path) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")
    manifest_data = _manifest(
        [
            _sample(train),
            _sample(validation, split="validation", event_time="2025-12-31T23:59:59Z"),
        ]
    )
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    del policy["temporal_order"]

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert report.valid


def test_equal_temporal_boundary_requires_explicit_opt_in(tmp_path: Path) -> None:
    train = tmp_path / "train.bin"
    validation = tmp_path / "validation.bin"
    train.write_bytes(b"train")
    validation.write_bytes(b"validation")
    manifest_data = _manifest(
        [
            _sample(train, event_time="2026-01-01T00:00:00Z"),
            _sample(validation, split="validation", event_time="2026-01-01T00:00:00Z"),
        ]
    )
    strict = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    temporal = policy["temporal_order"]
    assert isinstance(temporal, dict)
    temporal["allow_equal_boundary"] = True
    opted_in = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not strict.valid
    assert "temporal_split_overlap" in _codes(strict)
    assert opted_in.valid


@pytest.mark.parametrize(
    "event_time",
    [
        "2026-01-01T00:00:00",
        "not-a-date",
        "2026-02-30T00:00:00Z",
        "2026-01-01 00:00:00Z",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00.000Z",
    ],
)
def test_event_time_must_be_valid_and_timezone_aware(tmp_path: Path, event_time: str) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(sample_path, event_time=event_time)])),
        tmp_path,
    )

    assert not report.valid
    assert "invalid_event_time" in _codes(report)


def test_expired_retention_is_rejected_against_injected_clock(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    retention = policy["retention"]
    assert isinstance(retention, dict)
    retention["expires_at"] = "2030-01-01T00:00:00Z"

    report = validate_manifest(
        _write_manifest(tmp_path, manifest_data),
        tmp_path,
        now=datetime(2030, 1, 1, tzinfo=UTC),
    )

    assert not report.valid
    assert "retention_expired" in _codes(report)


def test_materially_future_event_uses_fixed_clock_and_explicit_skew(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    fixed_now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    within_skew = (fixed_now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    beyond_skew = (fixed_now + timedelta(minutes=5, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    accepted = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(sample_path, event_time=within_skew)]),
        ),
        tmp_path,
        now=fixed_now,
    )
    rejected = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(sample_path, event_time=beyond_skew)]),
        ),
        tmp_path,
        now=fixed_now,
    )

    assert accepted.valid
    assert not rejected.valid
    assert "future_event_time" in _codes(rejected)


def test_injected_clock_must_be_timezone_aware(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest = _write_manifest(tmp_path, _manifest([_sample(sample_path)]))

    with pytest.raises(ValueError, match="timezone-aware"):
        validate_manifest(manifest, tmp_path, now=datetime(2026, 7, 17))


def test_player_pseudonym_is_optional_but_hashed_identity_is_required(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path)
    del sample["player_pseudonym"]
    valid = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    sample_without_hash = _sample(sample_path)
    del sample_without_hash["hashed_player_id"]
    missing_hash = validate_manifest(
        _write_manifest(tmp_path, _manifest([sample_without_hash])),
        tmp_path,
    )

    assert valid.valid
    assert not missing_hash.valid
    assert "missing_field" in _codes(missing_hash)


def test_hashed_player_id_is_canonical_lowercase_hex(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    uppercase_hash = hashlib.sha256(b"player-train").hexdigest().upper()

    report = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(sample_path, hashed_player_id=uppercase_hash)]),
        ),
        tmp_path,
    )

    assert not report.valid
    assert "invalid_hashed_player_id" in _codes(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "Sample-Train"),
        ("session", "sessão-train"),
        ("client", "client/path"),
        ("theme", "theme:dark"),
        ("deck", "deck_"),
        ("split_group", " split-group"),
        ("player_pseudonym", "player."),
    ],
)
def test_leakage_identifiers_require_canonical_lowercase_ascii_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("invalid identifiers must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(sample_path, **{field: value})])),
        tmp_path,
    )

    assert not report.valid
    assert "invalid_canonical_id" in _codes(report)
    assert report.verified_files == 0


def test_sha256_requires_canonical_lowercase_hex_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("invalid digest must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(sample_path, sha256=_sha256(sample_path).upper())]),
        ),
        tmp_path,
    )

    assert not report.valid
    assert "invalid_sha256" in _codes(report)
    assert report.verified_files == 0


def test_raw_player_identifiers_are_not_accepted(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path, raw_player_id="real-account-name")

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "unexpected_field" in _codes(report)


def test_player_identity_policy_rejects_embedded_secret_without_echoing_it(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    player_identity = policy["player_identity"]
    assert isinstance(player_identity, dict)
    attacker_key = "hmac_key_material_must_not_be_echoed"
    attacker_value = "super-secret-player-identity-key-must-not-be-echoed"
    player_identity[attacker_key] = attacker_value

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)
    serialized = json.dumps(report.as_dict())

    assert not report.valid
    assert "unexpected_field" in _codes(report)
    assert attacker_key not in serialized
    assert attacker_value not in serialized


def test_adversarial_manifest_errors_are_capped_and_sanitized(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path)
    attacker_key_prefix = "attacker_controlled_key_must_not_be_echoed_"
    attacker_value_prefix = "attacker-controlled-value-must-not-be-echoed-"
    sample.update(
        {
            f"{attacker_key_prefix}{index:04d}": f"{attacker_value_prefix}{index:04d}"
            for index in range(MAX_REPORTED_ERRORS + 100)
        }
    )

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)
    serialized = json.dumps(report.as_dict())

    assert not report.valid
    assert len(report.errors) == MAX_REPORTED_ERRORS
    assert report.errors[-1].code == "error_limit_reached"
    assert attacker_key_prefix not in serialized
    assert attacker_value_prefix not in serialized


def test_legacy_policy_without_governance_is_fail_closed(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    for field in (
        "consent",
        "legal_basis",
        "redaction",
        "permitted_use",
        "real_money",
        "platform_terms",
        "jurisdiction",
        "player_identity",
        "retention",
        "deletion",
    ):
        del policy[field]

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert "missing_field" in _codes(report)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (("real_money", True), "real_money_forbidden"),
        (("permitted_use", []), "invalid_policy"),
        (("jurisdiction", ["UNKNOWN"]), "invalid_policy"),
        (("deletion.on_request", False), "invalid_policy"),
        (("redaction.screen_names_removed", False), "invalid_policy"),
        (("consent.status", "not-required"), "invalid_policy"),
        (("platform_terms.status", "UNKNOWN"), "invalid_policy"),
        (("retention.expires_at", "not-a-date"), "invalid_policy"),
        (("retention.expires_at", "2030-01-01 00:00:00Z"), "invalid_policy"),
        (("retention.expires_at", "2030-01-01T00:00:00+00:00"), "invalid_policy"),
        (("retention.expires_at", "2030-01-01T00:00:00.000Z"), "invalid_policy"),
        (("player_identity.scheme", "sha256"), "invalid_policy"),
        (("player_identity.key_version", "embedded-secret"), "invalid_policy"),
        (("player_identity.separation_context", "UNKNOWN"), "invalid_policy"),
        (("player_identity.purpose", "analytics"), "invalid_policy"),
        (("temporal_order.split_order", ["train", "validation"]), "invalid_policy"),
    ],
)
def test_governance_policy_is_machine_checked_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: tuple[str, object],
    expected_code: str,
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    field_path, value = mutation
    if "." in field_path:
        parent, child = field_path.split(".", maxsplit=1)
        nested = policy[parent]
        assert isinstance(nested, dict)
        nested[child] = value
    else:
        policy[field_path] = value
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("invalid policy must block hashing"),
    )

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert expected_code in _codes(report)
    assert report.verified_files == 0


def test_requested_use_must_be_explicitly_permitted(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest = _write_manifest(tmp_path, _manifest([_sample(sample_path)]))

    allowed = validate_manifest(manifest, tmp_path, requested_use="model-training")
    denied = validate_manifest(manifest, tmp_path, requested_use="redistribution")
    unsupported = validate_manifest(manifest, tmp_path, requested_use="production-wagering")

    assert allowed.valid
    assert not denied.valid
    assert "use_not_permitted" in _codes(denied)
    assert not unsupported.valid
    assert "invalid_requested_use" in _codes(unsupported)


def test_cli_enforces_requested_purpose(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest = _write_manifest(tmp_path, _manifest([_sample(sample_path)]))

    exit_code = main(
        [
            "--manifest",
            str(manifest),
            "--root",
            str(tmp_path),
            "--purpose",
            "redistribution",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["valid"] is False
    assert {issue["code"] for issue in output["errors"]} >= {"use_not_permitted"}


def test_normative_schema_and_example_expose_the_executable_contract(tmp_path: Path) -> None:
    schema = json.loads(
        (REPOSITORY_ROOT / "docs" / "schemas" / "dataset-manifest-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (REPOSITORY_ROOT / "docs" / "examples" / "dataset-manifest.example.json").read_text(
            encoding="utf-8"
        )
    )

    governance_fields = {
        "consent",
        "legal_basis",
        "redaction",
        "permitted_use",
        "real_money",
        "platform_terms",
        "jurisdiction",
        "player_identity",
        "retention",
        "deletion",
    }
    sample_fields = {"hashed_player_id", "event_time", "split_group"}
    policy_schema = schema["properties"]["policy"]
    sample_schema = schema["$defs"]["sample"]
    assert schema["additionalProperties"] is False
    assert policy_schema["additionalProperties"] is False
    assert sample_schema["additionalProperties"] is False
    assert "profile_revision" in schema["required"]
    assert schema["properties"]["profile_revision"] == {"const": manifest_module.PROFILE_REVISION}
    assert example["profile_revision"] == manifest_module.PROFILE_REVISION
    assert governance_fields <= set(policy_schema["required"])
    assert sample_fields <= set(sample_schema["required"])
    assert policy_schema["properties"]["real_money"] == {"const": False}
    player_identity_schema = policy_schema["properties"]["player_identity"]
    assert player_identity_schema["additionalProperties"] is False
    assert set(player_identity_schema["required"]) == {
        "scheme",
        "key_version",
        "separation_context",
        "purpose",
    }
    assert player_identity_schema["properties"]["scheme"] == {"const": "hmac-sha256"}
    assert player_identity_schema["properties"]["purpose"] == {"const": "split-leakage-prevention"}
    assert example["policy"]["player_identity"] == {
        "scheme": "hmac-sha256",
        "key_version": "kv-player-identity-2026-01",
        "separation_context": "poker-arena/player-identity/v1",
        "purpose": "split-leakage-prevention",
    }
    jurisdiction_pattern = re.compile(
        policy_schema["properties"]["jurisdiction"]["items"]["pattern"]
    )
    assert all(jurisdiction_pattern.fullmatch(code) for code in manifest_module._ISO_3166_ALPHA2)
    assert not jurisdiction_pattern.fullmatch("ZZ")
    assert not jurisdiction_pattern.fullmatch("BR-SP")
    assert policy_schema["properties"]["consent"]["properties"]["evidence_reference"] == {
        "$ref": "#/$defs/opaqueReference"
    }
    source_pattern = re.compile(schema["$defs"]["sourceReference"]["pattern"])
    assert source_pattern.fullmatch(example["samples"][0]["source"])
    assert not source_pattern.fullmatch("https://user:password@example.test/data")
    assert not source_pattern.fullmatch("Registry-Entry")
    assert not source_pattern.fullmatch("registry/")
    canonical_id_pattern = re.compile(schema["$defs"]["canonicalId"]["pattern"])
    assert canonical_id_pattern.fullmatch(example["samples"][0]["session"])
    assert not canonical_id_pattern.fullmatch("Session-001")
    assert not canonical_id_pattern.fullmatch("sessao-ç")
    assert policy_schema["properties"]["allowed_splits"]["items"] == {"$ref": "#/$defs/canonicalId"}
    assert policy_schema["properties"]["temporal_order"]["properties"]["split_order"]["items"] == {
        "$ref": "#/$defs/canonicalId"
    }

    timestamp_schema = schema["$defs"]["rfc3339UtcSeconds"]
    assert timestamp_schema["format"] == "date-time"
    assert timestamp_schema["pattern"] == manifest_module._RFC3339_UTC_PATTERN
    timestamp_pattern = re.compile(timestamp_schema["pattern"])
    assert timestamp_pattern.fullmatch(example["samples"][0]["event_time"])
    for rejected_timestamp in (
        "2026-01-01 12:00:00Z",
        "2026-01-01T12:00:00+00:00",
        "2026-01-01T12:00:00.000Z",
    ):
        assert not timestamp_pattern.fullmatch(rejected_timestamp)

    path_pattern = re.compile(schema["$defs"]["safePath"]["pattern"])
    assert path_pattern.fullmatch(example["samples"][0]["path"])
    for rejected_path in (
        "Upper.bin",
        "dir\\sample.bin",
        "sample.bin:metadata",
        "./sample.bin",
        "dir/../sample.bin",
        "dir/./sample.bin",
        "dir//sample.bin",
        "con.txt",
        "dir/nul.dat",
        ".hidden",
        "sample.",
    ):
        assert not path_pattern.fullmatch(rejected_path)

    sample_path = tmp_path / "images" / "capture-000001.png"
    sample_path.parent.mkdir()
    sample_path.write_bytes(b"synthetic-example")
    example["samples"][0]["sha256"] = _sha256(sample_path)
    manifest = _write_manifest(tmp_path, example)

    report = validate_manifest(manifest, tmp_path)

    assert report.valid


@pytest.mark.parametrize(
    ("path_value", "expected_code"),
    [
        ("../outside.bin", "invalid_path"),
        ("missing.bin", "file_missing"),
    ],
)
def test_unsafe_or_missing_paths_are_blocked(
    tmp_path: Path, path_value: str, expected_code: str
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path, path=path_value)

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert expected_code in _codes(report)


def test_absolute_sample_path_is_blocked_even_when_file_exists(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path, path=str(sample_path.resolve()))

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "invalid_path" in _codes(report)


@pytest.mark.parametrize(
    "path_value",
    [
        "Upper.bin",
        "dir\\sample.bin",
        "sample.bin:metadata",
        "./sample.bin",
        "dir/../sample.bin",
        "dir/./sample.bin",
        "dir//sample.bin",
        "con.txt",
        "dir/nul.dat",
        "dir/com1.log",
        ".hidden",
        "sample.",
    ],
)
def test_path_profile_rejects_noncanonical_and_windows_alias_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_value: str,
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("invalid path must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(sample_path, path=path_value)])),
        tmp_path,
    )

    assert not report.valid
    assert "invalid_path" in _codes(report)
    assert report.verified_files == 0


def _second_alias_sample(path: Path) -> dict[str, object]:
    pseudonym = "player-alias"
    return _sample(
        path,
        id="sample-alias",
        source="source-alias",
        session="session-alias",
        client="client-alias",
        deck="deck-alias",
        player_pseudonym=pseudonym,
        hashed_player_id=_hashed_player_id(pseudonym),
        split_group="split-group-alias",
    )


def test_duplicate_lexical_path_is_rejected_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("duplicate path must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(
            tmp_path,
            _manifest([_sample(sample_path), _second_alias_sample(sample_path)]),
        ),
        tmp_path,
    )

    assert not report.valid
    assert "duplicate_path" in _codes(report)
    assert report.verified_files == 0


def test_hardlink_alias_is_rejected_by_file_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.bin"
    alias = tmp_path / "alias.bin"
    first.write_bytes(b"same-file-id")
    try:
        os.link(first, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable in this test environment: {exc}")
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("FileId alias must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), _second_alias_sample(alias)])),
        tmp_path,
    )

    assert not report.valid
    assert "duplicate_file_identity" in _codes(report)
    assert report.verified_files == 0


def test_symlink_alias_is_rejected_by_resolved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.bin"
    alias = tmp_path / "alias.bin"
    first.write_bytes(b"same-resolved-file")
    alias.write_bytes(b"same-resolved-file")
    original_resolve = Path.resolve

    def alias_resolve(path: Path, *args, **kwargs):
        if path == alias:
            return original_resolve(first, strict=True)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", alias_resolve)
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("resolved alias must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), _second_alias_sample(alias)])),
        tmp_path,
    )

    assert not report.valid
    assert "duplicate_resolved_path" in _codes(report)
    assert report.verified_files == 0

    # Add a real symlink check opportunistically, while the deterministic path
    # above keeps this security control covered on locked-down Windows hosts.
    monkeypatch.undo()
    alias.unlink()
    try:
        alias.symlink_to(first.name)
    except OSError:
        return
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("resolved alias must block hashing"),
    )
    real_report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), _second_alias_sample(alias)])),
        tmp_path,
    )
    assert not real_report.valid
    assert "duplicate_resolved_path" in _codes(real_report)
    assert real_report.verified_files == 0


def test_hash_mismatch_is_blocked(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"actual")
    sample = _sample(sample_path, sha256="0" * 64)

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "hash_mismatch" in _codes(report)
    assert report.verified_files == 0


def test_sample_file_size_cap_is_enforced_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sixsix")
    sample = _sample(sample_path)
    monkeypatch.setattr(manifest_module, "MAX_SAMPLE_FILE_BYTES", 5)

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "file_too_large" in _codes(report)
    assert report.verified_files == 0


@pytest.mark.parametrize(
    ("limit_name", "expected_code"),
    [
        ("MAX_TOTAL_SAMPLE_FILES", "aggregate_file_limit"),
        ("MAX_TOTAL_SAMPLE_BYTES", "aggregate_bytes_limit"),
    ],
)
def test_aggregate_resource_caps_are_enforced_before_any_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    expected_code: str,
) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first-file")
    second.write_bytes(b"second-file")
    limit = 1 if limit_name == "MAX_TOTAL_SAMPLE_FILES" else first.stat().st_size
    monkeypatch.setattr(manifest_module, limit_name, limit)
    monkeypatch.setattr(
        manifest_module,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("aggregate limits must block hashing"),
    )

    report = validate_manifest(
        _write_manifest(tmp_path, _manifest([_sample(first), _second_alias_sample(second)])),
        tmp_path,
    )

    assert not report.valid
    assert expected_code in _codes(report)
    assert report.verified_files == 0


def test_observable_file_change_during_hashing_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"stable-at-manifest-time")
    sample = _sample(sample_path)
    original_fingerprint = manifest_module._stat_fingerprint
    calls = 0

    def changing_fingerprint(stat_result: object) -> tuple[int, int, int, int, int]:
        nonlocal calls
        calls += 1
        fingerprint = original_fingerprint(stat_result)  # type: ignore[arg-type]
        if calls == 2:
            return (*fingerprint[:-1], fingerprint[-1] + 1)
        return fingerprint

    monkeypatch.setattr(manifest_module, "_stat_fingerprint", changing_fingerprint)

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "file_changed_during_validation" in _codes(report)
    assert report.verified_files == 0


def test_manifest_change_after_snapshot_is_detected_and_original_receipt_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"stable-sample")
    manifest_data = _manifest([_sample(sample_path)])
    manifest = _write_manifest(tmp_path, manifest_data)
    original_manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    def change_manifest_during_hashing(
        _sample_file: object,
        _root: Path,
    ) -> str:
        changed_data = dict(manifest_data)
        changed_data["dataset"] = {"name": "changed-fixture", "version": "1.0.1"}
        manifest.write_text(json.dumps(changed_data), encoding="utf-8")
        return _sha256(sample_path)

    monkeypatch.setattr(manifest_module, "_hash_file", change_manifest_during_hashing)

    report = validate_manifest(manifest, tmp_path)

    assert not report.valid
    assert "manifest_changed_during_validation" in _codes(report)
    assert report.manifest_receipt is not None
    assert report.manifest_receipt.sha256 == original_manifest_digest
    assert report.manifest_receipt.sha256 != hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(report.as_dict())


@pytest.mark.parametrize("jurisdiction", ["ZZ", "BR-SP", "CAN", "unknown"])
def test_jurisdiction_requires_iso_3166_alpha2(tmp_path: Path, jurisdiction: str) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    policy["jurisdiction"] = [jurisdiction]

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert "invalid_policy" in _codes(report)


@pytest.mark.parametrize(
    "reference",
    [
        "https://registry.example/evidence",
        "evidence?id=secret",
        "../evidence",
        "evidence/path",
        " evidence-id",
        "evidence-id ",
    ],
)
def test_evidence_references_are_opaque_identifiers_only(tmp_path: Path, reference: str) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path)])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    consent = policy["consent"]
    assert isinstance(consent, dict)
    consent["evidence_reference"] = reference

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert "invalid_policy" in _codes(report)


@pytest.mark.parametrize(
    "source",
    [
        "https://user:password@example.test/data",
        "https://example.test/data?token=secret",
        "../outside-registry",
        "registry//entry",
        "registry..entry",
        "registry/./entry",
        "registry/-/entry",
        "registry/",
        "Registry-Entry",
        " registry-entry",
        "UNKNOWN",
    ],
)
def test_source_is_registry_identifier_not_url_path_or_free_text(
    tmp_path: Path, source: str
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    sample = _sample(sample_path, source=source)

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "invalid_source_reference" in _codes(report)


def test_policy_cannot_approve_unknown_license_marker(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    manifest_data = _manifest([_sample(sample_path, license="UNKNOWN")])
    policy = manifest_data["policy"]
    assert isinstance(policy, dict)
    policy["allowed_licenses"] = ["UNKNOWN"]

    report = validate_manifest(_write_manifest(tmp_path, manifest_data), tmp_path)

    assert not report.valid
    assert "invalid_policy" in _codes(report)
    assert "unapproved_license" in _codes(report)


def test_duplicate_json_keys_and_unknown_schema_are_fail_closed(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":1,"schema_version":1,"dataset":{},"policy":{},"samples":[]}',
        encoding="utf-8",
    )
    unsupported = _write_manifest(tmp_path, {**_manifest([]), "schema_version": 2})

    duplicate_report = validate_manifest(duplicate, tmp_path)
    unsupported_report = validate_manifest(unsupported, tmp_path)

    assert not duplicate_report.valid
    assert "invalid_json" in _codes(duplicate_report)
    assert not unsupported_report.valid
    assert "unsupported_schema" in _codes(unsupported_report)


def test_cli_is_check_only_and_does_not_echo_manifest_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(b"sample")
    secret_marker = "hf_secret_must_not_be_echoed"
    sample = _sample(sample_path, source=secret_marker, license="UNKNOWN")
    manifest = _write_manifest(tmp_path, _manifest([sample]))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    exit_code = main(["--manifest", str(manifest), "--root", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert secret_marker not in output
    assert str(tmp_path) not in output
    parsed = json.loads(output)
    assert parsed["valid"] is False
    assert parsed["error_count"] >= 1
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_cli_does_not_echo_unrecognized_key_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    redaction_probe = "api_token_value_" + "must_not_be_echoed"
    manifest_data = _manifest([])
    manifest_data[redaction_probe] = "anything"
    manifest = _write_manifest(tmp_path, manifest_data)

    exit_code = main(["--manifest", str(manifest), "--root", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert redaction_probe not in output
    assert json.loads(output)["valid"] is False


@given(st.binary(min_size=1, max_size=256))
@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_any_changed_payload_fails_the_recorded_sha256(tmp_path: Path, payload: bytes) -> None:
    sample_path = tmp_path / "sample.bin"
    sample_path.write_bytes(payload)
    sample = _sample(sample_path)
    sample_path.write_bytes(payload + b"\x00")

    report = validate_manifest(_write_manifest(tmp_path, _manifest([sample])), tmp_path)

    assert not report.valid
    assert "hash_mismatch" in _codes(report)
