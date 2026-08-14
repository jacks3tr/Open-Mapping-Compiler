"""Schema inspection command."""

from __future__ import annotations

from pathlib import Path

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import SchemaFormat, require_choice, validate_input_files
from open_mapping.model.schema import SchemaDocument


def inspect_command(
    schema: Path,
    schema_format: SchemaFormat,
    selector: str | None,
) -> str:
    schema_format = require_choice(schema_format, SchemaFormat, "--schema-format")
    validate_input_files({"schema": schema})
    parsed_selector = parse_openapi_selector(selector) if selector is not None else None
    document: SchemaDocument = load_schema(
        schema,
        format_name=schema_format.value,
        selector=parsed_selector,
        schema_id=None,
    )
    lines = [
        f"Schema: {document.schema_id}",
        f"Version: {document.schema_version}",
        f"Dialect: {document.dialect}",
        "Fields",
    ]
    for field in document.fields:
        if field.pointer == "":
            continue
        details = [
            field.pointer,
            ",".join(sorted(t.value for t in field.types)),
            f"required={field.required}",
        ]
        if field.enum_values:
            details.append("enum=" + ",".join(str(value) for value in field.enum_values))
        if field.description:
            details.append("description=" + field.description)
        lines.append("\t".join(details))
    return "\n".join(lines) + "\n"
