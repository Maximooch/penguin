"""Request-scoped Link-managed inference runtime construction."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel

from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link.context import LinkInferenceContext


class LinkExecutionRequest(BaseModel):
    """Immutable execution authority supplied by Link's trusted backend."""

    workspace_id: str
    user_id: str
    session_id: str
    agent_id: str
    run_id: str
    requested_model_id: str
    execution_source: Literal["link_gateway"]
    provider_state_owner: Literal["link_managed"]
    settlement_mode: Literal["debit_link_credits"]
    allow_fallback_to_link_gateway: bool = False


def resolve_link_inference_runtime(
    core: Any,
    execution: LinkExecutionRequest,
    requested_model: str | None,
) -> tuple[ModelConfig, APIClient]:
    """Build a Link provider without mutating Penguin's shared model runtime."""

    selected = (requested_model or "").strip()
    if selected and selected != execution.requested_model_id:
        raise ValueError(
            "The requested model does not match Link's server-resolved execution."
        )

    current = getattr(core, "model_config", None)
    if not isinstance(current, ModelConfig):
        raise ValueError("Penguin has no base model configuration for this request.")

    model_config = replace(
        current,
        model=execution.requested_model_id,
        provider="link",
        client_preference="link",
        api_base=None,
        api_key=None,
        use_responses_api=True,
    )
    context = LinkInferenceContext(
        workspace_id=execution.workspace_id,
        user_id=execution.user_id,
        session_id=execution.session_id,
        agent_id=execution.agent_id,
        run_id=execution.run_id,
        requested_model_id=execution.requested_model_id,
    )
    base_url = (
        os.getenv("LINK_INFERENCE_BASE_URL")
        or os.getenv("LINK_INFERENCE_URL")
        or "http://localhost:3001/api/v1"
    ).rstrip("/")
    return model_config, APIClient(
        model_config,
        base_url=base_url,
        link_context=context,
    )


__all__ = ["LinkExecutionRequest", "resolve_link_inference_runtime"]
