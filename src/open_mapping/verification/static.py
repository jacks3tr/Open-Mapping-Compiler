"""Static mapping verification."""

from __future__ import annotations

from dataclasses import dataclass

from open_mapping.errors import OpenMappingError
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonScalar
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.model.verification import StaticVerificationResult
from open_mapping.pointers import split_pointer
from open_mapping.serialization.mappings import mapping_sha256
from open_mapping.verification.type_inference import infer_expression_type

_ASSIGNABLE: dict[JsonType, set[JsonType]] = {
    JsonType.INTEGER: {JsonType.INTEGER, JsonType.NUMBER},
    JsonType.NUMBER: {JsonType.NUMBER},
    JsonType.STRING: {JsonType.STRING},
    JsonType.BOOLEAN: {JsonType.BOOLEAN},
    JsonType.OBJECT: {JsonType.OBJECT},
    JsonType.ARRAY: {JsonType.ARRAY},
    JsonType.NULL: {JsonType.NULL},
}


@dataclass(frozen=True)
class _CurrentContext:
    schema: SchemaDocument | None
    pointer: str | None
    types: frozenset[JsonType]


def _issue(
    code: IssueCode,
    message: str,
    correction: str,
    *,
    mapping_id: str | None = None,
    schema_id: str | None = None,
    rule_index: int | None = None,
    source_path: str | None = None,
    target_path: str | None = None,
    severity: Severity = Severity.ERROR,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        component="verification.static",
        message=message,
        correction=correction,
        schema_id=schema_id,
        mapping_id=mapping_id,
        rule_index=rule_index,
        source_path=source_path,
        target_path=target_path,
    )


def _descendant_fields(schema: SchemaDocument, pointer: str) -> tuple[SchemaField, ...]:
    return tuple(
        field for field in schema.fields if field.pointer.startswith(pointer.rstrip("/") + "/")
    )


def _required_mapping_pointers(schema: SchemaDocument) -> set[str]:
    result: set[str] = set()
    for field in schema.fields:
        if field.pointer == "" or not field.required:
            continue
        if "/items/" in field.pointer:
            continue
        if JsonType.ARRAY in field.types or not _descendant_fields(schema, field.pointer):
            result.add(field.pointer)
    return result


def _overlaps(left: str, right: str) -> bool:
    left_tokens = split_pointer(left)
    right_tokens = split_pointer(right)
    return (
        left_tokens[: len(right_tokens)] == right_tokens
        or right_tokens[: len(left_tokens)] == left_tokens
    )


def _literal_object_covered_fields(value: object, base_pointer: str) -> set[str]:
    if not isinstance(value, dict):
        return set()
    result: set[str] = set()
    for name, child in value.items():
        pointer = base_pointer.rstrip("/") + "/" + name.replace("~", "~0").replace("/", "~1")
        result.add(pointer)
        result.update(_literal_object_covered_fields(child, pointer))
    return result


def _intersect_covered_fields(field_sets: list[set[str]]) -> set[str]:
    if not field_sets:
        return set()
    result = field_sets[0].copy()
    for fields in field_sets[1:]:
        result.intersection_update(fields)
    return result


def _object_covered_fields(
    expression: Expression,
    base_pointer: str,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> set[str]:
    op = getattr(expression, "op", None)
    if op == "object":
        result: set[str] = set()
        for name, child in getattr(expression, "fields").items():
            pointer = base_pointer.rstrip("/") + "/" + name.replace("~", "~0").replace("/", "~1")
            result.add(pointer)
            result.update(
                _object_covered_fields(
                    child,
                    pointer,
                    source_schema=source_schema,
                    target_schema=target_schema,
                )
            )
        return result
    if op == "literal":
        return _literal_object_covered_fields(getattr(expression, "value"), base_pointer)
    if op == "if":
        branches = (getattr(expression, "then"), getattr(expression, "otherwise"))
        field_sets: list[set[str]] = []
        for branch in branches:
            branch_types = infer_expression_type(
                branch,
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=(),
            )
            if branch_types == frozenset({JsonType.NULL}):
                continue
            field_sets.append(
                _object_covered_fields(
                    branch,
                    base_pointer,
                    source_schema=source_schema,
                    target_schema=target_schema,
                )
            )
        return _intersect_covered_fields(field_sets)
    if op == "coalesce":
        field_sets = []
        for operand in getattr(expression, "operands"):
            operand_types = infer_expression_type(
                operand,
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=(),
            )
            if operand_types != frozenset({JsonType.NULL}):
                field_sets.append(
                    _object_covered_fields(
                        operand,
                        base_pointer,
                        source_schema=source_schema,
                        target_schema=target_schema,
                    )
                )
            if operand_types and JsonType.NULL not in operand_types:
                break
        return _intersect_covered_fields(field_sets)
    if op == "lookup":
        field_sets = [
            _literal_object_covered_fields(value, base_pointer)
            for value in getattr(expression, "values").values()
            if value is not None
        ]
        default = getattr(expression, "default")
        if default is not None:
            default_types = infer_expression_type(
                default,
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=(),
            )
            if default_types != frozenset({JsonType.NULL}):
                field_sets.append(
                    _object_covered_fields(
                        default,
                        base_pointer,
                        source_schema=source_schema,
                        target_schema=target_schema,
                    )
                )
        return _intersect_covered_fields(field_sets)
    return set()


def _join_pointer(base: str, path: str) -> str:
    if path in {"", "/"}:
        return base
    return base.rstrip("/") + "/" + path.lstrip("/")


def _possible_enum_values(
    expression: Expression,
    source_schema: SchemaDocument,
    current_contexts: tuple[_CurrentContext, ...],
) -> tuple[set[JsonScalar], bool]:
    op = getattr(expression, "op")
    if op == "literal":
        value = getattr(expression, "value")
        if value is None or isinstance(value, (str, int, float, bool)):
            return {value}, True
        return set(), True
    if op == "get" and getattr(expression, "document") == "input":
        field = source_schema.field(getattr(expression, "path"))
        if field is not None and field.enum_values:
            return set(field.enum_values), True
        return set(), False
    if op == "get" and getattr(expression, "document") == "current":
        if not current_contexts:
            return set(), False
        context = current_contexts[-1]
        if context.schema is None or context.pointer is None:
            return set(), False
        field = context.schema.field(_join_pointer(context.pointer, getattr(expression, "path")))
        if field is not None and field.enum_values:
            return set(field.enum_values), True
        return set(), False
    if op == "lookup":
        values = set(getattr(expression, "values").values())
        default = getattr(expression, "default")
        if default is not None:
            default_values, bounded = _possible_enum_values(
                default, source_schema, current_contexts
            )
            return values | default_values, bounded
        key_values, key_bounded = _possible_enum_values(
            getattr(expression, "key"), source_schema, current_contexts
        )
        lookup_keys = set(getattr(expression, "values"))
        if key_bounded and all(
            isinstance(value, str) and value in lookup_keys for value in key_values
        ):
            return values, True
        return values | {None}, True
    if op == "if":
        then_values, then_bounded = _possible_enum_values(
            getattr(expression, "then"), source_schema, current_contexts
        )
        else_values, else_bounded = _possible_enum_values(
            getattr(expression, "otherwise"), source_schema, current_contexts
        )
        return then_values | else_values, then_bounded and else_bounded
    return set(), False


def _collection_item_context(
    expression: Expression,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_contexts: tuple[_CurrentContext, ...],
) -> _CurrentContext:
    if getattr(expression, "op") == "get":
        document = getattr(expression, "document")
        path = getattr(expression, "path")
        schema: SchemaDocument | None
        pointer: str | None
        if document == "input":
            schema = source_schema
            pointer = path
        elif document == "output":
            schema = target_schema
            pointer = path
        elif current_contexts:
            parent = current_contexts[-1]
            schema = parent.schema
            pointer = _join_pointer(parent.pointer, path) if parent.pointer is not None else None
        else:
            schema = None
            pointer = None
        if schema is not None and pointer is not None:
            collection = schema.field(pointer)
            item_pointer = pointer.rstrip("/") + "/items"
            item = schema.field(item_pointer)
            if collection is not None and JsonType.ARRAY in collection.types:
                return _CurrentContext(
                    schema=schema,
                    pointer=item_pointer if item is not None else None,
                    types=item.types if item is not None else collection.item_types,
                )
    if getattr(expression, "op") == "array":
        item_types: set[JsonType] = set()
        for item in getattr(expression, "items"):
            item_types.update(
                infer_expression_type(
                    item,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    current_types=tuple(context.types for context in current_contexts),
                    current_pointer=(current_contexts[-1].pointer if current_contexts else None),
                )
            )
        return _CurrentContext(schema=None, pointer=None, types=frozenset(item_types))
    return _CurrentContext(schema=None, pointer=None, types=frozenset())


def _check_expression_paths(
    expression: object,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_contexts: tuple[_CurrentContext, ...],
    allow_output: bool,
    mapping_id: str,
    rule_index: int | None,
    issues: list[Issue],
) -> None:
    op = getattr(expression, "op")
    if op == "get":
        document = getattr(expression, "document")
        path = getattr(expression, "path")
        if document == "input":
            if source_schema.field(path) is None:
                issues.append(
                    _issue(
                        IssueCode.SOURCE_PATH_NOT_FOUND,
                        f"source path {path!r} does not exist",
                        "Use an existing source schema path.",
                        mapping_id=mapping_id,
                        schema_id=source_schema.schema_id,
                        rule_index=rule_index,
                        source_path=path,
                    )
                )
        elif document == "output":
            if not allow_output:
                issues.append(
                    _issue(
                        IssueCode.INVALID_EXPRESSION,
                        "mapping rules may not read the output document",
                        "Remove output reads from mapping rules.",
                        mapping_id=mapping_id,
                        rule_index=rule_index,
                        target_path=path,
                    )
                )
            elif target_schema.field(path) is None:
                issues.append(
                    _issue(
                        IssueCode.TARGET_PATH_NOT_FOUND,
                        f"output path {path!r} does not exist",
                        "Use an existing target schema path.",
                        mapping_id=mapping_id,
                        schema_id=target_schema.schema_id,
                        rule_index=rule_index,
                        target_path=path,
                    )
                )
        else:
            if not current_contexts:
                issues.append(
                    _issue(
                        IssueCode.INVALID_EXPRESSION,
                        "get(current) appears outside a map expression",
                        "Use get(current) only inside a map expression.",
                        mapping_id=mapping_id,
                        rule_index=rule_index,
                        source_path=path,
                    )
                )
            else:
                context = current_contexts[-1]
                resolved = (
                    _join_pointer(context.pointer, path) if context.pointer is not None else path
                )
                found = (
                    context.schema is not None
                    and context.pointer is not None
                    and context.schema.field(resolved) is not None
                )
                if not found:
                    issues.append(
                        _issue(
                            IssueCode.SOURCE_PATH_NOT_FOUND,
                            f"current path {path!r} does not exist in the active map item",
                            "Use an existing item path.",
                            mapping_id=mapping_id,
                            schema_id=source_schema.schema_id,
                            rule_index=rule_index,
                            source_path=resolved,
                        )
                    )
        return
    if op == "map":
        _check_expression_paths(
            getattr(expression, "collection"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_contexts=current_contexts,
            allow_output=allow_output,
            mapping_id=mapping_id,
            rule_index=rule_index,
            issues=issues,
        )
        item_context = _collection_item_context(
            getattr(expression, "collection"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_contexts=current_contexts,
        )
        _check_expression_paths(
            getattr(expression, "expression"),
            source_schema=source_schema,
            target_schema=target_schema,
            current_contexts=current_contexts + (item_context,),
            allow_output=allow_output,
            mapping_id=mapping_id,
            rule_index=rule_index,
            issues=issues,
        )
        return
    for attr in ("left", "right", "value", "condition", "then", "otherwise", "key", "default"):
        child = getattr(expression, attr, None)
        if hasattr(child, "op"):
            _check_expression_paths(
                child,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
                allow_output=allow_output,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
    for attr in ("operands", "items"):
        children = getattr(expression, attr, None)
        if isinstance(children, tuple):
            for child in children:
                if hasattr(child, "op"):
                    _check_expression_paths(
                        child,
                        source_schema=source_schema,
                        target_schema=target_schema,
                        current_contexts=current_contexts,
                        allow_output=allow_output,
                        mapping_id=mapping_id,
                        rule_index=rule_index,
                        issues=issues,
                    )
    fields = getattr(expression, "fields", None)
    if isinstance(fields, dict):
        for child in fields.values():
            _check_expression_paths(
                child,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
                allow_output=allow_output,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )


def _check_invariant_paths(
    invariant: Invariant,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    mapping_id: str,
    issues: list[Issue],
) -> None:
    if invariant.when is not None:
        _check_expression_paths(
            invariant.when,
            source_schema=source_schema,
            target_schema=target_schema,
            current_contexts=(),
            allow_output=True,
            mapping_id=mapping_id,
            rule_index=None,
            issues=issues,
        )
    _check_expression_paths(
        invariant.assertion,
        source_schema=source_schema,
        target_schema=target_schema,
        current_contexts=(),
        allow_output=True,
        mapping_id=mapping_id,
        rule_index=None,
        issues=issues,
    )


def _direct_children(schema: SchemaDocument, pointer: str) -> tuple[SchemaField, ...]:
    depth = len(split_pointer(pointer)) + 1
    return tuple(
        field
        for field in schema.fields
        if field.pointer.startswith(pointer.rstrip("/") + "/")
        and len(split_pointer(field.pointer)) == depth
    )


def _types_assignable(source_types: frozenset[JsonType], target_types: frozenset[JsonType]) -> bool:
    return bool(source_types) and all(
        source_type in _ASSIGNABLE and not _ASSIGNABLE[source_type].isdisjoint(target_types)
        for source_type in source_types
    )


def _append_required_shape_issue(
    *,
    target_path: str,
    mapping_id: str,
    target_schema: SchemaDocument,
    rule_index: int,
    issues: list[Issue],
) -> None:
    issues.append(
        _issue(
            IssueCode.REQUIRED_TARGET_UNMAPPED,
            f"required target {target_path!r} is not supplied by the array item expression",
            "Supply every required array-item field.",
            mapping_id=mapping_id,
            schema_id=target_schema.schema_id,
            rule_index=rule_index,
            target_path=target_path,
        )
    )


def _check_direct_shape(
    *,
    source_schema: SchemaDocument,
    source_pointer: str,
    target_schema: SchemaDocument,
    target_pointer: str,
    mapping_id: str,
    rule_index: int,
    issues: list[Issue],
) -> None:
    source_field = source_schema.field(source_pointer)
    target_field = target_schema.field(target_pointer)
    if source_field is None or target_field is None:
        return
    if not _types_assignable(source_field.types, target_field.types):
        issues.append(
            _issue(
                IssueCode.TYPE_MISMATCH,
                f"source shape at {source_pointer!r} is not assignable to {target_pointer!r}",
                "Use a compatible item expression or explicit conversion.",
                mapping_id=mapping_id,
                schema_id=target_schema.schema_id,
                rule_index=rule_index,
                source_path=source_pointer,
                target_path=target_pointer,
            )
        )
        return
    if JsonType.OBJECT in target_field.types:
        source_children = {
            field.pointer.rsplit("/", 1)[-1]: field
            for field in _direct_children(source_schema, source_pointer)
        }
        for target_child in _direct_children(target_schema, target_pointer):
            name = target_child.pointer.rsplit("/", 1)[-1]
            source_child = source_children.get(name)
            if source_child is None or target_child.required and not source_child.required:
                if target_child.required:
                    _append_required_shape_issue(
                        target_path=target_child.pointer,
                        mapping_id=mapping_id,
                        target_schema=target_schema,
                        rule_index=rule_index,
                        issues=issues,
                    )
                continue
            _check_direct_shape(
                source_schema=source_schema,
                source_pointer=source_child.pointer,
                target_schema=target_schema,
                target_pointer=target_child.pointer,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
    if JsonType.ARRAY in target_field.types:
        target_item = target_schema.field(target_pointer.rstrip("/") + "/items")
        source_item = source_schema.field(source_pointer.rstrip("/") + "/items")
        if target_item is not None:
            if source_item is None:
                _append_required_shape_issue(
                    target_path=target_item.pointer,
                    mapping_id=mapping_id,
                    target_schema=target_schema,
                    rule_index=rule_index,
                    issues=issues,
                )
            else:
                _check_direct_shape(
                    source_schema=source_schema,
                    source_pointer=source_item.pointer,
                    target_schema=target_schema,
                    target_pointer=target_item.pointer,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )


def _get_source_pointer(
    expression: Expression, current_contexts: tuple[_CurrentContext, ...]
) -> tuple[SchemaDocument, str] | None:
    if getattr(expression, "op") != "get":
        return None
    document = getattr(expression, "document")
    path = getattr(expression, "path")
    if document == "current" and current_contexts:
        context = current_contexts[-1]
        if context.schema is not None and context.pointer is not None:
            return context.schema, _join_pointer(context.pointer, path)
    return None


def _literal_types(value: object) -> frozenset[JsonType]:
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
    if isinstance(value, dict):
        return frozenset({JsonType.OBJECT})
    return frozenset()


def _check_literal_shape(
    value: object,
    *,
    target_pointer: str,
    target_schema: SchemaDocument,
    mapping_id: str,
    rule_index: int,
    issues: list[Issue],
) -> None:
    target_field = target_schema.field(target_pointer)
    if target_field is None:
        return
    if not _types_assignable(_literal_types(value), target_field.types):
        issues.append(
            _issue(
                IssueCode.TYPE_MISMATCH,
                f"literal shape is not assignable to target {target_pointer!r}",
                "Use a literal compatible with the nested target field.",
                mapping_id=mapping_id,
                schema_id=target_schema.schema_id,
                rule_index=rule_index,
                target_path=target_pointer,
            )
        )
        return
    if target_field.enum_values and value not in target_field.enum_values:
        issues.append(
            _issue(
                IssueCode.TYPE_MISMATCH,
                "literal value is outside the target enum",
                "Use a literal declared by the target enum.",
                mapping_id=mapping_id,
                schema_id=target_schema.schema_id,
                rule_index=rule_index,
                target_path=target_pointer,
            )
        )
    if JsonType.OBJECT in target_field.types and isinstance(value, dict):
        target_children = {
            split_pointer(field.pointer)[-1]: field
            for field in _direct_children(target_schema, target_pointer)
        }
        for name, target_child in target_children.items():
            if name not in value:
                if target_child.required:
                    _append_required_shape_issue(
                        target_path=target_child.pointer,
                        mapping_id=mapping_id,
                        target_schema=target_schema,
                        rule_index=rule_index,
                        issues=issues,
                    )
                continue
            _check_literal_shape(
                value[name],
                target_pointer=target_child.pointer,
                target_schema=target_schema,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
        for name in value.keys() - target_children.keys():
            unknown_path = target_pointer.rstrip("/") + "/" + name
            issues.append(
                _issue(
                    IssueCode.TARGET_PATH_NOT_FOUND,
                    f"literal object supplies unknown target path {unknown_path!r}",
                    "Use a field declared by the target item schema.",
                    mapping_id=mapping_id,
                    schema_id=target_schema.schema_id,
                    rule_index=rule_index,
                    target_path=unknown_path,
                )
            )
    if JsonType.ARRAY in target_field.types and isinstance(value, list):
        target_item_pointer = target_pointer.rstrip("/") + "/items"
        if target_schema.field(target_item_pointer) is not None:
            for item in value:
                _check_literal_shape(
                    item,
                    target_pointer=target_item_pointer,
                    target_schema=target_schema,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )


def _check_expression_shape(
    expression: Expression,
    *,
    target_pointer: str,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    current_contexts: tuple[_CurrentContext, ...],
    mapping_id: str,
    rule_index: int,
    issues: list[Issue],
    null_is_absent: bool = False,
) -> None:
    target_field = target_schema.field(target_pointer)
    if target_field is None:
        return
    inferred = infer_expression_type(
        expression,
        source_schema=source_schema,
        target_schema=target_schema,
        current_types=tuple(context.types for context in current_contexts),
        current_pointer=current_contexts[-1].pointer if current_contexts else None,
    )
    if null_is_absent:
        inferred = inferred - {JsonType.NULL}
        if not inferred:
            return
    if not _types_assignable(inferred, target_field.types):
        issues.append(
            _issue(
                IssueCode.TYPE_MISMATCH,
                f"expression shape is not assignable to target {target_pointer!r}",
                "Use an expression compatible with the nested target field.",
                mapping_id=mapping_id,
                schema_id=target_schema.schema_id,
                rule_index=rule_index,
                target_path=target_pointer,
            )
        )
        return
    if target_field.enum_values:
        possible, bounded = _possible_enum_values(expression, source_schema, current_contexts)
        if not bounded or not possible.issubset(set(target_field.enum_values)):
            issues.append(
                _issue(
                    IssueCode.TYPE_MISMATCH,
                    "expression output is not proven to be within the target enum",
                    "Constrain every output with a complete lookup or compatible enum.",
                    mapping_id=mapping_id,
                    schema_id=target_schema.schema_id,
                    rule_index=rule_index,
                    target_path=target_pointer,
                )
            )
    op = getattr(expression, "op")
    structural_target = not target_field.types.isdisjoint({JsonType.ARRAY, JsonType.OBJECT})
    if structural_target and op == "if":
        for branch in (getattr(expression, "then"), getattr(expression, "otherwise")):
            _check_expression_shape(
                branch,
                target_pointer=target_pointer,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
        return
    if structural_target and op == "coalesce":
        for operand in getattr(expression, "operands"):
            _check_expression_shape(
                operand,
                target_pointer=target_pointer,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
                null_is_absent=True,
            )
            operand_types = infer_expression_type(
                operand,
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=tuple(context.types for context in current_contexts),
                current_pointer=current_contexts[-1].pointer if current_contexts else None,
            )
            if operand_types and JsonType.NULL not in operand_types:
                break
        return
    if structural_target and op == "literal":
        _check_literal_shape(
            getattr(expression, "value"),
            target_pointer=target_pointer,
            target_schema=target_schema,
            mapping_id=mapping_id,
            rule_index=rule_index,
            issues=issues,
        )
        return
    if structural_target and op == "lookup":
        lookup_values = getattr(expression, "values")
        for value in lookup_values.values():
            _check_literal_shape(
                value,
                target_pointer=target_pointer,
                target_schema=target_schema,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
        default = getattr(expression, "default")
        if default is not None:
            _check_expression_shape(
                default,
                target_pointer=target_pointer,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
        elif not null_is_absent:
            key_values, key_bounded = _possible_enum_values(
                getattr(expression, "key"), source_schema, current_contexts
            )
            if not key_bounded or not all(
                isinstance(value, str) and value in lookup_values for value in key_values
            ):
                issues.append(
                    _issue(
                        IssueCode.TYPE_MISMATCH,
                        "lookup may produce null outside its declared keys",
                        "Provide an exhaustive lookup or a compatible default.",
                        mapping_id=mapping_id,
                        schema_id=target_schema.schema_id,
                        rule_index=rule_index,
                        target_path=target_pointer,
                    )
                )
        return
    if JsonType.OBJECT in target_field.types:
        if op == "object":
            fields = getattr(expression, "fields")
            target_children = {
                field.pointer.rsplit("/", 1)[-1]: field
                for field in _direct_children(target_schema, target_pointer)
            }
            for name, target_child in target_children.items():
                child = fields.get(name)
                if child is None:
                    if target_child.required:
                        _append_required_shape_issue(
                            target_path=target_child.pointer,
                            mapping_id=mapping_id,
                            target_schema=target_schema,
                            rule_index=rule_index,
                            issues=issues,
                        )
                    continue
                _check_expression_shape(
                    child,
                    target_pointer=target_child.pointer,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    current_contexts=current_contexts,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )
            for name in fields.keys() - target_children.keys():
                unknown_path = target_pointer.rstrip("/") + "/" + name
                issues.append(
                    _issue(
                        IssueCode.TARGET_PATH_NOT_FOUND,
                        f"object expression supplies unknown target path {unknown_path!r}",
                        "Use a field declared by the target item schema.",
                        mapping_id=mapping_id,
                        schema_id=target_schema.schema_id,
                        rule_index=rule_index,
                        target_path=unknown_path,
                    )
                )
        else:
            direct = _get_source_pointer(expression, current_contexts)
            if direct is not None:
                _check_direct_shape(
                    source_schema=direct[0],
                    source_pointer=direct[1],
                    target_schema=target_schema,
                    target_pointer=target_pointer,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )
    if JsonType.ARRAY in target_field.types:
        target_item_pointer = target_pointer.rstrip("/") + "/items"
        target_item = target_schema.field(target_item_pointer)
        if target_item is None:
            return
        if op == "map":
            item_context = _collection_item_context(
                getattr(expression, "collection"),
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts,
            )
            _check_expression_shape(
                getattr(expression, "expression"),
                target_pointer=target_item_pointer,
                source_schema=source_schema,
                target_schema=target_schema,
                current_contexts=current_contexts + (item_context,),
                mapping_id=mapping_id,
                rule_index=rule_index,
                issues=issues,
            )
        elif op == "array":
            for item in getattr(expression, "items"):
                _check_expression_shape(
                    item,
                    target_pointer=target_item_pointer,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    current_contexts=current_contexts,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )
        elif op == "get" and getattr(expression, "document") == "input":
            source_pointer = getattr(expression, "path")
            source_item = source_schema.field(source_pointer.rstrip("/") + "/items")
            if source_item is None:
                _append_required_shape_issue(
                    target_path=target_item_pointer,
                    mapping_id=mapping_id,
                    target_schema=target_schema,
                    rule_index=rule_index,
                    issues=issues,
                )
            else:
                _check_direct_shape(
                    source_schema=source_schema,
                    source_pointer=source_item.pointer,
                    target_schema=target_schema,
                    target_pointer=target_item_pointer,
                    mapping_id=mapping_id,
                    rule_index=rule_index,
                    issues=issues,
                )
        else:
            direct = _get_source_pointer(expression, current_contexts)
            if direct is not None:
                source_item = direct[0].field(direct[1].rstrip("/") + "/items")
                if source_item is not None:
                    _check_direct_shape(
                        source_schema=direct[0],
                        source_pointer=source_item.pointer,
                        target_schema=target_schema,
                        target_pointer=target_item_pointer,
                        mapping_id=mapping_id,
                        rule_index=rule_index,
                        issues=issues,
                    )


def _check_rule(
    rule: MappingRule,
    *,
    index: int,
    mapping: MappingDocument,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    issues: list[Issue],
) -> None:
    if target_schema.field(rule.target) is None:
        issues.append(
            _issue(
                IssueCode.TARGET_PATH_NOT_FOUND,
                f"target path {rule.target!r} does not exist",
                "Use an existing target schema path.",
                mapping_id=mapping.id,
                schema_id=target_schema.schema_id,
                rule_index=index,
                target_path=rule.target,
            )
        )
        return
    for token in split_pointer(rule.target):
        if token.isdigit():
            issues.append(
                _issue(
                    IssueCode.INVALID_INPUT,
                    "rule targets may not address numeric array indexes",
                    "Map array fields as a single unit and use map expressions.",
                    mapping_id=mapping.id,
                    rule_index=index,
                    target_path=rule.target,
                )
            )
            break
    _check_expression_paths(
        rule.expression,
        source_schema=source_schema,
        target_schema=target_schema,
        current_contexts=(),
        allow_output=False,
        mapping_id=mapping.id,
        rule_index=index,
        issues=issues,
    )
    target_field = target_schema.field(rule.target)
    if target_field is None:
        return
    inferred = infer_expression_type(
        rule.expression,
        source_schema=source_schema,
        target_schema=target_schema,
        current_types=(),
        current_pointer=None,
    )
    for inferred_type in inferred:
        if inferred_type not in _ASSIGNABLE or _ASSIGNABLE[inferred_type].isdisjoint(
            target_field.types
        ):
            issues.append(
                _issue(
                    IssueCode.TYPE_MISMATCH,
                    f"inferred type {inferred_type.value!r} is not assignable to target {rule.target!r}",
                    "Use an explicit cast or a compatible source field.",
                    mapping_id=mapping.id,
                    schema_id=target_schema.schema_id,
                    rule_index=index,
                    target_path=rule.target,
                )
            )
    if target_field.enum_values:
        possible, bounded = _possible_enum_values(rule.expression, source_schema, ())
        if not bounded or not possible.issubset(set(target_field.enum_values)):
            issues.append(
                _issue(
                    IssueCode.TYPE_MISMATCH,
                    "expression output is not proven to be within the target enum",
                    "Constrain every output with a complete lookup or compatible enum.",
                    mapping_id=mapping.id,
                    schema_id=target_schema.schema_id,
                    rule_index=index,
                    target_path=rule.target,
                )
            )
    if JsonType.ARRAY in target_field.types or JsonType.OBJECT in target_field.types:
        _check_expression_shape(
            rule.expression,
            target_pointer=rule.target,
            source_schema=source_schema,
            target_schema=target_schema,
            current_contexts=(),
            mapping_id=mapping.id,
            rule_index=index,
            issues=issues,
        )
    if getattr(rule.expression, "op", None) == "cast":
        target = getattr(rule.expression, "target_type")
        if target in {"integer", "number"}:
            source_types = infer_expression_type(
                getattr(rule.expression, "value"),
                source_schema=source_schema,
                target_schema=target_schema,
                current_types=(),
                current_pointer=None,
            )
            if JsonType.STRING in source_types or JsonType.NUMBER in source_types:
                issues.append(
                    _issue(
                        IssueCode.LOSSY_CAST,
                        "cast may lose information",
                        "Confirm source values are exact before casting.",
                        mapping_id=mapping.id,
                        rule_index=index,
                        target_path=rule.target,
                        severity=Severity.WARNING,
                    )
                )


def _sort_static_issues(issues: list[Issue]) -> tuple[Issue, ...]:
    ordered = sort_issues(issues)
    return tuple(
        sorted(
            ordered,
            key=lambda issue: (
                issue.severity.value,
                issue.code.value,
                issue.component,
                issue.mapping_id or "",
                issue.schema_id or "",
                issue.sample_id or "",
                issue.target_path or "",
                issue.source_path or "",
                issue.message,
                issue.rule_index if issue.rule_index is not None else -1,
            ),
        )
    )


def verify_proposed_rule(
    rule: MappingRule,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    _check_rule(
        rule,
        index=0,
        mapping=MappingDocument(
            mapping_version="0.1",
            id="proposed",
            source_schema=source_schema.schema_id,
            source_schema_version=source_schema.schema_version,
            target_schema=target_schema.schema_id,
            target_schema_version=target_schema.schema_version,
            rules=(rule,),
            invariants=(),
        ),
        source_schema=source_schema,
        target_schema=target_schema,
        issues=issues,
    )
    return _sort_static_issues(issues)


def verify_static(
    mapping: MappingDocument,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> StaticVerificationResult:
    issues: list[Issue] = []
    if mapping.source_schema != source_schema.schema_id:
        issues.append(
            _issue(
                IssueCode.INVALID_INPUT,
                f"mapping source schema {mapping.source_schema!r} does not match {source_schema.schema_id!r}",
                "Use the same schema pair that produced the mapping.",
                mapping_id=mapping.id,
                schema_id=source_schema.schema_id,
            )
        )
    if mapping.target_schema != target_schema.schema_id:
        issues.append(
            _issue(
                IssueCode.INVALID_INPUT,
                f"mapping target schema {mapping.target_schema!r} does not match {target_schema.schema_id!r}",
                "Use the same schema pair that produced the mapping.",
                mapping_id=mapping.id,
                schema_id=target_schema.schema_id,
            )
        )
    if mapping.source_schema_version != source_schema.schema_version:
        issues.append(
            _issue(
                IssueCode.INVALID_INPUT,
                "mapping source schema version does not match",
                "Use the same source schema version.",
                mapping_id=mapping.id,
                schema_id=source_schema.schema_id,
            )
        )
    if mapping.target_schema_version != target_schema.schema_version:
        issues.append(
            _issue(
                IssueCode.INVALID_INPUT,
                "mapping target schema version does not match",
                "Use the same target schema version.",
                mapping_id=mapping.id,
                schema_id=target_schema.schema_id,
            )
        )
    if JsonType.OBJECT not in source_schema.root_types or not set(
        source_schema.root_types
    ).issubset({JsonType.OBJECT}):
        issues.append(
            _issue(
                IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                "source schema root must be object-only in v0.1",
                "Use an object root schema.",
                mapping_id=mapping.id,
                schema_id=source_schema.schema_id,
            )
        )
    if JsonType.OBJECT not in target_schema.root_types or not set(
        target_schema.root_types
    ).issubset({JsonType.OBJECT}):
        issues.append(
            _issue(
                IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                "target schema root must be object-only in v0.1",
                "Use an object root schema.",
                mapping_id=mapping.id,
                schema_id=target_schema.schema_id,
            )
        )
    seen_targets: dict[str, int] = {}
    for index, rule in enumerate(mapping.rules):
        if rule.target in seen_targets:
            issues.append(
                _issue(
                    IssueCode.DUPLICATE_TARGET_ASSIGNMENT,
                    f"duplicate target assignment {rule.target!r}",
                    "Map each target path exactly once.",
                    mapping_id=mapping.id,
                    rule_index=index,
                    target_path=rule.target,
                )
            )
        else:
            seen_targets[rule.target] = index
        _check_rule(
            rule,
            index=index,
            mapping=mapping,
            source_schema=source_schema,
            target_schema=target_schema,
            issues=issues,
        )
    for i, left in enumerate(mapping.rules):
        for right in mapping.rules[i + 1 :]:
            if left.target != right.target and _overlaps(left.target, right.target):
                issues.append(
                    _issue(
                        IssueCode.OVERLAPPING_TARGET_ASSIGNMENT,
                        f"target paths {left.target!r} and {right.target!r} overlap",
                        "Map object containers or leaves, not both.",
                        mapping_id=mapping.id,
                        rule_index=mapping.rules.index(right),
                        target_path=right.target,
                    )
                )
    for pointer in _required_mapping_pointers(target_schema):
        covered = any(rule.target == pointer for rule in mapping.rules)
        if not covered:
            for rule in mapping.rules:
                if (
                    rule.target
                    and pointer.startswith(rule.target.rstrip("/") + "/")
                    and pointer
                    in _object_covered_fields(
                        rule.expression,
                        rule.target,
                        source_schema=source_schema,
                        target_schema=target_schema,
                    )
                ):
                    covered = True
                    break
        if not covered:
            issues.append(
                _issue(
                    IssueCode.REQUIRED_TARGET_UNMAPPED,
                    f"required target {pointer!r} is unmapped",
                    "Add a mapping rule for every required target leaf.",
                    mapping_id=mapping.id,
                    schema_id=target_schema.schema_id,
                    target_path=pointer,
                )
            )
    for invariant in mapping.invariants:
        _check_invariant_paths(
            invariant,
            source_schema=source_schema,
            target_schema=target_schema,
            mapping_id=mapping.id,
            issues=issues,
        )
    ordered = _sort_static_issues(issues)
    mapped = tuple(sorted(rule.target for rule in mapping.rules))
    return StaticVerificationResult(
        issues=ordered,
        mapped_target_paths=mapped,
        mapping_sha256=mapping_sha256(mapping),
    )


def require_static_valid(
    mapping: MappingDocument,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> StaticVerificationResult:
    result = verify_static(mapping, source_schema=source_schema, target_schema=target_schema)
    if not result.valid:
        raise OpenMappingError(result.issues)
    return result
