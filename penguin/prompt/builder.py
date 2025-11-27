"""
Prompt Builder - Composes prompts from modular components.
Phase 1 implementation with basic mode support.
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class PromptComponents:
    """Container for prompt components"""
    base_prompt: str
    empirical_first: str
    persistence_directive: str
    workflow_section: str
    project_workflow: str
    multi_turn_investigation: str
    action_syntax: str
    advice_section: str
    completion_phrases: str
    large_codebase_guide: str
    tool_learning_guide: str
    code_analysis_guide: str
    python_guide: str

class PromptBuilder:
    """
    Builds prompts by composing modular components.
    Phase 1: Basic assembly with mode support.
    """
    
    def __init__(self):
        self.components = None
        # Output formatting guidance appended to prompts; defaults lazily
        self.output_formatting: str = ""
        # Security/permission context section (generated dynamically)
        self._permission_section: str = ""
        self._permission_config: dict = {}
        
    def load_components(self,
                       base_prompt: str,
                       empirical_first: str,
                       persistence_directive: str,
                       workflow_section: str,
                       project_workflow: str,
                       multi_turn_investigation: str,
                       action_syntax: str,
                       advice_section: str,
                       completion_phrases: str,
                       large_codebase_guide: str,
                       tool_learning_guide: str,
                       code_analysis_guide: str,
                       python_guide: str) -> None:
        """Load all prompt components"""
        self.components = PromptComponents(
            base_prompt=base_prompt,
            empirical_first=empirical_first,
            persistence_directive=persistence_directive,
            workflow_section=workflow_section,
            project_workflow=project_workflow,
            multi_turn_investigation=multi_turn_investigation,
            action_syntax=action_syntax,
            advice_section=advice_section,
            completion_phrases=completion_phrases,
            large_codebase_guide=large_codebase_guide,
            tool_learning_guide=tool_learning_guide,
            code_analysis_guide=code_analysis_guide,
            python_guide=python_guide
        )
    
    def set_permission_context(
        self,
        mode: str = "workspace",
        enabled: bool = True,
        workspace_root: Optional[str] = None,
        project_root: Optional[str] = None,
        allowed_paths: Optional[list] = None,
        denied_paths: Optional[list] = None,
        require_approval: Optional[list] = None,
    ) -> None:
        """Set the permission/security context for prompt generation.
        
        This updates the permission section that gets included in prompts,
        informing the agent what operations are allowed.
        
        Args:
            mode: Permission mode ('read_only', 'workspace', 'full')
            enabled: Whether permission checks are active
            workspace_root: Current workspace directory
            project_root: Current project directory
            allowed_paths: Additional allowed path patterns
            denied_paths: Denied path patterns
            require_approval: Operations requiring approval
        """
        self._permission_config = {
            "mode": mode,
            "enabled": enabled,
            "workspace_root": workspace_root,
            "project_root": project_root,
            "allowed_paths": allowed_paths or [],
            "denied_paths": denied_paths or [],
            "require_approval": require_approval or [],
        }
        # Regenerate the permission section
        self._regenerate_permission_section()
    
    def _regenerate_permission_section(self) -> None:
        """Regenerate the permission section from current config."""
        try:
            from penguin.security.prompt_integration import get_permission_section
            self._permission_section = get_permission_section(**self._permission_config)
        except ImportError:
            # Security module not available, use minimal fallback
            mode = self._permission_config.get("mode", "workspace")
            enabled = self._permission_config.get("enabled", True)
            if not enabled:
                self._permission_section = "\n## Permissions\n**YOLO mode active** - no restrictions.\n"
            else:
                self._permission_section = f"\n## Permissions\n**Mode: {mode.upper()}** - Standard boundaries apply.\n"
        except Exception:
            self._permission_section = ""
    
    def build(self, mode: str = "direct", **kwargs) -> str:
        """
        Build system prompt with mode-specific adjustments.
        
        Args:
            mode: Prompt mode ('direct', 'bench_minimal', 'explain', 'terse', 'review')
            **kwargs: Additional context variables
            
        Returns:
            Assembled system prompt
        """
        if not self.components:
            raise ValueError("Components not loaded. Call load_components() first.")

        # ALWAYS refresh output formatting to pick up latest changes from prompt_workflow.py
        # Don't cache it - we want to get updates when prompt_workflow.py is modified
        try:
            from penguin.prompt_workflow import get_output_formatting
            # Determine style from config or use default
            from penguin.config import config as raw_config
            style = str(raw_config.get("output", {}).get("prompt_style", "steps_final")).strip().lower()
            self.output_formatting = get_output_formatting(style or "steps_final")
        except Exception as e:
            # Safe fallback: no additional formatting guidance
            self.output_formatting = ""
            
        # Apply mode-specific deltas
        if mode == "bench_minimal":
            return self._build_bench_minimal()
        elif mode == "direct":
            return self._build_direct()
        elif mode == "terse":
            return self._build_terse()
        elif mode == "explain":
            return self._build_explain()
        elif mode == "review":
            return self._build_review()
        elif mode == "implement":
            return self._build_implement()
        elif mode == "test":
            return self._build_test()
        else:
            # Default to direct mode
            return self._build_direct()
    
    def _build_bench_minimal(self) -> str:
        """Build minimal prompt for benchmark compatibility"""
        return (
            "You are Penguin, a software engineering agent.\n\n" +
            "## Core Rules\n" +
            "- Continue working until task completion\n" +
            "- Check paths before writing; create backups automatically\n" +  
            "- Use <execute> for Python code, <apply_diff> for file edits\n" +
            "- Acknowledge tool results before next action\n\n" +
            self.components.action_syntax
        )
    
    def _build_direct(self) -> str:
        """Build standard direct mode prompt"""
        # Import forbidden phrases detection at runtime
        from penguin.prompt_workflow import FORBIDDEN_PHRASES_DETECTION
        
        # Import incremental execution rule at runtime
        from penguin.prompt_workflow import INCREMENTAL_EXECUTION_RULE
        
        return (
            """**OUTPUT STYLE (Codex/Cursor/Claude Code Pattern):**

Show your work, not your process:
- ✅ Execute tools → Show results → Answer the question
- ❌ Never say: "Let me start by...", "I need to...", "I'll check...", "Following instructions..."
- ❌ Never list: "1. First I'll... 2. Then I'll... 3. Finally..."
- ✅ If uncertain: Ask clarifying question, don't explain your uncertainty
- ✅ Planning OK: Brief *italicized* thoughts (goes to reasoning block, hidden by default)

Match Codex/Cursor directness: Answer → Evidence → Done

""" +
            INCREMENTAL_EXECUTION_RULE +
            "\n\n" +
            FORBIDDEN_PHRASES_DETECTION +
            "\n\n" +
            self.components.base_prompt +
            self._permission_section +  # Include permission context
            self.components.empirical_first +
            self.components.persistence_directive +
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.multi_turn_investigation +
            self.components.action_syntax +
            self.output_formatting +
            self.components.advice_section +
            self.components.completion_phrases +
            self.components.large_codebase_guide +
            self.components.tool_learning_guide +
            self.components.code_analysis_guide +
            self.components.python_guide
        )
    
    def _build_terse(self) -> str:
        """Build ultra-minimal prompt"""
        return (
            self.components.base_prompt +
            self._permission_section +
            self.components.persistence_directive + 
            self.components.action_syntax +
            self.output_formatting +
            "\n## Response Style\nBe concise. Minimal explanations unless asked."
        )
    
    def _build_explain(self) -> str:
        """Build educational mode prompt"""
        return (
            self.components.base_prompt +
            self._permission_section +
            self.components.persistence_directive + 
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.action_syntax +
            self.output_formatting +
            self.components.advice_section +
            "\n## Response Style\nExplain your reasoning and provide educational context when helpful."
        )
    
    def _build_review(self) -> str:
        """Build code review focused prompt"""
        return (
            self.components.base_prompt +
            self._permission_section +
            self.components.persistence_directive + 
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.action_syntax +
            self.output_formatting +
            "\n## Review Focus\nPrioritize security, performance, and maintainability. Provide checklists and risk assessments."
        )

    def _build_implement(self) -> str:
        """Build implementation-focused prompt (spec-first, incremental)."""
        return (
            self.components.base_prompt +
            self._permission_section +
            self.components.persistence_directive +
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.action_syntax +
            self.output_formatting +
            "\n## Implementation Focus\nFollow spec-first, domain-driven steps. Work in small, verifiable increments, updating tests and docs as you go."
        )

    def _build_test(self) -> str:
        """Build testing/validation-focused prompt."""
        return (
            self.components.base_prompt +
            self._permission_section +
            self.components.persistence_directive +
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.action_syntax +
            self.output_formatting +
            "\n## Testing Focus\nDesign and run tests first when possible. Execute, observe, iterate until green; then validate against acceptance criteria."
        )

# Global instance
_builder = PromptBuilder()

def get_builder() -> PromptBuilder:
    """Get the global prompt builder instance"""
    return _builder

def build_system_prompt(mode: str = "direct", **kwargs) -> str:
    """
    Convenience function to build system prompt.
    
    Args:
        mode: Prompt mode
        **kwargs: Additional context variables
        
    Returns:
        Assembled system prompt
    """
    return _builder.build(mode=mode, **kwargs)

def set_output_formatting(style: str = "steps_final") -> None:
    """Set the global builder's output formatting style.

    Args:
        style: One of 'steps_final', 'plain', 'json_guided'
    """
    try:
        from penguin.prompt_workflow import get_output_formatting
        _builder.output_formatting = get_output_formatting(style)
    except Exception:
        _builder.output_formatting = ""


def set_permission_context_from_config() -> None:
    """Initialize permission context from current config.
    
    Reads security settings from Config and RuntimeConfig,
    then updates the prompt builder's permission section.
    """
    try:
        from penguin.config import Config, RuntimeConfig, load_config
        
        # Load config
        config_data = load_config()
        security_data = config_data.get("security", {})
        
        # Try to get runtime config for workspace/project roots
        workspace_root = None
        project_root = None
        try:
            # RuntimeConfig may not be initialized yet
            runtime = RuntimeConfig(config_data)
            workspace_root = runtime.workspace_root
            project_root = runtime.project_root
        except Exception:
            pass
        
        _builder.set_permission_context(
            mode=security_data.get("mode", "workspace"),
            enabled=security_data.get("enabled", True),
            workspace_root=workspace_root,
            project_root=project_root,
            allowed_paths=security_data.get("allowed_paths", []),
            denied_paths=security_data.get("denied_paths", []),
            require_approval=security_data.get("require_approval", []),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Could not set permission context from config: {e}")
