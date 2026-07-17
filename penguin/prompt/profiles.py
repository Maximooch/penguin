"""Work-mode presets and orthogonal quality overlays for prompt composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Literal

__all__ = [
    "LEGACY_PROMPT_PRESETS",
    "MODE_PROFILES",
    "QUALITY_OVERLAYS",
    "WORK_MODE_PROFILES",
    "CapabilityProfile",
    "ModeProfile",
    "PromptMode",
    "PromptPreset",
    "QualityOverlay",
    "QualityOverlayProfile",
    "WorkMode",
    "WorkModeProfile",
    "get_mode_description",
    "get_mode_profile",
    "get_quality_overlay",
    "get_work_mode_description",
    "get_work_mode_profile",
    "list_available_modes",
    "list_available_work_modes",
    "list_quality_overlays",
    "normalize_prompt_mode",
    "normalize_quality_overlays",
    "normalize_work_mode",
    "resolve_prompt_preset",
]

CapabilityProfile = Literal["full", "read_only", "no_tools"]


class WorkMode(str, Enum):
    """Task intent for the current turn or session."""

    BUILD = "build"
    PLAN = "plan"
    REVIEW = "review"
    RESEARCH = "research"
    CHAT = "chat"
    TEST = "test"


class PromptMode(str, Enum):
    """Deprecated preset names retained for source compatibility."""

    DIRECT = "direct"
    BENCH_MINIMAL = "bench_minimal"
    TERSE = "terse"
    EXPLAIN = "explain"
    REVIEW = "review"
    IMPLEMENT = "implement"
    TEST = "test"
    RESEARCH = "research"
    PRODUCT = "product"
    RIGOROUS = "rigorous"
    COMPLEXITY_REVIEW = "complexity_review"


class QualityOverlay(str, Enum):
    """Optional discipline applied without changing task intent."""

    PRODUCT = "product"
    RIGOROUS = "rigorous"
    COMPLEXITY_REVIEW = "complexity_review"


@dataclass(frozen=True)
class WorkModeProfile:
    """Prompt guidance and recommended runtime capability for one work mode."""

    name: str
    description: str
    guidance: str
    capability_profile: CapabilityProfile
    user_visible: bool = True


@dataclass(frozen=True)
class QualityOverlayProfile:
    """Focused quality policy that composes with a work mode."""

    name: str
    description: str
    guidance: str


@dataclass(frozen=True)
class PromptPreset:
    """Compatibility mapping from an old prompt mode to orthogonal settings."""

    work_mode: str
    output_style: str | None = None
    personality_profile: str | None = None
    quality_overlays: tuple[str, ...] = ()


WORK_MODE_PROFILES: dict[str, WorkModeProfile] = {
    WorkMode.BUILD.value: WorkModeProfile(
        name=WorkMode.BUILD.value,
        description="Implement and verify changes in the user's workspace.",
        capability_profile="full",
        guidance="""## Build mode

Trace the affected behavior before editing. Prefer a root-cause fix, keep the
change focused, and run risk-proportional verification before claiming
completion.""",
    ),
    WorkMode.PLAN.value: WorkModeProfile(
        name=WorkMode.PLAN.value,
        description="Develop an actionable plan without changing the workspace.",
        capability_profile="read_only",
        guidance="""## Plan mode

Understand the relevant system and decisions before proposing work. Produce a
specific, ordered plan with dependencies, risks, and acceptance evidence. Do
not implement changes unless the user asks to move from planning to building.""",
    ),
    WorkMode.REVIEW.value: WorkModeProfile(
        name=WorkMode.REVIEW.value,
        description="Review existing work without applying fixes.",
        capability_profile="read_only",
        guidance="""## Review mode

Review for correctness, security, performance, maintainability, and missing
verification. State each actionable finding with location, impact, and
evidence. Do not apply changes unless the user asks for a fix.""",
    ),
    WorkMode.RESEARCH.value: WorkModeProfile(
        name=WorkMode.RESEARCH.value,
        description="Investigate and synthesize primary evidence.",
        capability_profile="read_only",
        guidance="""## Research mode

Gather enough primary evidence to answer the question or identify what remains
unknown. Cite sources when useful, distinguish fact from inference, and stop
when additional inspection would not change the decision.""",
    ),
    WorkMode.CHAT.value: WorkModeProfile(
        name=WorkMode.CHAT.value,
        description="Discuss, explain, and advise without taking actions.",
        capability_profile="no_tools",
        guidance="""## Chat mode

Respond directly from the available conversation. Explain, advise, or clarify
without claiming to inspect files, call tools, or change external state.""",
    ),
    WorkMode.TEST.value: WorkModeProfile(
        name=WorkMode.TEST.value,
        description="Design and run focused behavioral verification.",
        capability_profile="full",
        user_visible=False,
        guidance="""## Test mode

Derive checks from required behavior and failure paths. Prefer deterministic,
focused tests first; broaden only when risk warrants it. A green command is
evidence, not a substitute for checking the requirement.""",
    ),
}


QUALITY_OVERLAYS: dict[str, QualityOverlayProfile] = {
    QualityOverlay.PRODUCT.value: QualityOverlayProfile(
        name=QualityOverlay.PRODUCT.value,
        description="Complete, polished user-facing product behavior.",
        guidance="""## Product quality overlay

Trace the real user journey and reuse the existing design system. Cover the
relevant loading, empty, error, success, keyboard, accessibility, and
responsive states. Perform visual or interactive verification when useful.""",
    ),
    QualityOverlay.RIGOROUS.value: QualityOverlayProfile(
        name=QualityOverlay.RIGOROUS.value,
        description="High assurance for state, trust, concurrency, and runtime work.",
        guidance="""## Rigorous systems overlay

Identify the source of truth, invariant, failure path, and recovery behavior
before changing persistence, authorization, concurrency, provider/runtime, or
destructive behavior. Make resource bounds explicit and user-configurable when
they affect user-visible work.""",
    ),
    QualityOverlay.COMPLEXITY_REVIEW.value: QualityOverlayProfile(
        name=QualityOverlay.COMPLEXITY_REVIEW.value,
        description="Ponytail-inspired review for unnecessary complexity.",
        guidance="""## Complexity review overlay

For each complexity finding, give one concise line with location, tag
(`delete`, `stdlib`, `native`, `yagni`, or `shrink`), what to remove, and what
replaces it. Do not call safety, validation, accessibility, or meaningful
verification bloat. If there is nothing to cut, say `Lean already. Ship.`""",
    ),
}


LEGACY_PROMPT_PRESETS: dict[str, PromptPreset] = {
    "direct": PromptPreset(work_mode=WorkMode.BUILD.value),
    "bench_minimal": PromptPreset(
        work_mode=WorkMode.BUILD.value,
        output_style="plain",
        personality_profile="minimal",
    ),
    "terse": PromptPreset(
        work_mode=WorkMode.BUILD.value,
        output_style="plain",
        personality_profile="minimal",
    ),
    "explain": PromptPreset(work_mode=WorkMode.CHAT.value, output_style="explanatory"),
    "implement": PromptPreset(work_mode=WorkMode.BUILD.value),
    "product": PromptPreset(
        work_mode=WorkMode.BUILD.value,
        quality_overlays=(QualityOverlay.PRODUCT.value,),
    ),
    "rigorous": PromptPreset(
        work_mode=WorkMode.BUILD.value,
        quality_overlays=(QualityOverlay.RIGOROUS.value,),
    ),
    "complexity_review": PromptPreset(
        work_mode=WorkMode.REVIEW.value,
        output_style="plain",
        quality_overlays=(QualityOverlay.COMPLEXITY_REVIEW.value,),
    ),
}

_PROMPT_PRESET_ALIASES = {
    "lean": "direct",
    "pony_tail": "complexity_review",
    "ponytail": "complexity_review",
    "production": "product",
    "safety": "rigorous",
}


def _normalize_name(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def normalize_work_mode(mode: str | WorkMode) -> str:
    """Return a canonical work-mode name."""

    raw_mode = mode.value if isinstance(mode, WorkMode) else mode
    normalized = _normalize_name(raw_mode)
    if normalized in WORK_MODE_PROFILES:
        return normalized
    available = ", ".join(list_available_work_modes(include_internal=True))
    raise ValueError(f"Unknown work mode {raw_mode!r}. Available: {available}")


def resolve_prompt_preset(value: str | WorkMode | PromptMode) -> PromptPreset:
    """Resolve a work mode or legacy prompt-mode name into explicit settings."""

    raw_value = value.value if isinstance(value, (WorkMode, PromptMode)) else value
    normalized = _normalize_name(raw_value)
    normalized = _PROMPT_PRESET_ALIASES.get(normalized, normalized)
    if normalized in WORK_MODE_PROFILES:
        return PromptPreset(work_mode=normalized)
    preset = LEGACY_PROMPT_PRESETS.get(normalized)
    if preset is not None:
        return preset
    available = ", ".join(list_available_modes())
    raise ValueError(f"Unknown prompt preset {raw_value!r}. Available: {available}")


def normalize_quality_overlays(
    values: Iterable[str | QualityOverlay],
) -> tuple[str, ...]:
    """Validate and deduplicate quality overlays while preserving order."""

    normalized: list[str] = []
    for value in values:
        raw_value = value.value if isinstance(value, QualityOverlay) else value
        name = _normalize_name(raw_value)
        if name not in QUALITY_OVERLAYS:
            available = ", ".join(QUALITY_OVERLAYS)
            raise ValueError(
                f"Unknown quality overlay {raw_value!r}. Available: {available}"
            )
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def get_work_mode_profile(mode: str | WorkMode) -> WorkModeProfile:
    """Return the profile for one canonical work mode."""

    return WORK_MODE_PROFILES[normalize_work_mode(mode)]


def get_quality_overlay(
    overlay: str | QualityOverlay,
) -> QualityOverlayProfile:
    """Return one validated quality overlay."""

    return QUALITY_OVERLAYS[normalize_quality_overlays((overlay,))[0]]


def list_available_work_modes(*, include_internal: bool = False) -> list[str]:
    """Return work modes suitable for configuration or a user-facing selector."""

    return [
        name
        for name, profile in WORK_MODE_PROFILES.items()
        if include_internal or profile.user_visible
    ]


def list_quality_overlays() -> list[str]:
    """Return optional quality disciplines suitable for a configuration UI."""

    return list(QUALITY_OVERLAYS)


def get_work_mode_description(mode: str | WorkMode) -> str:
    """Return a user-facing work-mode description."""

    return get_work_mode_profile(mode).description


# Compatibility names for integrations importing the old prompt-mode API.
ModeProfile = WorkModeProfile
MODE_PROFILES = WORK_MODE_PROFILES


def normalize_prompt_mode(mode: str | WorkMode | PromptMode) -> str:
    """Normalize an old prompt mode without discarding its preset semantics."""

    raw_mode = mode.value if isinstance(mode, (WorkMode, PromptMode)) else mode
    normalized = _normalize_name(raw_mode)
    normalized = _PROMPT_PRESET_ALIASES.get(normalized, normalized)
    resolve_prompt_preset(normalized)
    return normalized


def get_mode_profile(mode: str | WorkMode | PromptMode) -> WorkModeProfile:
    """Compatibility wrapper returning the preset's work-mode profile."""

    return get_work_mode_profile(resolve_prompt_preset(mode).work_mode)


def list_available_modes() -> list[str]:
    """Return work modes plus supported legacy preset names."""

    names = list_available_work_modes(include_internal=True)
    for name in LEGACY_PROMPT_PRESETS:
        if name not in names:
            names.append(name)
    return names


def get_mode_description(mode: str | WorkMode | PromptMode) -> str:
    """Compatibility wrapper for the resolved work-mode description."""

    return get_mode_profile(mode).description
