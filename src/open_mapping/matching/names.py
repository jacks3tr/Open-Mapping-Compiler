"""Deterministic field-name normalization."""

from __future__ import annotations

import re
import unicodedata

_ABBREVIATIONS = {
    "acct": "account",
    "amt": "amount",
    "cd": "code",
    "ctrl": "control",
    "curr": "currency",
    "desc": "description",
    "dim": "dimension",
    "id": "identifier",
    "identifier": "identifier",
    "len": "length",
    "loc": "location",
    "lvl": "level",
    "mat": "material",
    "mfg": "manufacturing",
    "nbr": "number",
    "nm": "name",
    "no": "number",
    "num": "number",
    "number": "number",
    "org": "organization",
    "pct": "percent",
    "prod": "production",
    "qty": "quantity",
    "quantity": "quantity",
    "ref": "reference",
    "rev": "revision",
    "seq": "sequence",
    "std": "standard",
    "tel": "telephone",
    "txt": "text",
    "uom": "unit",
    "unit": "unit",
    "val": "value",
    "wh": "warehouse",
    "wt": "weight",
    "dt": "date",
    "date": "date",
    "ts": "timestamp",
    "timestamp": "timestamp",
    "addr": "address",
    "address": "address",
}

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEPARATORS = re.compile(r"[\s_\-/]+")


def name_tokens(name: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", name)
    split = _SEPARATORS.split(_CAMEL_SPLIT.sub(" ", normalized))
    result: list[str] = []
    for token in split:
        lowered = token.casefold()
        if not lowered:
            continue
        result.append(_ABBREVIATIONS.get(lowered, lowered))
    return tuple(result)


def canonical_name(name: str) -> tuple[str, ...]:
    return tuple(sorted(name_tokens(name)))


def normalized_name_text(name: str) -> str:
    return " ".join(name_tokens(name))
