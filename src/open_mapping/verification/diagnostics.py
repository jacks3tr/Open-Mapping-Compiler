"""Deterministic, value-redacted JSON Schema diagnostics."""

from __future__ import annotations

from collections.abc import Iterable

from jsonschema.exceptions import ValidationError

from open_mapping.pointers import escape_pointer_token


def validation_error_sort_key(error: ValidationError) -> tuple[str, str]:
    """Sort errors without incorporating instance values into diagnostics."""

    return (validation_error_pointer(error), _constraint_category(error))


def validation_error_message(
    artifact: str, error: ValidationError, *, diagnostic_values: bool = False
) -> str:
    """Render a public validation message without the invalid instance value."""

    pointer = validation_error_pointer(error)
    category = _constraint_category(error)
    if category == "required-property":
        message = f"{artifact} violates required-property constraint at {pointer}"
    elif category == "type":
        message = f"{artifact} has incompatible type at {pointer}"
    elif category == "enum":
        message = f"{artifact} value is outside the allowed enum at {pointer}"
    elif category == "pattern":
        message = f"{artifact} string violates the required pattern at {pointer}"
    elif category == "format":
        message = f"{artifact} string violates the required format at {pointer}"
    elif category == "additional-property":
        message = f"{artifact} has an unsupported property at {pointer}"
    elif category == "string-length":
        message = f"{artifact} string violates a length constraint at {pointer}"
    elif category == "array-size":
        message = f"{artifact} array violates a size constraint at {pointer}"
    elif category == "numeric-range":
        message = f"{artifact} number violates a range constraint at {pointer}"
    else:
        message = f"{artifact} violates a schema constraint at {pointer}"
    if diagnostic_values:
        message += f" (observed {_redacted_value_summary(error.instance)})"
    return message


def validation_error_pointer(error: ValidationError) -> str:
    """Return the affected instance pointer, including a missing required property."""

    tokens = [str(token) for token in error.absolute_path]
    if _constraint_category(error) == "required-property":
        missing = _missing_required_property(error)
        if missing is not None:
            tokens.append(missing)
    return "/" + "/".join(escape_pointer_token(token) for token in tokens) if tokens else "/"


def _constraint_category(error: ValidationError) -> str:
    validator = error.validator
    if validator == "required":
        return "required-property"
    if validator == "type":
        return "type"
    if validator == "enum":
        return "enum"
    if validator == "pattern":
        return "pattern"
    if validator == "format":
        return "format"
    if validator == "additionalProperties":
        return "additional-property"
    if validator in {"minLength", "maxLength"}:
        return "string-length"
    if validator in {"minItems", "maxItems", "uniqueItems"}:
        return "array-size"
    if validator in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}:
        return "numeric-range"
    return "schema"


def _missing_required_property(error: ValidationError) -> str | None:
    required = error.validator_value
    instance = error.instance
    if not isinstance(required, Iterable) or isinstance(required, (str, bytes)):
        return None
    if not isinstance(instance, dict):
        return None
    for value in required:
        if isinstance(value, str) and value not in instance:
            return value
    return None


def _redacted_value_summary(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return f"string(length={_bounded_count(len(value))})"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return f"array(length={_bounded_count(len(value))})"
    if isinstance(value, dict):
        return f"object(property_count={_bounded_count(len(value))})"
    return "value"


def _bounded_count(value: int) -> str:
    return str(value) if value <= 1000 else "1000+"
