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
    persistence_directive: str
    workflow_section: str
    project_workflow: str
    action_syntax: str
    advice_section: str
    completion_phrases: str
    large_codebase_guide: str
    tool_learning_guide: str
    code_analysis_guide: str

class PromptBuilder:
    """
    Builds prompts by composing modular components.
    Phase 1: Basic assembly with mode support.
    """
    
    def __init__(self):
        self.components = None
        # Output formatting guidance appended to prompts; defaults lazily
        self.output_formatting: str = ""
        
    def load_components(self, 
                       base_prompt: str,
                       persistence_directive: str,
                       workflow_section: str,
                       project_workflow: str,
                       action_syntax: str,
                       advice_section: str,
                       completion_phrases: str,
                       large_codebase_guide: str,
                       tool_learning_guide: str,
                       code_analysis_guide: str) -> None:
        """Load all prompt components"""
        self.components = PromptComponents(
            base_prompt=base_prompt,
            persistence_directive=persistence_directive,
            workflow_section=workflow_section,
            project_workflow=project_workflow,
            action_syntax=action_syntax,
            advice_section=advice_section,
            completion_phrases=completion_phrases,
            large_codebase_guide=large_codebase_guide,
            tool_learning_guide=tool_learning_guide,
            code_analysis_guide=code_analysis_guide
        )
    
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

        # Ensure an output formatting section exists (default to steps+final)
        if not self.output_formatting:
            try:
                from penguin.prompt_workflow import get_output_formatting
                self.output_formatting = get_output_formatting("steps_final")
            except Exception:
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
        return (
            self.components.base_prompt +
            self.components.persistence_directive + 
            self.components.workflow_section +
            self.components.project_workflow +
            self.components.action_syntax +
            self.output_formatting +
            self.components.advice_section +
            self.components.completion_phrases +
            self.components.large_codebase_guide +
            self.components.tool_learning_guide +
            self.components.code_analysis_guide
        )
    
    def _build_terse(self) -> str:
        """Build ultra-minimal prompt"""
        return (
            self.components.base_prompt +
            self.components.persistence_directive + 
            self.components.action_syntax +
            self.output_formatting +
            "\n## Response Style\nBe concise. Minimal explanations unless asked."
        )
    
    def _build_explain(self) -> str:
        """Build educational mode prompt"""
        return (
            self.components.base_prompt +
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
