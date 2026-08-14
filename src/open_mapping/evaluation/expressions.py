"""Deterministic bounded expression evaluator."""

from __future__ import annotations

from typing import cast

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.dates import canonical_rfc3339, format_date_pattern, parse_rfc3339
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.evaluation.numbers import (
    MAX_SAFE_INTEGER,
    normalize_number,
    parse_decimal_string,
    parse_integer_string,
    round_half_away_from_zero,
)
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.expressions import Expression
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.pointers import resolve_pointer

_MISSING = object()


class EvaluationContext(OpenMappingModel):
    input_document: JsonValue
    output_document: JsonValue = {}
    current_stack: tuple[JsonValue, ...] = ()


def _issue(
    code: IssueCode,
    message: str,
    correction: str,
    *,
    source_path: str | None = None,
    target_path: str | None = None,
) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component="evaluation",
        message=message,
        correction=correction,
        source_path=source_path,
        target_path=target_path,
    )


def _domain_error(
    code: IssueCode,
    message: str,
    correction: str,
    *,
    source_path: str | None = None,
    target_path: str | None = None,
) -> OpenMappingError:
    return OpenMappingError(
        (
            _issue(
                code,
                message,
                correction,
                source_path=source_path,
                target_path=target_path,
            ),
        )
    )


def _count_nodes(value: object) -> int:
    if isinstance(value, dict):
        return 1 + sum(_count_nodes(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_count_nodes(item) for item in value)
    return 1


def _check_limits(value: object, limits: EvaluationLimits) -> None:
    if _count_nodes(value) > limits.max_output_nodes:
        raise _domain_error(
            IssueCode.EVALUATION_LIMIT_EXCEEDED,
            "output exceeds max_output_nodes",
            "Reduce array size or simplify the mapping.",
        )
    total_length = 0

    def visit(item: object) -> None:
        nonlocal total_length
        if isinstance(item, str):
            total_length += len(item)
            if total_length > limits.max_string_length:
                raise _domain_error(
                    IssueCode.EVALUATION_LIMIT_EXCEEDED,
                    "output string length exceeds max_string_length",
                    "Reduce string size or simplify the mapping.",
                )
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)


def _numeric(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _domain_error(
            IssueCode.TYPE_MISMATCH,
            "numeric operation requires a number",
            "Cast the value to integer or number first.",
        )
    if isinstance(value, int) and abs(value) > MAX_SAFE_INTEGER:
        raise _domain_error(
            IssueCode.NUMERIC_PRECISION_RISK,
            "integer exceeds JavaScript safe integer range",
            "Use a bounded integer source.",
        )
    try:
        result = float(value)
    except OverflowError as exc:
        raise _domain_error(
            IssueCode.NUMERIC_PRECISION_RISK,
            "numeric input exceeds binary64 range",
            "Use a bounded numeric source.",
        ) from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise _domain_error(
            IssueCode.NUMERIC_PRECISION_RISK,
            "non-finite numeric input is not supported",
            "Validate source data before mapping.",
        )
    return result


def _cast(value: JsonValue, target_type: str) -> JsonValue:
    if target_type == "string":
        if value is None or isinstance(value, (str, int, float, bool)):
            if value is None:
                return "null"
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)
        raise _domain_error(
            IssueCode.TYPE_MISMATCH,
            "cast to string requires a JSON scalar",
            "Use a scalar source value.",
        )
    if target_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise _domain_error(
            IssueCode.TYPE_MISMATCH,
            "cast to boolean requires a boolean or true/false string",
            "Use a boolean-compatible source value.",
        )
    if target_type == "integer":
        if isinstance(value, bool):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "cast to integer does not accept booleans",
                "Use an integer or base-10 integer string.",
            )
        if isinstance(value, int):
            if abs(value) > MAX_SAFE_INTEGER:
                raise _domain_error(
                    IssueCode.NUMERIC_PRECISION_RISK,
                    "integer exceeds JavaScript safe integer range",
                    "Use a bounded integer source.",
                )
            return value
        if isinstance(value, str):
            try:
                parsed = parse_integer_string(value)
            except ValueError:
                pass
            else:
                if abs(parsed) > MAX_SAFE_INTEGER:
                    raise _domain_error(
                        IssueCode.NUMERIC_PRECISION_RISK,
                        "integer exceeds JavaScript safe integer range",
                        "Use a bounded integer source.",
                    )
                return parsed
        raise _domain_error(
            IssueCode.TYPE_MISMATCH,
            "cast to integer requires an integer or base-10 integer string",
            "Use an integer-compatible source value.",
        )
    if target_type == "number":
        if isinstance(value, bool):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "cast to number does not accept booleans",
                "Use a numeric source value.",
            )
        if isinstance(value, str):
            try:
                parsed_number = parse_decimal_string(value)
            except ValueError as exc:
                raise _domain_error(
                    IssueCode.TYPE_MISMATCH,
                    "cast to number requires a numeric string",
                    "Use a numeric-compatible source value.",
                ) from exc
            return normalize_number(parsed_number)
        if not isinstance(value, (int, float)):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "cast to number requires a numeric value",
                "Use a numeric-compatible source value.",
            )
        if abs(value) > MAX_SAFE_INTEGER:
            raise _domain_error(
                IssueCode.NUMERIC_PRECISION_RISK,
                "integer exceeds JavaScript safe integer range",
                "Use a bounded integer source.",
            )
        return normalize_number(float(value))
    raise _domain_error(
        IssueCode.INVALID_EXPRESSION,
        f"unknown cast target type {target_type!r}",
        "Use string, integer, number, or boolean.",
    )


def _evaluate(
    expression: object, context: EvaluationContext, limits: EvaluationLimits, depth: int
) -> JsonValue:
    if depth > limits.max_expression_depth:
        raise _domain_error(
            IssueCode.EVALUATION_LIMIT_EXCEEDED,
            "expression exceeds max_expression_depth",
            "Reduce expression nesting.",
        )
    op = getattr(expression, "op")
    if op == "get":
        document = getattr(expression, "document")
        path = getattr(expression, "path")
        if document == "input":
            base = context.input_document
        elif document == "output":
            base = context.output_document
        else:
            if not context.current_stack:
                raise _domain_error(
                    IssueCode.INVALID_EXPRESSION,
                    "get(current) requires an active map item",
                    "Use get(current) only inside a map expression.",
                    source_path=path,
                )
            base = context.current_stack[-1]
        return resolve_pointer(base, path)
    if op == "literal":
        return cast(JsonValue, getattr(expression, "value"))
    if op == "object":
        result: dict[str, JsonValue] = {}
        for key, child in getattr(expression, "fields").items():
            result[key] = _evaluate(child, context, limits, depth + 1)
        return cast(JsonValue, result)
    if op == "array":
        items = getattr(expression, "items")
        if len(items) > limits.max_array_items:
            raise _domain_error(
                IssueCode.EVALUATION_LIMIT_EXCEEDED,
                "array expression exceeds max_array_items",
                "Reduce array size.",
            )
        return cast(JsonValue, [_evaluate(item, context, limits, depth + 1) for item in items])
    if op == "map":
        collection = _evaluate(getattr(expression, "collection"), context, limits, depth + 1)
        if not isinstance(collection, list):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "map collection must evaluate to an array",
                "Use an array source field.",
            )
        if len(collection) > limits.max_array_items:
            raise _domain_error(
                IssueCode.EVALUATION_LIMIT_EXCEEDED,
                "map collection exceeds max_array_items",
                "Reduce source array size.",
            )
        output: list[JsonValue] = []
        for item in collection:
            item_value = cast(JsonValue, item)
            item_context = EvaluationContext(
                input_document=context.input_document,
                output_document=context.output_document,
                current_stack=context.current_stack + (item_value,),
            )
            output.append(
                _evaluate(getattr(expression, "expression"), item_context, limits, depth + 1)
            )
        return cast(JsonValue, output)
    if op == "coalesce":
        for operand in getattr(expression, "operands"):
            try:
                value = _evaluate(operand, context, limits, depth + 1)
            except OpenMappingError as exc:
                if any(issue.code == IssueCode.SOURCE_PATH_NOT_FOUND for issue in exc.issues):
                    continue
                raise
            if value is not _MISSING and value is not None:
                return value
        return None
    if op == "concat":
        parts: list[str] = []
        for operand in getattr(expression, "operands"):
            value = _evaluate(operand, context, limits, depth + 1)
            if not isinstance(value, str):
                raise _domain_error(
                    IssueCode.TYPE_MISMATCH,
                    "concat requires string operands",
                    "Cast each operand to string explicitly.",
                )
            parts.append(value)
        return cast(str, getattr(expression, "separator")).join(parts)
    if op == "cast":
        return _cast(
            _evaluate(getattr(expression, "value"), context, limits, depth + 1),
            getattr(expression, "target_type"),
        )
    if op == "if":
        condition = _evaluate(getattr(expression, "condition"), context, limits, depth + 1)
        if not isinstance(condition, bool):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "if condition must evaluate to a boolean",
                "Use a boolean comparison or cast.",
            )
        branch = getattr(expression, "then") if condition else getattr(expression, "otherwise")
        return _evaluate(branch, context, limits, depth + 1)
    if op == "equals":
        left = _evaluate(getattr(expression, "left"), context, limits, depth + 1)
        right = _evaluate(getattr(expression, "right"), context, limits, depth + 1)
        try:
            return semantic_json_equal(left, right)
        except ValueError as exc:
            raise _domain_error(
                IssueCode.NUMERIC_PRECISION_RISK,
                "semantic comparison contains an unsupported JSON number",
                "Use finite JSON numbers within JavaScript's safe integer range.",
            ) from exc
    if op == "not":
        value = _evaluate(getattr(expression, "value"), context, limits, depth + 1)
        if not isinstance(value, bool):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                "not requires a boolean value",
                "Use a boolean comparison or cast.",
            )
        return not value
    if op in {"and", "or"}:
        values = [
            _evaluate(operand, context, limits, depth + 1)
            for operand in getattr(expression, "operands")
        ]
        if any(not isinstance(value, bool) for value in values):
            raise _domain_error(
                IssueCode.TYPE_MISMATCH,
                f"{op} requires boolean operands",
                "Use boolean comparisons or casts.",
            )
        return all(values) if op == "and" else any(values)
    if op == "lookup":
        key = _evaluate(getattr(expression, "key"), context, limits, depth + 1)
        values = getattr(expression, "values")
        if isinstance(key, str) and key in values:
            return cast(JsonValue, values[key])
        default = getattr(expression, "default")
        return _evaluate(default, context, limits, depth + 1) if default is not None else None
    if op in {"add", "subtract", "multiply", "divide"}:
        left = _numeric(_evaluate(getattr(expression, "left"), context, limits, depth + 1))
        right = _numeric(_evaluate(getattr(expression, "right"), context, limits, depth + 1))
        if op == "add":
            numeric_result: float = left + right
        elif op == "subtract":
            numeric_result = left - right
        elif op == "multiply":
            numeric_result = left * right
        else:
            if right == 0.0:
                raise _domain_error(
                    IssueCode.DIVIDE_BY_ZERO,
                    "division by zero is not supported",
                    "Guard the denominator before dividing.",
                )
            numeric_result = left / right
        try:
            return normalize_number(numeric_result)
        except ValueError as exc:
            raise _domain_error(
                IssueCode.NUMERIC_PRECISION_RISK,
                "numeric result is outside supported bounds",
                "Use bounded numeric source values.",
            ) from exc
    if op == "round":
        value = _numeric(_evaluate(getattr(expression, "value"), context, limits, depth + 1))
        try:
            return round_half_away_from_zero(value, int(getattr(expression, "digits")))
        except ValueError as exc:
            raise _domain_error(
                IssueCode.NUMERIC_PRECISION_RISK,
                "round result is outside supported bounds",
                "Use bounded numeric source values.",
            ) from exc
    if op == "parse_date":
        value = _evaluate(getattr(expression, "value"), context, limits, depth + 1)
        if not isinstance(value, str):
            raise _domain_error(
                IssueCode.INVALID_DATE,
                "parse_date requires an RFC 3339 string",
                "Use a string source value with an explicit timezone.",
            )
        try:
            return canonical_rfc3339(parse_rfc3339(value))
        except ValueError as exc:
            raise _domain_error(
                IssueCode.INVALID_DATE,
                "invalid RFC 3339 date-time value",
                "Use an RFC 3339 date-time with an explicit timezone.",
            ) from exc
    if op == "format_date":
        value = _evaluate(getattr(expression, "value"), context, limits, depth + 1)
        if not isinstance(value, str):
            raise _domain_error(
                IssueCode.INVALID_DATE,
                "format_date requires a canonical RFC 3339 string",
                "Parse the date first.",
            )
        try:
            return format_date_pattern(value, getattr(expression, "pattern"))
        except ValueError as exc:
            raise _domain_error(
                IssueCode.INVALID_DATE,
                "invalid canonical date or format pattern",
                "Use a canonical RFC 3339 value and supported tokens.",
            ) from exc
    raise _domain_error(
        IssueCode.INVALID_EXPRESSION,
        f"unknown expression operation {op!r}",
        "Use a supported v0.1 expression operation.",
    )


def evaluate_expression(
    expression: Expression,
    context: EvaluationContext,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
) -> JsonValue:
    value = _evaluate(expression, context, limits, 0)
    _check_limits(value, limits)
    return value
