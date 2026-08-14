"""Safe YAML loading that rejects duplicate keys and arbitrary objects."""

from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from open_mapping.model.json_types import JsonValue


class DuplicateKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: DuplicateKeySafeLoader, node: MappingNode, deep: bool = False
) -> dict[str, Any]:
    loader.flatten_mapping(node)
    keys: set[str] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping keys must be strings",
                key_node.start_mark,
            )
        if key in keys:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        keys.add(key)
    return dict(loader.construct_pairs(node, deep=deep))


DuplicateKeySafeLoader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)
DuplicateKeySafeLoader.add_constructor("tag:yaml.org,2002:omap", _construct_mapping)


def load_safe_yaml(content: str) -> JsonValue:
    value = yaml.load(content, Loader=DuplicateKeySafeLoader)
    return (
        value if isinstance(value, (dict, list, str, int, float, bool)) or value is None else value
    )
