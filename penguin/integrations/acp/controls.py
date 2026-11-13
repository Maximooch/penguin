"""ACP controls backed by existing request-scoped Penguin runtime APIs."""

from __future__ import annotations

from typing import Any

from acp import RequestError
from acp.schema import (
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionMode,
    SessionModeState,
)

__all__ = ["SessionControls"]


class SessionControls:
    def __init__(self, core: Any) -> None:
        self.core = core

    @property
    def supports_plan(self) -> bool:
        return bool(
            getattr(
                getattr(self.core, "tool_manager", None), "_permission_enabled", False
            )
        )

    def modes(self, current: str) -> SessionModeState:
        return SessionModeState(
            current_mode_id=current,
            available_modes=[
                SessionMode(
                    id="build", name="Build", description="Use normal tool permissions."
                ),
                *(
                    [
                        SessionMode(
                            id="plan",
                            name="Plan",
                            description="Read-only planning; no mutating tools.",
                        )
                    ]
                    if self.supports_plan
                    else []
                ),
            ],
        )

    def options(self, model_id: str) -> list[SessionConfigOptionSelect]:
        if not callable(getattr(self.core, "resolve_request_runtime", None)):
            return []
        models = self.core.list_available_models()
        choices = [
            SessionConfigSelectOption(value="default", name="Configured default")
        ]
        choices.extend(
            SessionConfigSelectOption(
                value=item["id"], name=str(item.get("name") or item["id"])
            )
            for item in models
            if item.get("id") and item["id"] != "default"
        )
        return [
            SessionConfigOptionSelect(
                id="model",
                name="Model",
                category="model",
                type="select",
                current_value=model_id,
                options=choices,
            )
        ]

    async def resolve(self, model_id: str) -> tuple[Any, Any]:
        options = self.options(model_id)
        if not options or model_id not in {
            option.value for option in options[0].options
        }:
            raise RequestError.invalid_params({"reason": "Unknown configured model"})
        if model_id == "default":
            return None, None
        try:
            return await self.core.resolve_request_runtime(model_id)
        except (ValueError, RuntimeError):
            raise RequestError.invalid_params(
                {"reason": "Model is unavailable; configure its provider in Penguin"}
            ) from None
