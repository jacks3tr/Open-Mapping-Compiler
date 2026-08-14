"""RFC 6901 JSON Pointer utilities."""

from __future__ import annotations

from typing import cast

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue


def escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def unescape_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def normalize_pointer(pointer: str) -> str:
    if pointer == "":
        return ""
    if not pointer.startswith("/"):
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="pointers",
                    message=f"invalid JSON Pointer {pointer!r}: must be empty or start with '/'",
                    correction="Use a valid RFC 6901 pointer.",
                ),
            )
        )
    tokens = pointer[1:].split("/")
    for token in tokens:
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                    raise OpenMappingError(
                        (
                            Issue(
                                code=IssueCode.INVALID_INPUT,
                                severity=Severity.ERROR,
                                component="pointers",
                                message=f"invalid JSON Pointer escape in {pointer!r}",
                                correction="Use ~0 for '~' and ~1 for '/'.",
                            ),
                        )
                    )
                index += 2
            else:
                index += 1
    return pointer


def split_pointer(pointer: str) -> tuple[str, ...]:
    normalized = normalize_pointer(pointer)
    if normalized == "":
        return ()
    return tuple(unescape_pointer_token(token) for token in normalized[1:].split("/"))


def _missing_issue(pointer: str, component: str = "pointers") -> Issue:
    return Issue(
        code=IssueCode.SOURCE_PATH_NOT_FOUND,
        severity=Severity.ERROR,
        component=component,
        message=f"JSON Pointer {pointer!r} does not resolve",
        correction="Use a path that exists in the document.",
        source_path=pointer,
    )


def resolve_pointer(document: JsonValue, pointer: str) -> JsonValue:
    tokens = split_pointer(pointer)
    current: JsonValue = document
    if not tokens:
        return current
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise OpenMappingError((_missing_issue(pointer),))
            current = cast(JsonValue, current[token])
        elif isinstance(current, list):
            if not token.isdigit():
                raise OpenMappingError((_missing_issue(pointer),))
            idx = int(token)
            if idx >= len(current):
                raise OpenMappingError((_missing_issue(pointer),))
            current = cast(JsonValue, current[idx])
        else:
            raise OpenMappingError((_missing_issue(pointer),))
    return current


def assign_pointer(document: dict[str, object], pointer: str, value: object) -> dict[str, object]:
    tokens = split_pointer(pointer)
    result = dict(document)
    current: dict[str, object] = result
    for index, token in enumerate(tokens):
        if token.isdigit():
            raise OpenMappingError(
                (
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="pointers",
                        message="numeric array-index assignment is not supported in mapping rule targets",
                        correction="Use an object field path for mapping targets.",
                        target_path=pointer,
                    ),
                )
            )
        last = index == len(tokens) - 1
        if last:
            current[token] = value
        else:
            existing = current.get(token)
            if existing is None or isinstance(existing, dict):
                child: dict[str, object] = {} if existing is None else dict(existing)
                current[token] = child
                current = child
            else:
                raise OpenMappingError(
                    (
                        Issue(
                            code=IssueCode.OVERLAPPING_TARGET_ASSIGNMENT,
                            severity=Severity.ERROR,
                            component="pointers",
                            message=f"cannot assign {pointer!r}: an existing value blocks the parent path",
                            correction="Do not assign overlapping object and scalar targets.",
                            target_path=pointer,
                        ),
                    )
                )
    return result
