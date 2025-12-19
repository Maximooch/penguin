from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, validator  # type: ignore

if TYPE_CHECKING:
    from penguin.config import Config, AgentPersonaConfig

# ---------------------------------------------------------------------------
# Agent configuration data-classes
# ---------------------------------------------------------------------------
# Unified agent configuration supporting both:
# 1. YAML-based autonomous agents (with `type` for class loading)
# 2. Persona-based runtime configs (from config.yml)

class AgentLimits(BaseModel):
    """Resource limits for agent execution."""

    max_tokens: Optional[int] = Field(
        None, description="Maximum total tokens (prompt + completion) per invocation."
    )
    max_wall_clock_sec: Optional[float] = Field(
        None, description="Maximum wall clock time in seconds per invocation."
    )
    max_memory_mb: Optional[int] = Field(
        None, description="Maximum memory allocation in megabytes (Docker only)."
    )
    max_cpu_pct: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Maximum CPU percentage allocation (Docker only).",
    )


class AgentSecurity(BaseModel):
    """Security constraints for agent execution."""

    allowed_tools: Optional[List[str]] = Field(
        None,
        description="Explicit list of tool names the agent can use. If None, defaults may apply.",
    )
    allowed_outbound_domains: Optional[List[str]] = Field(
        None, description="List of allowed domain names for network requests."
    )
    sandbox_type: Literal["none", "docker", "firecracker", "shared_docker"] = Field(
        "none", description="Type of execution sandbox."
    )
    # Future: filesystem_access: Literal["read_only", "workspace_write", "full_write"]


class AgentMount(BaseModel):
    """Volume mounts for containerized agents (Docker/Firecracker)."""

    host_path: str = Field(..., description="Path on the host machine.")
    container_path: str = Field(..., description="Path inside the agent container.")
    read_only: bool = Field(False, description="Mount the volume as read-only.")


class AgentConfig(BaseModel):
    """Unified configuration schema for a Penguin Agent.

    Supports two modes:
    1. YAML-based autonomous agents: Set `type` to a fully-qualified class path
    2. Persona-based runtime agents: Set `system_prompt` and optionally `model_id`

    Use `from_persona()` to build from config.yml persona definitions.
    """

    spec_version: Literal["0.1"] = Field("0.1", description="Version of the agent configuration schema.")
    name: str = Field(..., description="Unique identifier name for the agent.")
    description: Optional[str] = Field(None, description="Human-readable description of the agent's purpose.")

    # --- YAML-based agent fields ---
    type: Optional[str] = Field(
        None, description="Fully-qualified class name implementing the agent (e.g. 'penguin.agent.basic.EchoAgent'). Required for YAML-based agents."
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="Tags indicating agent capabilities (e.g. 'refactoring', 'testing', 'research').",
    )
    mounts: List[AgentMount] = Field(
        default_factory=list, description="Volume mounts for containerized execution."
    )
    env: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables for the agent execution context."
    )

    # --- Persona-based agent fields ---
    system_prompt: Optional[str] = Field(
        None, description="System prompt for persona-based agents."
    )
    model_id: Optional[str] = Field(
        None, description="Model identifier (e.g. 'anthropic/claude-sonnet'). If None, uses default."
    )
    permissions: Optional[Dict[str, Any]] = Field(
        None, description="Unified permissions config (operations, paths, mode)."
    )

    # --- Shared fields ---
    limits: AgentLimits = Field(default_factory=AgentLimits, description="Resource limits.")
    security: AgentSecurity = Field(default_factory=AgentSecurity, description="Security constraints.")
    tools: Optional[List[str]] = Field(
        None,
        description="Overrides allowed_tools – explicit set of tools available to the agent.",
    )

    # --- Session sharing (for sub-agents) ---
    share_session_with: Optional[str] = Field(
        None, description="Parent agent ID to share conversation session with."
    )
    share_context_window_with: Optional[str] = Field(
        None, description="Parent agent ID to share context window with."
    )

    @validator("tools", always=True)
    def _tools_or_security_allowed_tools(cls, v, values):  # noqa: D401
        """Ensure *tools* overrides *security.allowed_tools* when both provided."""
        security: AgentSecurity | None = values.get("security")  # type: ignore[assignment]
        if v is not None and security and security.allowed_tools is not None:
            return v
        if v is None and security and security.allowed_tools is not None:
            return security.allowed_tools
        return v

    @classmethod
    def from_persona(cls, persona: "AgentPersonaConfig") -> "AgentConfig":
        """Build AgentConfig from a config.yml persona definition.

        Args:
            persona: AgentPersonaConfig from config.yml

        Returns:
            AgentConfig suitable for runtime use
        """
        return cls(
            name=persona.name,
            description=persona.description,
            system_prompt=persona.system_prompt,
            model_id=persona.model.id if persona.model else None,
            tools=list(persona.default_tools) if persona.default_tools else None,
            permissions=persona.permissions,
            share_session_with=persona.share_session_with,
            share_context_window_with=persona.share_context_window_with,
            limits=AgentLimits(
                max_tokens=persona.shared_context_window_max_tokens,
            ) if persona.shared_context_window_max_tokens else AgentLimits(),
        )

    @classmethod
    def from_persona_name(cls, name: str, config: "Config") -> "AgentConfig":
        """Build AgentConfig from a persona name in config.yml.

        Args:
            name: Persona name from config.yml agents section
            config: The Config instance containing agent_personas

        Returns:
            AgentConfig for the persona, or a default config if not found
        """
        persona = config.agent_personas.get(name)
        if persona:
            return cls.from_persona(persona)
        # Return minimal default config
        return cls(name=name)

    class Config:
        extra = "ignore"  # Allow extra fields for forward compatibility