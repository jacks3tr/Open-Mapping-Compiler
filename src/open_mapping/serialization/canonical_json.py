"""Canonical JSON serialization."""

import json
import math
from typing import Any

from open_mapping.model.json_types import JsonValue


def _clean(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("non-finite numbers are not valid JSON")
    if isinstance(value, dict):
        return {
            str(key): _clean(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def canonical_json(value: JsonValue) -> str:
    return json.dumps(_clean(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_json_bytes(value: JsonValue) -> bytes:
    return canonical_json(value).encode("utf-8")
