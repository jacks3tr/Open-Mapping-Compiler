"""Open Mapping Compiler public package."""

from open_mapping.compiler import Compiler
from open_mapping.errors import OpenMappingError
from open_mapping.mapper import Mapper
from open_mapping.mapping import map_schemas
from open_mapping.model.builds import BuildResult, BuildStatus
from open_mapping.model.bundles import MappingBundle, VerificationLevel
from open_mapping.source_inference import infer_source_schema

__version__ = "0.2.0"

__all__ = [
    "Compiler",
    "BuildResult",
    "BuildStatus",
    "MappingBundle",
    "Mapper",
    "VerificationLevel",
    "OpenMappingError",
    "map_schemas",
    "infer_source_schema",
    "__version__",
]
