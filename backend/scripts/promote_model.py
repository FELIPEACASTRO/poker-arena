"""Create a reviewed promoted-manifest candidate after every scientific gate passes.

The command never overwrites the live MANIFEST.json.  It writes a new immutable
proposal that an authorized reviewer can compare and activate separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from poker_arena.ml.external_validation import (
    MAX_RECEIPT_BYTES,
    PROFILE_REVISION,
    PromotionEvidenceError,
    verify_promotion_receipt,
)
from poker_arena.model_artifacts import ModelArtifactUnavailable, verify_evaluation_candidate


class PromotionRejected(RuntimeError):
    pass


def _receipt_digest(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
            raise PromotionRejected("receipt is not a bounded regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise PromotionRejected("receipt is unavailable") from exc
    return hashlib.sha256(payload).hexdigest()


def build_promoted_manifest(
    *,
    artifact_path: Path,
    manifest_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    candidate = verify_evaluation_candidate(
        artifact_path,
        "vision",
        manifest_path=manifest_path,
    )
    receipt_digest = _receipt_digest(receipt_path)
    try:
        verify_promotion_receipt(
            receipt_path,
            expected_sha256=receipt_digest,
            artifact_sha256=candidate.sha256,
        )
    except PromotionEvidenceError as exc:
        raise PromotionRejected("scientific receipt did not pass the mandatory profile") from exc
    try:
        manifest_root = manifest_path.parent.resolve(strict=True)
        relative_receipt = receipt_path.resolve(strict=True).relative_to(manifest_root)
    except (OSError, ValueError) as exc:
        raise PromotionRejected("receipt must remain under the model manifest directory") from exc
    relative_text = relative_receipt.as_posix()
    if relative_text.startswith("../"):
        raise PromotionRejected("receipt path is outside the model manifest directory")

    try:
        manifest_payload = manifest_path.read_bytes()
        if hashlib.sha256(manifest_payload).hexdigest() != candidate.manifest_sha256:
            raise PromotionRejected("candidate manifest changed after verification")
        raw = json.loads(manifest_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionRejected("candidate manifest could not be re-read") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("artifacts"), list):
        raise PromotionRejected("candidate manifest is invalid")
    wanted = artifact_path.resolve()
    matches: list[dict[str, Any]] = []
    for entry in raw["artifacts"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise PromotionRejected("candidate manifest inventory is invalid")
        try:
            declared = manifest_root.joinpath(*entry["path"].split("/")).resolve(strict=False)
        except OSError as exc:
            raise PromotionRejected("candidate manifest path is invalid") from exc
        if declared == wanted:
            matches.append(entry)
    if len(matches) != 1 or matches[0].get("state") != "candidate":
        raise PromotionRejected("exactly one candidate entry must match the artifact")
    matches[0]["state"] = "promoted"
    matches[0]["promotion_receipt"] = {
        "path": relative_text,
        "sha256": receipt_digest,
        "profile_revision": PROFILE_REVISION,
    }
    raw["snapshot_date"] = datetime.now(UTC).date().isoformat()
    return raw


def write_manifest_proposal(path: Path, manifest: dict[str, Any]) -> str:
    payload = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PromotionRejected("output proposal already exists") from exc
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed promoted manifest proposal")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        proposal = build_promoted_manifest(
            artifact_path=arguments.artifact,
            manifest_path=arguments.manifest,
            receipt_path=arguments.receipt,
        )
        digest = write_manifest_proposal(arguments.output, proposal)
    except (PromotionRejected, ModelArtifactUnavailable) as exc:
        print(json.dumps({"decision": "rejected", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"decision": "proposal-created", "manifest_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
