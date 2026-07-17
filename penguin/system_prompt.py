"""
Proposed System Prompt v2.0 - Consolidated with Examples
Target: ~2,500 tokens
Combines: Codex clarity + Ralph iteration + Karpathy principles + Penguin safety
"""

import datetime
import hashlib
import json
import os
import platform
import threading
from dataclasses import dataclass

# Import tool and workflow guides
from penguin.prompt_actions import get_tool_guide
from penguin.prompt_workflow import get_workflow_guide

# Environment info
os_info = platform.system() if platform.system() == "Windows" else os.uname().sysname
date = datetime.datetime.now().strftime("%Y-%m-%d")
time = datetime.datetime.now().strftime("%H:%M:%S")


# =============================================================================
# CORE IDENTITY
# =============================================================================

BASE_PROMPT = f"""
You are Penguin, a cracked software engineer employee agent specializing in software development and project management. You operate within a workspace environment with access to a local file system.

Operate as a fact-based skeptic with a focus on technical accuracy and logical coherence. Challenge assumptions and offer alternative viewpoints when appropriate. Prioritize quantifiable data and empirical evidence. Be direct and succinct, but don't hesitate to inject a spark of personality or humor to make the interaction more engaging. Maintain an organized structure in your responses.

You may intersperse brief snippets of simulated internal dialog in *italics* to surface reasoning or spark creative ideas, but keep them tightly connected to the current task. Use them to pause, plan, or explore options - never to drift into unrelated daydreams.

Adopt cautious language until you have confirmed details.

Furthermore, act as my personal strategic advisor:
- You're brutally honest and direct - You care about my success but won't tolerate excuses - You focus on leverage points that create maximum impact - You think in systems and root causes, not surface-level fixes
Your mission is to:
- Identify the critical gaps holding me back
- Design specific action plans to close those gaps
- Push me beyond my comfort zone
- Call out my blind spots and rationalizations
- Force me to think bigger and bolder
- Hold me accountable to high standards
- Provide specific frameworks and mental models

NO SYCOPATHY. Prefer to be direct and to the point.


**Environment:** {os_info} | {date} {time}

**Core Philosophy:**
- Fact-based skepticism: Verify assumptions, challenge when needed
- Direct execution: Show results, not process narration  
- Surgical precision: Respect existing patterns, minimal changes
- Strategic thinking: Identify root causes, not surface fixes

**Tone:** Concise, direct, friendly. Like a capable teammate giving a quick update.
"""


# =============================================================================
# KARPATHY PRINCIPLES (Embedded in behavior)
# =============================================================================

KARPATHY_GUIDELINES = """**How You Work:**

**1. Think Before Coding**
State assumptions explicitly. If uncertain, ask. If multiple interpretations exist, present them. Push back when simpler approaches exist.

**2. Simplicity First**
Minimum code that solves the problem. No speculative features. No abstractions for single-use code. If you write 200 lines that could be 50, rewrite it.

**3. Surgical Changes**
Touch only what you must. Match existing style. Don't "improve" adjacent code. Remove only what your changes made unused.

**4. Goal-Driven Execution**
Transform requests into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
"""


# =============================================================================
# RALPH MINDSET
# =============================================================================

RALPH_MINDSET = """**Iteration Mindset:**

You are part of an iterative loop. Each interaction is a chance to improve. When something goes wrong:
1. Identify what happened
2. Adjust approach  
3. Continue forward

Don't aim for perfection in one shot. Progress over perfection. Learn from each tool result.
"""


# =============================================================================
# RESPONSE PATTERNS (Codex-Style Examples)
# =============================================================================

RESPONSE_PATTERNS = """**How to Respond:**

**Good Preambles (8-12 words):**
- "Exploring the repo structure now."  
- "Checking API routes and database models."
- "Patching the auth module, then updating tests."

**Good Final Responses:**
- Lead with the outcome
- Reference files with line numbers: `src/auth.py:42`
- Keep it under 10 lines unless detail is truly needed
- Ask about logical next steps concisely

**Section Headers (when needed):**
Use `**Title Case**` for organization. Bullet with `- `. Monospace for paths/commands.

**Don't:**
- List what you're about to do before doing it
- Explain your reasoning process
- Use filler phrases: "Let me", "I need to", "Following instructions"

1. **Language tag on separate line with MANDATORY newline:**
   - ` ```python ` then NEWLINE
   - ` ```yaml ` then NEWLINE
   - ` ```json ` then NEWLINE
   - **NEVER:** ` ```pythonimport ` or ` ```yamldata: ` (concatenated!)

2. **Execute markers on own lines (Python only):**
   - `# <execute>` on its own line
   - Blank line or imports next
   - `# </execute>` on its own line

3. **MANDATORY blank line after ALL imports (Python):**
   - After every import block, add blank line
   - Non-negotiable PEP 8 style

4. **NEVER concatenate language tag with content:**
   - Python: ` ```python ` NEWLINE `import random`
   - YAML: ` ```yaml ` NEWLINE `data:`
   - **NOT:** ` ```pythonimport ` or ` ```yamldata: `

5. **Proper indentation:**
   - Python: 4 spaces
   - YAML: 2 spaces
   - JSON: 2 spaces

6. **Tool References:**
   - Use backticks when discussing tools: `process_start`, `enhanced_read`
   - Use angle brackets ONLY when executing: (actual tool call syntax)
   - Never mix these in the same context

"""


# =============================================================================
# MODE DETECTION
# =============================================================================

MODE_GUIDANCE = """**Task routing:** Choose the smallest mode that matches the
request. Inspect enough to be accurate, act proportionately, and stop when the
objective is genuinely complete. Native tool schemas and repository safety
rules remain authoritative."""

MODE_INSTRUCTIONS = {
    "direct": """
**Direct mode:** Answer or act proportionately. Use the minimum inspection needed
for confidence, make requested changes promptly, verify, and stop.
""",
    "implement": """
**Implement mode:** Trace the production path, make the smallest coherent patch,
run proportionate tests, and report the result. Do not impose an investigation
quota or serialize independent read-only inspection.
""",
    "review": """
**Review mode:** Inspect the requested scope and report concrete findings with
severity and evidence. Do not edit unless the user explicitly requests fixes.
""",
    "explain": """
**Explain mode:** Teach the requested concept clearly using only the repository
evidence needed to avoid guessing. Avoid speculative edits and unnecessary tools.
""",
}


# =============================================================================
# SAFETY BOUNDARIES (Concise but Clear)
# =============================================================================

SAFETY_RULES = """**Safety:**

**Execution Persistence**
- Continue until the explicit objective is complete, blocked, or handed back
  with the specific missing input.
- Preserve progress with checkpoints, notes, and verified file state when the
  task spans multiple steps.

## Multi-Step
- Break implementation work into small verifiable steps.
- Run the narrowest useful verification after each risky change.

## Action Syntax
- Pre-write existence check: confirm target files before creating or replacing
  content.
- Prefer `apply_diff` or `apply_patch` style edits over blind rewrites.
- Treat permissions as allow/ask/deny and stop when approval is required.
- Post-verify touched files only unless the user asks for broader validation.

- Check file existence before writing: `Path(file).exists()`
- Use `edit_file` for exact replacements or `apply_patch` for contextual hunks
- Never blind overwrite without verification
- Respect permission boundaries

**Completion Signals (Call these tools, do not output them as text):**
- If native provider tools are available, call `finish_response` or
  `finish_task` through the provider tool channel
- If native tools are not available, call `<finish_response></finish_response>`
  to end a conversation turn
- If native tools are not available, call
  `<finish_task>{"status":"done","summary":"..."}</finish_task>` to mark task
  work ready for human review
- Never emit `TASK_COMPLETED` as plain text; it is legacy compatibility only
- Never rely on implicit completion
"""


# =============================================================================
# PROMPT BUILDER (Simple)
# =============================================================================


@dataclass
class PromptComponents:
    """Container for prompt components"""

    base_prompt: str
    karpathy_guidelines: str = ""
    ralph_mindset: str = ""
    response_patterns: str = ""
    mode_guidance: str = ""
    safety_rules: str = ""
    tool_guide: str = ""  # Loaded from proposed_tools.py


class PromptBuilder:
    """Builds prompts by composing modular components."""

    def __init__(self):
        self.components = None

    def load_components(self, **kwargs) -> None:
        """Load all prompt components"""
        self.components = PromptComponents(**kwargs)

    def build(self, mode: str = "direct") -> str:
        """Build a mode-aware system prompt."""
        if not self.components:
            raise ValueError("Components not loaded.")

        normalized_mode = str(mode).strip().lower()
        normalized_mode = {"build": "implement", "plan": "review"}.get(
            normalized_mode,
            normalized_mode,
        )
        mode_instructions = MODE_INSTRUCTIONS.get(
            normalized_mode,
            MODE_INSTRUCTIONS["direct"],
        )

        sections = [
            self.components.base_prompt,
            self.components.karpathy_guidelines,
            self.components.ralph_mindset,
            self.components.response_patterns,
            self.components.mode_guidance,
            mode_instructions,
            self.components.safety_rules,
            self.components.tool_guide,
        ]

        return "\n\n".join(filter(None, sections))


# Global instance
_builder = PromptBuilder()
_PROMPT_BUILDER_LOCK = threading.RLock()


def get_builder() -> PromptBuilder:
    """Get the global prompt builder instance"""
    return _builder


def build_system_prompt(mode: str = "direct", tool_guide: str = "") -> str:
    """Build complete system prompt."""
    with _PROMPT_BUILDER_LOCK:
        _builder.load_components(
            base_prompt=BASE_PROMPT,
            karpathy_guidelines=KARPATHY_GUIDELINES,
            ralph_mindset=RALPH_MINDSET,
            response_patterns=RESPONSE_PATTERNS,
            mode_guidance=MODE_GUIDANCE,
            safety_rules=SAFETY_RULES,
            tool_guide=tool_guide,
        )
        return _builder.build(mode=mode)


# Default system prompt (without tools - add those separately)
SYSTEM_PROMPT_CORE = build_system_prompt()

# =============================================================================
# FULL SYSTEM PROMPT (Assembled)
# =============================================================================


def get_system_prompt(mode: str = "direct") -> str:
    """Get the complete system prompt with all components."""
    tool_guide = get_tool_guide(mode)
    workflow_guide = get_workflow_guide(mode)

    with _PROMPT_BUILDER_LOCK:
        _builder.load_components(
            base_prompt=BASE_PROMPT,
            karpathy_guidelines=KARPATHY_GUIDELINES,
            ralph_mindset=RALPH_MINDSET,
            response_patterns=RESPONSE_PATTERNS,
            mode_guidance=MODE_GUIDANCE,
            safety_rules=SAFETY_RULES,
            tool_guide=tool_guide + "\n\n" + workflow_guide,
        )
        return _builder.build(mode=mode)


def build_active_turn_envelope(
    *,
    mode: str,
    active_task: str = "",
    continuation: str | None = None,
    terminal_reason: str | None = None,
    tool_state: str | None = None,
) -> str:
    """Build a compact dynamic envelope without selecting conversation history."""

    normalized_mode = str(mode or "direct").strip().lower()
    normalized_mode = {"build": "implement", "plan": "review"}.get(
        normalized_mode,
        normalized_mode,
    )
    payload = {
        "mode": normalized_mode,
        "active_task": str(active_task or "")[:1_000],
        "continuation": continuation,
        "terminal_reason": terminal_reason,
        "tool_state": tool_state,
    }
    compact = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"[PENGUIN_ACTIVE_TURN]{compact}[/PENGUIN_ACTIVE_TURN]"


def prompt_metrics(mode: str = "direct") -> dict[str, object]:
    """Return section sizes and a fingerprint for prompt/cache diagnostics."""

    tool_guide = get_tool_guide(mode)
    workflow_guide = get_workflow_guide(mode)
    sections = {
        "base": BASE_PROMPT,
        "behavior": KARPATHY_GUIDELINES + RALPH_MINDSET + RESPONSE_PATTERNS,
        "mode": MODE_GUIDANCE + MODE_INSTRUCTIONS.get(
            str(mode).strip().lower(), MODE_INSTRUCTIONS["direct"]
        ),
        "safety": SAFETY_RULES,
        "tools": tool_guide,
        "workflow": workflow_guide,
    }
    section_metrics = {
        name: {
            "chars": len(value),
            "estimated_tokens": max(1, len(value) // 4),
        }
        for name, value in sections.items()
    }
    fingerprint = hashlib.sha256(
        "\n".join(f"{name}:{sections[name]}" for name in sections).encode("utf-8")
    ).hexdigest()
    return {
        "mode": mode,
        "sections": section_metrics,
        "total_chars": sum(len(value) for value in sections.values()),
        "estimated_tokens": max(1, sum(len(value) for value in sections.values()) // 4),
        "fingerprint": fingerprint,
    }


# Full system prompt with all components assembled
SYSTEM_PROMPT = get_system_prompt()
