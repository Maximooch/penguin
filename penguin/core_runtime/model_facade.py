"""Model-management compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import Any

from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig, fetch_model_specs

from . import model_runtime as core_model_runtime

__all__ = ["ModelCoreFacade"]

logger = logging.getLogger("penguin.core")


class ModelCoreFacade:
    """Compatibility methods for model/provider runtime management."""

    def _ensure_litellm_configured(self) -> None:
        """Configure LiteLLM on first use when the optional extra is installed."""
        core_model_runtime.ensure_litellm_runtime_state(self, log=logger)

    def set_llm_config(
        self,
        base_url: str | None = None,
        link_user_id: str | None = None,
        link_session_id: str | None = None,
        link_agent_id: str | None = None,
        link_workspace_id: str | None = None,
        link_api_key: str | None = None,
    ) -> dict[str, Any]:
        """Configure LLM endpoint and Link integration at runtime."""
        return core_model_runtime.configure_llm_client(
            self,
            base_url=base_url,
            link_user_id=link_user_id,
            link_session_id=link_session_id,
            link_agent_id=link_agent_id,
            link_workspace_id=link_workspace_id,
            link_api_key=link_api_key,
        )

    def refresh_api_client(self) -> None:
        """Recreate the active API client using the current model config."""
        core_model_runtime.refresh_api_client(
            self,
            api_client_factory=APIClient,
            log=logger,
        )

    def _apply_new_model_config(
        self,
        new_model_config: ModelConfig,
        context_window_tokens: int | None = None,
    ) -> None:
        """Swap model configuration and rewire dependent runtime components."""
        core_model_runtime.apply_new_model_config(
            self,
            new_model_config,
            context_window_tokens=context_window_tokens,
            refresh_active_client=self.refresh_api_client,
            log=logger,
        )

    async def _build_model_config_for_model(
        self,
        model_id: str,
    ) -> tuple[ModelConfig, int | None]:
        """Resolve a runtime model id into a concrete ModelConfig."""
        return await core_model_runtime.build_model_config_for_model(
            model_id,
            model_configs=getattr(self.config, "model_configs", None),
            current_model_config=getattr(self, "model_config", None),
            fetch_specs=fetch_model_specs,
            resolve_provider=self._resolve_model_provider,
        )

    async def resolve_request_runtime(
        self,
        model_id: str | None = None,
    ) -> tuple[ModelConfig, APIClient]:
        """Build a request-scoped model config and API client."""
        return await core_model_runtime.resolve_request_runtime(
            self,
            model_id,
            api_client_factory=APIClient,
        )

    async def load_model(self, model_id: str) -> bool:
        """Replace the active model at runtime."""
        return await core_model_runtime.load_model_for_core(
            self,
            model_id,
            log=logger,
        )

    def _canonicalize_runtime_model_id(
        self,
        model_id: str,
        provider: str,
        client_preference: str,
    ) -> str:
        """Canonicalize model IDs into provider-local form for runtime adapters."""
        return core_model_runtime.canonicalize_runtime_model_id(
            model_id,
            provider,
            client_preference,
        )

    def _resolve_model_provider(self, model_id: str) -> tuple[str | None, str]:
        """Resolve provider and client preference for a model ID."""
        return core_model_runtime.resolve_model_provider(
            model_id,
            getattr(self.config, "model_configs", None),
            current_client_preference=(
                self.model_config.client_preference if self.model_config else None
            ),
        )

    def list_available_models(self) -> list[dict[str, Any]]:
        """Return model metadata derived from ``config.yml``."""
        current_model_name = self.model_config.model if self.model_config else None
        return core_model_runtime.list_available_models(
            getattr(self.config, "model_configs", None),
            current_model_name=current_model_name,
        )

    def get_current_model(self) -> dict[str, Any] | None:
        """Get information about the currently loaded model."""
        if not self.model_config:
            return None

        return core_model_runtime.current_model_payload(self.model_config)
