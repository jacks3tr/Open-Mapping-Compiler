"""Canonical, tamper-evident mapping bundle serialization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, NoReturn

from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.bundles import (
    BundleProvenance,
    BundleVerification,
    MappingBundle,
)
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.serialization.canonical_json import canonical_json, canonical_json_bytes
from open_mapping.serialization.mappings import mapping_sha256

_COMPONENT = "serialization.bundles"


def _issue(code: IssueCode, message: str, correction: str) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component=_COMPONENT,
        message=message,
        correction=correction,
    )


def _raise(code: IssueCode, message: str, correction: str) -> NoReturn:
    raise OpenMappingError((_issue(code, message, correction),))


def _schema_sha256(schema: SchemaDocument) -> str:
    return hashlib.sha256(canonical_json_bytes(schema.model_dump(mode="json"))).hexdigest()


def _validate_schema_locations(schema: SchemaDocument) -> None:
    for field in schema.fields:
        location = field.source_location.split(" -> ", 1)[0].split("#", 1)[0]
        if PureWindowsPath(location).is_absolute() or PurePosixPath(location).is_absolute():
            _raise(
                IssueCode.INVALID_INPUT,
                "mapping bundle contains a machine-specific absolute schema location",
                "Load schemas through Compiler paths or use portable source locations.",
            )


def _validate_compiler_version(version: str) -> None:
    from open_mapping import __version__

    try:
        bundle_major = int(version.split(".", 1)[0])
        current_major = int(__version__.split(".", 1)[0])
    except ValueError:
        _raise(
            IssueCode.UNSUPPORTED_BUNDLE_VERSION,
            f"bundle compiler version {version!r} is invalid",
            "Rebuild the bundle with a released Open Mapping Compiler version.",
        )
    if bundle_major > current_major:
        _raise(
            IssueCode.UNSUPPORTED_BUNDLE_VERSION,
            f"bundle requires incompatible compiler version {version!r}",
            f"Upgrade Open Mapping Compiler beyond {__version__} or rebuild the bundle with this version.",
        )


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r} is not allowed")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def create_bundle(
    *,
    mapping: MappingDocument,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    verification: BundleVerification,
    provenance: BundleProvenance,
) -> MappingBundle:
    """Create a bundle with hashes derived from its embedded content."""

    from open_mapping import __version__

    resolved_mapping_sha = mapping_sha256(mapping)
    bundle = MappingBundle(
        bundle_version="0.1",
        compiler_version=__version__,
        mapping=mapping,
        source_schema=source_schema,
        target_schema=target_schema,
        mapping_sha256=resolved_mapping_sha,
        source_schema_sha256=_schema_sha256(source_schema),
        target_schema_sha256=_schema_sha256(target_schema),
        verification=verification.model_copy(update={"mapping_sha256": resolved_mapping_sha}),
        provenance=provenance,
    )
    validate_bundle(bundle)
    return bundle


def bundle_sha256(bundle: MappingBundle) -> str:
    validate_bundle(bundle)
    return hashlib.sha256(canonical_json_bytes(bundle.model_dump(mode="json"))).hexdigest()


def dumps_bundle(bundle: MappingBundle) -> str:
    validate_bundle(bundle)
    return canonical_json(bundle.model_dump(mode="json")) + "\n"


def dump_bundle(bundle: MappingBundle, path: Path) -> None:
    path.write_text(dumps_bundle(bundle), encoding="utf-8", newline="\n")


def loads_bundle(content: str) -> MappingBundle:
    try:
        raw: JsonValue = json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError, ValueError):
        _raise(
            IssueCode.INVALID_INPUT,
            "invalid mapping bundle JSON",
            "Use canonical JSON without duplicate keys or non-finite numbers.",
        )
    if isinstance(raw, dict) and raw.get("bundle_version") != "0.1":
        _raise(
            IssueCode.UNSUPPORTED_BUNDLE_VERSION,
            f"unsupported bundle version {raw.get('bundle_version')!r}",
            "Rebuild the bundle with a compatible Open Mapping Compiler version.",
        )
    raw_verification = raw.get("verification") if isinstance(raw, dict) else None
    if isinstance(raw_verification, dict) and raw_verification.get("valid") is not True:
        _raise(
            IssueCode.BUNDLE_NOT_VERIFIED,
            "mapping bundle is not verified",
            "Rebuild the bundle after successful verification.",
        )
    try:
        bundle = MappingBundle.model_validate(raw)
    except ValidationError:
        _raise(
            IssueCode.INVALID_INPUT,
            "mapping bundle structure is invalid",
            "Rebuild the bundle from validated schemas and mapping rules.",
        )
    validate_bundle(bundle)
    return bundle


def load_bundle(path: Path) -> MappingBundle:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _raise(
            IssueCode.INVALID_INPUT,
            f"could not read mapping bundle {path.name!r}",
            "Provide a readable UTF-8 .omc file.",
        )
    return loads_bundle(content)


def validate_bundle(bundle: MappingBundle) -> None:
    _validate_compiler_version(bundle.compiler_version)
    _validate_schema_locations(bundle.source_schema)
    _validate_schema_locations(bundle.target_schema)
    if not bundle.verification.valid:
        _raise(
            IssueCode.BUNDLE_NOT_VERIFIED,
            "mapping bundle is not verified",
            "Rebuild the bundle after successful verification.",
        )
    expected = {
        "mapping": mapping_sha256(bundle.mapping),
        "source schema": _schema_sha256(bundle.source_schema),
        "target schema": _schema_sha256(bundle.target_schema),
    }
    actual = {
        "mapping": bundle.mapping_sha256,
        "source schema": bundle.source_schema_sha256,
        "target schema": bundle.target_schema_sha256,
    }
    for label in expected:
        if expected[label] != actual[label]:
            _raise(
                IssueCode.BUNDLE_HASH_MISMATCH,
                f"{label} hash does not match embedded content",
                "Discard this bundle and rebuild it from trusted inputs.",
            )
    if bundle.verification.mapping_sha256 != bundle.mapping_sha256:
        _raise(
            IssueCode.BUNDLE_HASH_MISMATCH,
            "verification mapping hash does not match the embedded mapping",
            "Discard this bundle and rebuild it from trusted inputs.",
        )


__all__ = [
    "bundle_sha256",
    "create_bundle",
    "dump_bundle",
    "dumps_bundle",
    "load_bundle",
    "loads_bundle",
    "validate_bundle",
]
