"""A per-request reasoning override is restored on the config it changed (SM-36)."""

from __future__ import annotations

from types import SimpleNamespace

from penguin.web import routes


def _config(effort: str) -> SimpleNamespace:
    return SimpleNamespace(
        model="m",
        reasoning_enabled=True,
        reasoning_effort=effort,
        reasoning_max_tokens=None,
        reasoning_exclude=False,
    )


def test_restore_leaves_the_global_config_alone() -> None:
    core = SimpleNamespace(model_config=_config("low"))
    request_config = _config("medium")

    snapshot = routes._apply_reasoning_variant_override(
        core, "high", model_config=request_config
    )
    routes._restore_reasoning_variant_override(core, snapshot)

    assert core.model_config.reasoning_effort == "low"
    assert request_config.reasoning_effort == "medium"


def test_restore_still_targets_the_global_config_when_it_was_overridden() -> None:
    core = SimpleNamespace(model_config=_config("low"))

    snapshot = routes._apply_reasoning_variant_override(core, "high")
    assert core.model_config.reasoning_effort == "high"
    routes._restore_reasoning_variant_override(core, snapshot)

    assert core.model_config.reasoning_effort == "low"
