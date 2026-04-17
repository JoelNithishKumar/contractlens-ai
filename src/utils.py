from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def safe_json_dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def file_fingerprint(filename: str, file_bytes: bytes) -> str:
    hasher = hashlib.sha256()
    hasher.update(filename.encode("utf-8"))
    hasher.update(file_bytes)
    return hasher.hexdigest()