"""Prompt-mode profiles used by Penguin's canonical prompt renderer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "MODE_PROFILES",
    "ModeProfile",
    "PromptMode",
    "get_mode_description",
    "get_mode_profile",
    "list_available_modes",
    "normalize_prompt_mode",
]


class PromptMode(str, Enum):
    """Supported task-oriented prompt modes."""

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


@dataclass(frozen=True)
class ModeProfile:
    """A focused prompt overlay for one kind of work."""

    name: str
    description: str
    guidance: str
    personality_level: str = "minimal"
    verbosity: str = "normal"
    reasoning_depth: str = "normal"
    completion_phrases: bool = True


MODE_PROFILES: dict[str, ModeProfile] = {
    PromptMode.DIRECT.value: ModeProfile(
        name=PromptMode.DIRECT.value,
        description="Lean default for direct, evidence-backed engineering work.",
        guidance="""## Direct work

Work directly on the request. Inspect only the context needed to make a sound
decision, then act. Keep progress updates factual and brief.""",
        reasoning_depth="fast",
    ),
    PromptMode.BENCH_MINIMAL.value: ModeProfile(
        name=PromptMode.BENCH_MINIMAL.value,
        description=(
            "Minimal compatibility mode that retains core safety and completion rules."
        ),
        guidance="""## Minimal mode

Use the smallest amount of explanation and process needed to complete the
request safely. Do not omit permission checks, verification appropriate to the
change, or truthful completion status.""",
        personality_level="none",
        verbosity="minimal",
        reasoning_depth="fast",
    ),
    PromptMode.TERSE.value: ModeProfile(
        name=PromptMode.TERSE.value,
        description="Concise responses without reducing engineering rigor.",
        guidance="""## Terse response style

Prefer short, outcome-first responses. Keep only the evidence and caveats the
user needs to make a decision.""",
        personality_level="none",
        verbosity="minimal",
        reasoning_depth="fast",
    ),
    PromptMode.EXPLAIN.value: ModeProfile(
        name=PromptMode.EXPLAIN.value,
        description="Educational mode that explains observable evidence and tradeoffs.",
        guidance="""## Explain mode

Explain decisions through observable evidence, tradeoffs, and examples when
helpful. Do not expose private chain-of-thought or simulate internal dialogue.""",
        verbosity="detailed",
    ),
    PromptMode.REVIEW.value: ModeProfile(
        name=PromptMode.REVIEW.value,
        description="Correctness, security, performance, and maintainability review.",
        guidance="""## Review mode

Review for correctness, security, performance, maintainability, and missing
verification. State each finding with location, impact, and evidence. Do not
apply changes unless the user asks for a fix.""",
        verbosity="detailed",
    ),
    PromptMode.IMPLEMENT.value: ModeProfile(
        name=PromptMode.IMPLEMENT.value,
        description=(
            "Focused implementation with root-cause fixes and risk-proportional "
            "verification."
        ),
        guidance="""## Implementation mode

Trace the affected behavior before editing. Prefer a root-cause fix over a
symptom patch, keep the change focused, and run the narrowest meaningful
verification before claiming completion.""",
    ),
    PromptMode.TEST.value: ModeProfile(
        name=PromptMode.TEST.value,
        description=(
            "Testing and validation focused on behavior, regressions, and failure "
            "paths."
        ),
        guidance="""## Test mode

Derive checks from the required behavior and its failure paths. Prefer
deterministic, focused tests first; broaden only when the changed risk warrants
it. A green command is evidence, not a substitute for checking the requirement.""",
    ),
    PromptMode.RESEARCH.value: ModeProfile(
        name=PromptMode.RESEARCH.value,
        description=(
            "Evidence-oriented investigation without arbitrary exploration quotas."
        ),
        guidance="""## Research mode

Gather enough primary evidence to answer the question or identify what remains
unknown. Cite sources when useful, distinguish fact from inference, and stop
when additional inspection would not change the decision.""",
        verbosity="detailed",
        reasoning_depth="deep",
    ),
    PromptMode.PRODUCT.value: ModeProfile(
        name=PromptMode.PRODUCT.value,
        description=(
            "User-facing product work with complete interaction states and visual "
            "validation."
        ),
        guidance="""## Product quality mode

For user-facing changes, trace the real user journey and reuse the existing
design system before adding UI primitives or state. Cover relevant loading,
empty, error, success, keyboard, and responsive states. Perform visual or
interactive verification when the surface and available tools make it useful;
do not invent UI polish outside the requested product scope.""",
        reasoning_depth="deep",
    ),
    PromptMode.RIGOROUS.value: ModeProfile(
        name=PromptMode.RIGOROUS.value,
        description=(
            "High-assurance work for durable state, trust boundaries, concurrency, "
            "and runtime behavior."
        ),
        guidance="""## Rigorous systems mode

Before changing persistence, authorization, concurrency, provider/runtime, or
destructive behavior, identify the source of truth, invariant, expected failure
path, and recovery behavior. Make any resource bound explicit, local to its
owner, and configurable when it affects user-visible work. Never introduce an
implicit task token, iteration, or wall-clock stop.""",
        reasoning_depth="deep",
    ),
    PromptMode.COMPLEXITY_REVIEW.value: ModeProfile(
        name=PromptMode.COMPLEXITY_REVIEW.value,
        description="Ponytail-inspired review that hunts unnecessary complexity only.",
        guidance="""## Complexity review mode

Review only for unnecessary complexity. For each finding, give one concise line
with location, tag (`delete`, `stdlib`, `native`, `yagni`, or `shrink`), what to
remove, and what replaces it. Do not flag safety checks, validation, error
handling, accessibility, or meaningful verification as bloat. If there is
nothing to cut, say `Lean already. Ship.`""",
        verbosity="minimal",
    ),
}


_MODE_ALIASES = {
    "lean": PromptMode.DIRECT.value,
    "pony_tail": PromptMode.COMPLEXITY_REVIEW.value,
    "ponytail": PromptMode.COMPLEXITY_REVIEW.value,
    "production": PromptMode.PRODUCT.value,
    "safety": PromptMode.RIGOROUS.value,
}


def normalize_prompt_mode(mode: str | PromptMode) -> str:
    """Return a canonical prompt mode or raise a clear configuration error."""

    raw_mode = mode.value if isinstance(mode, PromptMode) else str(mode)
    normalized = raw_mode.strip().lower().replace("-", "_")
    normalized = _MODE_ALIASES.get(normalized, normalized)
    if normalized in MODE_PROFILES:
        return normalized

    available = ", ".join(list_available_modes())
    raise ValueError(f"Unknown prompt mode {raw_mode!r}. Available modes: {available}")


def get_mode_profile(mode: str | PromptMode) -> ModeProfile:
    """Return the requested profile, falling back to the direct profile."""

    try:
        return MODE_PROFILES[normalize_prompt_mode(mode)]
    except ValueError:
        return MODE_PROFILES[PromptMode.DIRECT.value]


def list_available_modes() -> list[str]:
    """Return canonical prompt mode names suitable for configuration or CLI use."""

    return list(MODE_PROFILES)


def get_mode_description(mode: str | PromptMode) -> str:
    """Return the user-facing description for a prompt mode."""

    return get_mode_profile(mode).description
