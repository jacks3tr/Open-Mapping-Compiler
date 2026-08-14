"""Privacy-safe redaction helpers."""

from __future__ import annotations

import re
from typing import cast

from open_mapping.model.json_types import JsonValue
from open_mapping.providers.protocol import ProviderRequest

_EMAIL_LOCAL = re.compile(r"[A-Za-z0-9._%+-]+@")
_AUTHORIZATION = re.compile(r"(?i)\b(authorization)\s*[:=]\s*(?:bearer\s+)?(?!\[REDACTED\])\S+")
_BEARER = re.compile(r"(?i)\b(bearer)\s+(?!\[REDACTED\])\S+")
_NAMED_SECRET = re.compile(r"(?i)\b(api[_-]?key|token)\s*[:=]\s*(?!\[REDACTED\])\S+")
_LONG_DIGITS = re.compile(r"\d{12,}")
_HIGH_ENTROPY = re.compile(r"[A-Za-z0-9_-]{32,}")


def _redact_text_with_count(text: str) -> tuple[str, int]:
    count = 0

    def replace_named_secret(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}: [REDACTED]"

    def replace_bearer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)} [REDACTED]"

    def replace_value(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[REDACTED]"

    def replace_email(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[REDACTED]@"

    result = _AUTHORIZATION.sub(replace_named_secret, text)
    result = _BEARER.sub(replace_bearer, result)
    result = _NAMED_SECRET.sub(replace_named_secret, result)
    result = _EMAIL_LOCAL.sub(replace_email, result)
    result = _LONG_DIGITS.sub(replace_value, result)
    result = _HIGH_ENTROPY.sub(replace_value, result)
    return result, count


def redact_text(text: str) -> str:
    return _redact_text_with_count(text)[0]


def redact_json(value: JsonValue) -> JsonValue:
    return redact_json_with_count(value)[0]


def redact_json_with_count(value: JsonValue) -> tuple[JsonValue, int]:
    if isinstance(value, str):
        return _redact_text_with_count(value)
    if isinstance(value, list):
        result: list[object] = []
        count = 0
        for item in value:
            redacted, item_count = redact_json_with_count(cast(JsonValue, item))
            result.append(redacted)
            count += item_count
        return result, count
    if isinstance(value, dict):
        result_dict: dict[str, object] = {}
        count = 0
        for key in sorted(value):
            redacted_key, key_count = _redact_text_with_count(key)
            unique_key = redacted_key
            collision_index = 2
            while unique_key in result_dict:
                unique_key = f"{redacted_key}#{collision_index}"
                collision_index += 1
            item = value[key]
            redacted, item_count = redact_json_with_count(cast(JsonValue, item))
            result_dict[unique_key] = redacted
            count += key_count + item_count
        return result_dict, count
    return value, 0


def sanitize_provider_request(
    request: ProviderRequest, *, allow_raw_samples: bool
) -> tuple[ProviderRequest, int]:
    payload = request.model_dump(mode="json")
    if not allow_raw_samples:
        payload["raw_samples"] = None
    redacted, count = redact_json_with_count(cast(JsonValue, payload))
    return ProviderRequest.model_validate(redacted), count
