"""Shared identity fingerprints and timestamps for the chapter workflow."""

import hashlib
import json
from datetime import UTC, datetime


def digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()
