"""
Proposed System Prompt - Consolidated and Slimmed
Target: ~3,000 tokens (down from ~15,000)
"""

import datetime
import os
import platform
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Environment info
os_info = platform.system() if platform.system() == "Windows" else os.uname().sysname
date = datetime.datetime.now().strftime("%Y-%m-%d")
time = datetime.datetime.now().strftime("%H:%M:%S")


BASE_PROMPT = f"""
You are Penguin, a cracked software engineer employee agent specializing in software development and project management.

**Operating System:** {os_info}
**Date:** {date} {time}

**Core Traits:**
- Fact-based skeptic: verify everything, challenge assumptions
- Direct and succinct: show work, not process
- Strategic advisor: identify gaps, push beyond comfort zones
- No sycophancy: brutally honest, no excuses

**Response Pattern (Codex/Cursor Style):**
- Execute tools → Show results → Answer
- Never say: "Let me start by...", "I need to...", "Following instructions..."
- Never list: "1. First I will... 2. Then I will..." 
- Planning OK: Brief *italicized* thoughts (max 60 words)
- Match Codex directness: Answer → Evidence → Done

**Ambition vs Precision:**
- New tasks: Be ambitious and creative
- Existing codebases: Surgical precision, respect existing patterns
"""

TOOL_RESULT_HANDLING = """**Tool Result Handling:**
- Results appear in next message - you MUST respond
- Exploration: Execute all tools silently, respond ONCE with complete findings
- Implementation: Acknowledge critical changes, continue
- NEVER execute same tool twice - check previous message first"""

CODE_FORMATTING = """**Code Formatting:**
- Language tag on separate line: ```python [newline] import os
- Blank line after ALL imports (PEP 8)
- 4-space indentation (Python), 2-space (YAML/JSON)
- Tool refs in backticks: `enhanced_read` (not <enhanced_read>)"""


# =============================================================================
# PROMPT BUILDER
# =============================================================================

@dataclass
class PromptComponents:
    """Container for prompt components"""
    base_prompt: str
    empirical_first: str = ""
    safety_rules: str = ""
    incremental_execution: str = ""
    forbidden_phrases: str = ""
    tool_result_handling: str = ""
    code_formatting: str = ""
    tool_syntax: str = ""
    workflow_guide: str = ""
    completion_signals: str = ""


class PromptBuilder:
    """Builds prompts by composing modular components."""

    def __init__(self):
        self.components = None
        self._permission_section: str = ""

    def load_components(self, **kwargs) -> None:
        """Load all prompt components"""
        self.components = PromptComponents(**kwargs)

    def set_permission_context(self, mode: str = "workspace", **kwargs) -> None:
        """Set the permission/security context for prompt generation."""
        self._permission_section = f"\n## Permissions\n**Mode: {mode.upper()}**\n"

    def build(self, mode: str = "direct", **kwargs) -> str:
        """Build system prompt with mode-specific adjustments."""
        if not self.components:
            raise ValueError("Components not loaded. Call load_components() first.")

        sections = [
            self.components.base_prompt,
            self._permission_section,
            self.components.empirical_first,
            self.components.safety_rules,
            self.components.incremental_execution,
            self.components.forbidden_phrases,
            self.components.tool_result_handling,
            self.components.code_formatting,
            self.components.tool_syntax,
            self.components.workflow_guide,
            self.components.completion_signals,
        ]

        return "\n\n".join(filter(None, sections))


# Global instance
_builder = PromptBuilder()

def get_builder() -> PromptBuilder:
    """Get the global prompt builder instance"""
    return _builder

def build_system_prompt(mode: str = "direct", **kwargs) -> str:
    """Convenience function to build system prompt."""
    return _builder.build(mode=mode, **kwargs)


# =============================================================================
# DEFAULT SYSTEM PROMPT
# =============================================================================

# Initialize builder with components
_builder.load_components(
    base_prompt=BASE_PROMPT,
    empirical_first=EMPIRICAL_FIRST,
    safety_rules=SAFETY_RULES,
    incremental_execution=INCREMENTAL_EXECUTION,
    forbidden_phrases=FORBIDDEN_PHRASES,
    tool_result_handling=TOOL_RESULT_HANDLING,
    code_formatting=CODE_FORMATTING,
    tool_syntax="",  # To be loaded from proposed_tools.py
    workflow_guide="",  # To be loaded from proposed_workflow.py
    completion_signals="",  # To be loaded from proposed_workflow.py
)

SYSTEM_PROMPT = _builder.build(mode="direct")
