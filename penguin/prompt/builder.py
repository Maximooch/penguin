"""Canonical, mode-aware system-prompt renderer for Penguin.

The prompt deliberately contains only durable behavioral policy. Tool schemas
come from the active provider/runtime and detailed workflows remain on-demand
references rather than permanent per-turn context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from penguin.prompt.profiles import (
    PromptPreset,
    get_quality_overlay,
    get_work_mode_profile,
    normalize_quality_overlays,
    normalize_work_mode,
    resolve_prompt_preset,
)
from penguin.prompt.soul import (
    MINIMAL_PENGUIN_SOUL,
    PENGUIN_SOUL,
    get_personality_section,
    normalize_personality_profile,
)
from penguin.prompt_actions import get_runtime_tool_protocol

__all__ = [
    "CORE_ENGINEERING_DISCIPLINE",
    "CORE_IDENTITY",
    "GIT_ATTRIBUTION_GUIDANCE",
    "OPERATING_CONTRACT",
    "PENGUIN_SOUL",
    "RUNTIME_CONTRACT",
    "VOICE_AND_COUNSEL",
    "PromptBuilder",
    "build_system_prompt",
    "get_builder",
    "list_output_styles",
    "set_output_formatting",
    "set_permission_context_from_config",
]


# Deprecated section names retained for integrations importing them directly.
CORE_IDENTITY = MINIMAL_PENGUIN_SOUL
VOICE_AND_COUNSEL = PENGUIN_SOUL


CORE_ENGINEERING_DISCIPLINE = """## Engineering discipline

Understand the affected flow, its callers, and relevant boundary conditions
before choosing a solution. Optimize for the smallest excellent change, not the
smallest diff, fastest apparent completion, or largest architecture.

Use this decision ladder:
1. Confirm that a change is needed.
2. Reuse an existing project pattern or capability.
3. Use the language standard library or native platform feature.
4. Use an already-installed dependency.
5. Write the minimum code that satisfies the real requirement.

Prefer root-cause fixes over symptom patches. Do not add a dependency, store,
configuration surface, abstraction, or delegation unless its concrete benefit
outweighs its maintenance cost.

Simplicity never permits cutting data integrity, security, permissions, error
handling, accessibility, durability, performance reasoning for relevant hot or
critical paths, or required user-visible states. Verify the changed property
with the narrowest meaningful check, then broaden validation when risk warrants
it."""


OPERATING_CONTRACT = """## Operating contract

Follow user instructions, repository guidance, and runtime permission policy.
Use only tools and capabilities actually available in the current session.

Do not invent a deadline, token budget, iteration cap, or wall-clock stop. An
explicitly configured limit is a real contract; otherwise continue until the
objective is complete, the user interrupts, required input is missing, or a
genuine external/runtime failure occurs. Do not describe a provider failure as
task completion.

Persist progress only when it must survive interruption or materially helps the
user. Do not create planning files, documentation, commits, branches, or
checkpoints merely as ceremony. Call `finish_task` only when the stated
acceptance evidence supports `done`; otherwise use truthful partial or blocked
status."""


RUNTIME_CONTRACT = OPERATING_CONTRACT


SKILL_AND_DELEGATION_GUIDANCE = """## Skills and delegation

Use a named or clearly relevant skill only after loading its instructions. Work
directly by default. Delegate only when a bounded, independent subproblem has a
clear owner and parallel work materially improves the outcome or latency; never
delegate merely to create activity or collect duplicate opinions."""


GIT_ATTRIBUTION_GUIDANCE = """## Git attribution

When you create a Git commit for work you performed, include this trailer in
the commit message:

```
Co-authored-by: penguin-agent[bot] <penguin-agent[bot]@users.noreply.github.com>
```

This is an attribution convention, not permission to create, amend, push, or
rewrite commits. Preserve existing trailers and do not alter user-authored
commits merely to add attribution."""


_OUTPUT_STYLE_GUIDANCE = {
    "steps_final": """## Response style

Keep progress updates concrete and brief. Lead the final response with the
outcome, then provide verification and material caveats. For non-trivial work,
make the quality trace legible: what changed, what was reused or avoided, what
was verified, and any remaining limitation—omitting headings that add no value.""",
    "plain": """## Response style

Use concise prose. State the outcome, evidence, and any material caveat without
process narration or simulated internal dialogue.""",
    "json_guided": """## Response style

Use clear, structured output when the user asks for machine-readable results.
Otherwise lead with the outcome, evidence, and material caveats. Do not expose
private chain-of-thought.""",
    "explanatory": """## Response style

Explain the answer in cohesive prose at the user's apparent level. Lead with
the conclusion, then provide the reasoning, examples, and tradeoffs needed to
make it understandable and actionable.""",
}


def _normalize_output_style(style: str | None) -> str:
    """Return a supported output-style name with a safe default."""

    normalized = str(style).strip().lower() if style is not None else ""
    return normalized if normalized in _OUTPUT_STYLE_GUIDANCE else "steps_final"


def list_output_styles() -> list[str]:
    """Return response styles suitable for configuration or a selector."""

    return list(_OUTPUT_STYLE_GUIDANCE)


@dataclass
class PromptBuilder:
    """Compose orthogonal prompt layers into one deterministic system prompt."""

    output_style: str = "steps_final"
    personality_profile: str = "penguin"
    personality_overlay: str = ""
    quality_overlays: tuple[str, ...] = ()
    permission_section: str = ""
    _legacy_components: dict[str, Any] = field(default_factory=dict)

    def load_components(self, **kwargs: Any) -> None:
        """Retain legacy caller inputs without making them active prompt policy.

        Older integrations imported this builder and populated an expansive set
        of sections. The canonical renderer intentionally ignores those static
        guides so one legacy caller cannot silently restore the monolith.
        """

        self._legacy_components = dict(kwargs)

    def set_permission_context(
        self,
        *,
        mode: str = "workspace",
        enabled: bool = True,
        workspace_root: str | None = None,
        project_root: str | None = None,
        allowed_paths: list[str] | None = None,
        denied_paths: list[str] | None = None,
        require_approval: list[str] | None = None,
    ) -> None:
        """Record a concise permission reminder for compatibility callers."""

        del workspace_root, project_root, allowed_paths, denied_paths, require_approval
        if not enabled:
            self.permission_section = ""
            return
        self.permission_section = (
            "## Permissions\n"
            f"The active permission mode is `{mode}`. Honor runtime allow, ask, and "
            "deny decisions; do not bypass them through another tool or path."
        )

    def set_output_style(self, style: str) -> None:
        """Set the response-style overlay used by future rendered prompts."""

        self.output_style = _normalize_output_style(style)

    def set_personality(self, profile: str, *, overlay: str = "") -> None:
        """Set the built-in Soul profile and optional user-owned preferences."""

        self.personality_profile = normalize_personality_profile(profile)
        self.personality_overlay = str(overlay).strip()

    def set_quality_overlays(self, overlays: list[str] | tuple[str, ...]) -> None:
        """Set optional quality disciplines without changing task intent."""

        self.quality_overlays = normalize_quality_overlays(overlays)

    def build(
        self,
        mode: str = "direct",
        *,
        work_mode: str | None = None,
        output_style: str | None = None,
        personality_profile: str | None = None,
        personality_overlay: str | None = None,
        quality_overlays: list[str] | tuple[str, ...] | None = None,
        git_attribution_prompt: bool = True,
        **_kwargs: Any,
    ) -> str:
        """Build a deterministic prompt for one supported mode."""

        preset = self._resolve_preset(mode=mode, work_mode=work_mode)
        profile = get_work_mode_profile(preset.work_mode)
        selected_output_style = _normalize_output_style(
            output_style or preset.output_style or self.output_style
        )
        selected_personality = normalize_personality_profile(
            personality_profile
            or preset.personality_profile
            or self.personality_profile
        )
        selected_personality_overlay = (
            self.personality_overlay
            if personality_overlay is None
            else str(personality_overlay).strip()
        )
        selected_quality_overlays = normalize_quality_overlays(
            (
                *self.quality_overlays,
                *preset.quality_overlays,
                *(quality_overlays or ()),
            )
        )
        sections = [
            get_personality_section(
                selected_personality,
                overlay=selected_personality_overlay,
            ),
            CORE_ENGINEERING_DISCIPLINE,
            OPERATING_CONTRACT,
            SKILL_AND_DELEGATION_GUIDANCE,
        ]
        if self.permission_section:
            sections.append(self.permission_section)
        if git_attribution_prompt:
            sections.append(GIT_ATTRIBUTION_GUIDANCE)
        sections.extend(
            [
                profile.guidance,
                *(
                    get_quality_overlay(name).guidance
                    for name in selected_quality_overlays
                ),
                _OUTPUT_STYLE_GUIDANCE[selected_output_style],
                get_runtime_tool_protocol(),
            ]
        )
        return "\n\n".join(section.strip() for section in sections if section.strip())

    @staticmethod
    def _resolve_preset(*, mode: str, work_mode: str | None) -> PromptPreset:
        """Resolve legacy presets unless an explicit work mode was supplied."""

        if work_mode is not None:
            return PromptPreset(work_mode=normalize_work_mode(work_mode))
        return resolve_prompt_preset(mode)


_builder = PromptBuilder()


def get_builder() -> PromptBuilder:
    """Return the process-local canonical prompt builder."""

    return _builder


def build_system_prompt(
    mode: str = "direct",
    *,
    work_mode: str | None = None,
    output_style: str | None = None,
    personality_profile: str | None = None,
    personality_overlay: str | None = None,
    quality_overlays: list[str] | tuple[str, ...] | None = None,
    git_attribution_prompt: bool = True,
    **kwargs: Any,
) -> str:
    """Render a system prompt for a supported task mode."""

    return _builder.build(
        mode=mode,
        work_mode=work_mode,
        output_style=output_style,
        personality_profile=personality_profile,
        personality_overlay=personality_overlay,
        quality_overlays=quality_overlays,
        git_attribution_prompt=git_attribution_prompt,
        **kwargs,
    )


def set_output_formatting(style: str = "steps_final") -> None:
    """Compatibility entry point used by runtime output-style settings."""

    _builder.set_output_style(style)


def set_permission_context_from_config() -> None:
    """Load a concise permission reminder from configuration when available."""

    try:
        from penguin.config import load_config

        config_data = load_config()
        security = (
            config_data.get("security", {}) if isinstance(config_data, dict) else {}
        )
        _builder.set_permission_context(
            mode=str(security.get("mode", "workspace")),
            enabled=bool(security.get("enabled", True)),
            allowed_paths=list(security.get("allowed_paths") or []),
            denied_paths=list(security.get("denied_paths") or []),
            require_approval=list(security.get("require_approval") or []),
        )
    except Exception:
        _builder.permission_section = ""
