"""Static expression type inference."""

from __future__ import annotations

from open_mapping.model.expressions import Expression
from open_mapping.model.json_types import JsonValue
from open_mapping.model.schema import JsonType, SchemaDocument

ExpressionType = frozenset[JsonType]

_JSON_TYPE = {
    bool: JsonType.BOOLEAN,
    int: JsonType.INTEGER,
    float: JsonType.NUMBER,
    str: JsonType.STRING,
}


def _value_types(value: JsonValue) -> frozenset[JsonType]:
    if value is None:
        return frozenset({JsonType.NULL})
    if isinstance(value, bool):
        return frozenset({JsonType.BOOLEAN})
    if isinstance(value, int):
        return frozenset({JsonType.INTEGER})
    if isinstance(value, float):
        return frozenset({JsonType.NUMBER})
    if isinstance(value, str):
        return frozenset({JsonType.STRING})
    if isinstance(value, list):
        return frozenset({JsonType.ARRAY})
    return frozenset({JsonType.OBJECT})


def _field_types(
    schema: SchemaDocument, pointer: str, *, guaranteed_base: str = ""
) -> frozenset[JsonType]:
    field = schema.field(pointer)
    if field is None:
        return frozenset()
    pointer_tokens = pointer.strip("/").split("/") if pointer else []
    base_tokens = guaranteed_base.strip("/").split("/") if guaranteed_base else []
    required = True
    for length in range(len(base_tokens) + 1, len(pointer_tokens) + 1):
        ancestor = schema.field("/" + "/".join(pointer_tokens[:length]))
        if ancestor is None or not ancestor.required:
            required = False
            break
    return field.types if required else field.types | {JsonType.NULL}


def _join_pointer(base: str, path: str) -> str:
    if path in {"", "/"}:
        return base
    return base.rstrip("/") + "/" + path.lstrip("/")


def _get_pointer(expression: Expression, current_pointer: str | None) -> str | None:
    if getattr(expression, "op") != "get":
        return None
    document = getattr(expression, "document")
    path = str(getattr(expression, "path"))
    if document == "input":
        return path
    if document == "current" and current_pointer is not None:
        return _join_pointer(current_pointer, path)
    return None


def _bounded_string_values(
    expression: Expression,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_pointer: str | None,
) -> frozenset[str] | None:
    op = getattr(expression, "op")
    if op == "literal":
        value = getattr(expression, "value")
        return frozenset({value}) if isinstance(value, str) else None
    if op == "get":
        document = getattr(expression, "document")
        path = getattr(expression, "path")
        if document == "input":
            field = source_schema.field(path)
        elif document == "output":
            field = target_schema.field(path)
        elif current_pointer is not None:
            field = source_schema.field(_join_pointer(current_pointer, path))
        else:
            field = None
        if (
            field is not None
            and field.enum_values
            and all(isinstance(value, str) for value in field.enum_values)
        ):
            return frozenset(value for value in field.enum_values if isinstance(value, str))
        return None
    if op == "if":
        then_values = _bounded_string_values(
            getattr(expression, "then"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_pointer=current_pointer,
        )
        else_values = _bounded_string_values(
            getattr(expression, "otherwise"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_pointer=current_pointer,
        )
        if then_values is not None and else_values is not None:
            return then_values | else_values
    return None


def _collection_item_context(
    expression: Expression,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_types: tuple[ExpressionType, ...],
    current_pointer: str | None,
) -> tuple[ExpressionType, str | None]:
    pointer = _get_pointer(expression, current_pointer)
    if pointer is not None:
        collection = source_schema.field(pointer)
        item_pointer = pointer.rstrip("/") + "/items"
        item = source_schema.field(item_pointer)
        if collection is None or JsonType.ARRAY not in collection.types:
            return frozenset(), None
        return (
            item.types if item is not None else collection.item_types,
            item_pointer if item is not None else None,
        )
    if getattr(expression, "op") == "array":
        item_types: set[JsonType] = set()
        for item in getattr(expression, "items"):
            item_types.update(
                infer_expression_type(
                    item,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    current_types=current_types,
                    current_pointer=current_pointer,
                )
            )
        return frozenset(item_types), None
    return frozenset(), None


def infer_expression_type(
    expression: Expression,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_types: tuple[ExpressionType, ...],
    current_pointer: str | None = None,
) -> ExpressionType:
    op = getattr(expression, "op")
    if op == "literal":
        return _value_types(getattr(expression, "value"))
    if op == "get":
        document = getattr(expression, "document")
        path = getattr(expression, "path")
        if document == "input":
            return _field_types(source_schema, path)
        if document == "output":
            return _field_types(target_schema, path)
        if current_types:
            current = current_types[-1]
            if path in {"", "/"}:
                return current
            if JsonType.OBJECT in current and current_pointer is not None:
                resolved = _join_pointer(current_pointer, path)
                return _field_types(source_schema, resolved, guaranteed_base=current_pointer)
            return frozenset()
        return frozenset()
    if op == "object":
        return frozenset({JsonType.OBJECT})
    if op == "array":
        return frozenset({JsonType.ARRAY})
    if op == "map":
        collection_type = infer_expression_type(
            getattr(expression, "collection"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        if JsonType.ARRAY not in collection_type:
            return frozenset()
        item_types, item_pointer = _collection_item_context(
            getattr(expression, "collection"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        if not item_types:
            return frozenset()
        mapped_type = infer_expression_type(
            getattr(expression, "expression"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types + (item_types,),
            current_pointer=item_pointer,
        )
        if not mapped_type:
            return frozenset()
        map_result = {JsonType.ARRAY}
        if JsonType.NULL in collection_type:
            map_result.add(JsonType.NULL)
        return frozenset(map_result)
    if op == "coalesce":
        result: set[JsonType] = set()
        for operand in getattr(expression, "operands"):
            operand_types = infer_expression_type(
                operand,
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=current_types,
                current_pointer=current_pointer,
            )
            result.update(operand_types)
            if JsonType.NULL not in operand_types:
                result.discard(JsonType.NULL)
                break
        return frozenset(result)
    if op == "concat":
        return frozenset({JsonType.STRING})
    if op == "cast":
        target = getattr(expression, "target_type")
        return frozenset({JsonType(target)})
    if op == "if":
        then_type = infer_expression_type(
            getattr(expression, "then"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        else_type = infer_expression_type(
            getattr(expression, "otherwise"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        return then_type | else_type
    if op in {"equals", "not", "and", "or"}:
        return frozenset({JsonType.BOOLEAN})
    if op == "lookup":
        result_set: set[JsonType] = set()
        for value in getattr(expression, "values").values():
            result_set.update(_value_types(value))
        default = getattr(expression, "default")
        if default is not None:
            result_set.update(
                infer_expression_type(
                    default,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    current_types=current_types,
                    current_pointer=current_pointer,
                )
            )
        else:
            key_type = infer_expression_type(
                getattr(expression, "key"),
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=current_types,
                current_pointer=current_pointer,
            )
            key_values = _bounded_string_values(
                getattr(expression, "key"),
                source_schema=source_schema,
                target_schema=target_schema,
                current_pointer=current_pointer,
            )
            lookup_keys = set(getattr(expression, "values"))
            if (
                JsonType.NULL in key_type
                or key_values is None
                or not key_values.issubset(lookup_keys)
            ):
                result_set.add(JsonType.NULL)
        return frozenset(result_set)
    if op in {"add", "subtract", "multiply", "divide"}:
        left = infer_expression_type(
            getattr(expression, "left"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        right = infer_expression_type(
            getattr(expression, "right"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_types=current_types,
            current_pointer=current_pointer,
        )
        if JsonType.INTEGER in left and JsonType.INTEGER in right and op != "divide":
            return frozenset({JsonType.INTEGER})
        return frozenset({JsonType.NUMBER})
    if op == "round":
        return frozenset({JsonType.NUMBER})
    if op in {"parse_date", "format_date"}:
        return frozenset({JsonType.STRING})
    return frozenset()
