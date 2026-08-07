"""Canonical binding between scientific evidence and one model-manifest contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_LIFECYCLE_FIELDS = frozenset({"state", "promotion_receipt"})


def promotion_contract_sha256(entry: Mapping[str, Any]) -> str:
    """Hash every semantic/governance field while allowing candidate -> promoted."""

    contract = {key: value for key, value in entry.items() if key not in _LIFECYCLE_FIELDS}
    payload = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()
