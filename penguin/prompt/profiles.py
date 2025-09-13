"""
Prompt Profiles - Mode and personality configurations.
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class PromptMode(Enum):
    """Available prompt modes"""
    DIRECT = "direct"
    BENCH_MINIMAL = "bench_minimal"  
    EXPLAIN = "explain"
    TERSE = "terse"
    REVIEW = "review"
    RESEARCH = "research"

@dataclass
class ModeProfile:
    """Configuration for a specific prompt mode"""
    name: str
    description: str
    personality_level: str  # "none", "minimal", "full"
    verbosity: str         # "minimal", "normal", "detailed" 
    reasoning_depth: str   # "fast", "normal", "deep"
    completion_phrases: bool = True
    
    # Mode-specific additions
    extra_sections: Optional[str] = None
    excluded_sections: Optional[list] = None

# Predefined mode profiles
MODE_PROFILES: Dict[str, ModeProfile] = {
    "direct": ModeProfile(
        name="direct",
        description="Minimal explanations, maximum persistence with essential safety",
        personality_level="minimal",
        verbosity="normal", 
        reasoning_depth="fast"
    ),
    
    "bench_minimal": ModeProfile(
        name="bench_minimal", 
        description="Benchmark-compatible, no persona, minimal protocol",
        personality_level="none",
        verbosity="minimal",
        reasoning_depth="fast",
        completion_phrases=False,
        excluded_sections=["advice", "large_codebase", "tool_learning"]
    ),
    
    "explain": ModeProfile(
        name="explain",
        description="Educational mode with reasoning and context",
        personality_level="minimal",
        verbosity="detailed",
        reasoning_depth="normal",
        extra_sections="\n## Response Style\nExplain your reasoning and provide educational context when helpful."
    ),
    
    "terse": ModeProfile(
        name="terse",
        description="Ultra-minimal responses, essential actions only",
        personality_level="none", 
        verbosity="minimal",
        reasoning_depth="fast",
        excluded_sections=["advice", "large_codebase", "tool_learning"],
        extra_sections="\n## Response Style\nBe concise. Minimal explanations unless asked."
    ),
    
    "review": ModeProfile(
        name="review",
        description="Code review focus with checklists and risk analysis",
        personality_level="minimal",
        verbosity="detailed", 
        reasoning_depth="normal",
        extra_sections="\n## Review Focus\nPrioritize security, performance, and maintainability. Provide checklists and risk assessments."
    ),
    
    "research": ModeProfile(
        name="research", 
        description="Information gathering with citations and sources",
        personality_level="minimal",
        verbosity="detailed",
        reasoning_depth="deep",
        extra_sections="\n## Research Mode\nProvide sources and citations. Gather comprehensive information before conclusions."
    )
}

def get_mode_profile(mode: str) -> ModeProfile:
    """Get profile for a specific mode"""
    return MODE_PROFILES.get(mode, MODE_PROFILES["direct"])

def list_available_modes() -> list[str]:
    """List all available prompt modes"""
    return list(MODE_PROFILES.keys())

def get_mode_description(mode: str) -> str:
    """Get description for a specific mode"""
    profile = get_mode_profile(mode)
    return profile.description