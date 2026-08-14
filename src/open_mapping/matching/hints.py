"""Structured business instruction to expression conversion."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.model.expressions import Expression
from open_mapping.model.mappings import Evidence, EvidenceKind, MappingRule


def _literal(value: object) -> dict[str, object]:
    return {"op": "literal", "value": value}


def _get(source: str) -> dict[str, object]:
    return {"op": "get", "path": source, "document": "input"}


def hint_to_rule(hint: object, target_schema_id: str, target_schema_version: str) -> MappingRule:
    expression: object
    if hasattr(hint, "target") and hasattr(hint, "expression"):
        target = str(getattr(hint, "target"))
        reason = str(getattr(hint, "reason"))
        expression = getattr(hint, "expression")
    elif hasattr(hint, "target") and (
        hasattr(hint, "source")
        or hasattr(hint, "values")
        or hasattr(hint, "factors")
        or hasattr(hint, "pattern")
    ):
        target = str(getattr(hint, "target"))
        reason = str(getattr(hint, "reason"))
        if hasattr(hint, "pattern") and hasattr(hint, "source"):
            expression = {
                "op": "format_date",
                "value": {"op": "parse_date", "value": _get(str(getattr(hint, "source")))},
                "pattern": str(getattr(hint, "pattern")),
            }
        elif hasattr(hint, "values"):
            expression = {
                "op": "lookup",
                "key": _get(str(getattr(hint, "source"))),
                "values": dict(getattr(hint, "values")),
                "default": _literal(getattr(hint, "default"))
                if getattr(hint, "default", None) is not None
                else None,
            }
        elif hasattr(hint, "factors"):
            factors = {
                key: int(value) if float(value).is_integer() else float(value)
                for key, value in getattr(hint, "factors").items()
            }
            expression = {
                "op": "cast",
                "target_type": "integer",
                "value": {
                    "op": "multiply",
                    "left": _get(str(getattr(hint, "value_source"))),
                    "right": {
                        "op": "lookup",
                        "key": _get(str(getattr(hint, "unit_source"))),
                        "values": factors,
                        "default": None,
                    },
                },
            }
        elif hasattr(hint, "source"):
            expression = _get(str(getattr(hint, "source")))
        else:
            raise ValueError("unsupported hint shape")
    elif hasattr(hint, "value") and hasattr(hint, "target"):
        target = str(getattr(hint, "target"))
        reason = str(getattr(hint, "reason"))
        expression = _literal(getattr(hint, "value"))
    else:
        raise ValueError("unsupported hint shape")
    return MappingRule(
        target=target,
        expression=TypeAdapter(Expression).validate_python(expression),
        confidence=0.0,
        confidence_method="business-instruction-v0.1",
        evidence=(Evidence(kind=EvidenceKind.BUSINESS_INSTRUCTION, detail=reason),),
    )
