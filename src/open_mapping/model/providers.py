"""Provider disclosure metadata."""

from pydantic import Field

from open_mapping.model.issues import Issue
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.model_config import ContextMode, ProviderKind
from open_mapping.model.model_protocol import ModelMappingResponse


class ModelUsage(OpenMappingModel):
    """Bounded provider usage metadata, when the provider exposes it."""

    input_tokens: int | None
    output_tokens: int | None


class ProviderDisclosure(OpenMappingModel):
    endpoint_origin: str
    raw_samples_included: bool
    source_field_count: int
    candidate_count: int
    sample_profile_count: int
    redaction_count: int
    request_sha256: str


class ModelBatchRun(OpenMappingModel):
    """Validated outcome and bounded provenance for one context batch."""

    batch_id: str
    context_sha256: str
    response_sha256: str | None
    response: ModelMappingResponse | None
    issues: tuple[Issue, ...]
    attempts: int = Field(ge=0, le=2)
    format_repairs: int = Field(ge=0, le=1)
    usage: ModelUsage
    latency_ms: int = Field(ge=0)


class ModelRunDisclosure(OpenMappingModel):
    """Provider-neutral provenance for one ordered model-assisted run."""

    model_alias: str
    provider_name: str
    provider_kind: ProviderKind
    model_id: str
    prompt_version: str
    config_sha256: str
    context_mode: ContextMode
    raw_samples_included: bool
    redaction_count: int = Field(ge=0)
    batch_runs: tuple[ModelBatchRun, ...]


__all__ = [
    "ModelBatchRun",
    "ModelRunDisclosure",
    "ModelUsage",
    "ProviderDisclosure",
]
