from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, validator # type: ignore

# Version 0.1 schema

class AgentLimits(BaseModel):
    """Resource limits for agent execution."""
    max_tokens: Optional[int] = Field(None, description="Maximum total tokens (prompt + completion) per invocation.")
    max_wall_clock_sec: Optional[float] = Field(None, description="Maximum wall clock time in seconds per invocation.")
    max_memory_mb: Optional[int] = Field(None, description="Maximum memory allocation in megabytes (Docker only).")
    max_cpu_pct: Optional[int] = Field(None, ge=0, le=100, description="Maximum CPU percentage allocation (Docker only).")

class AgentSecurity(BaseModel):
    """Security constraints for agent execution."""
    allowed_tools: Optional[List[str]] = Field(None, description="Explicit list of tool names the agent can use. If None, defaults may apply.")
    allowed_outbound_domains: Optional[List[str]] = Field(None, description="List of allowed domain names for network requests.")
    sandbox_type: Literal["none", "docker", "firecracker", "shared_docker"] = Field("none", description="Type of execution sandbox.")
    # Future: filesystem_access: Literal["read_only", "workspace_write", "full_write"]

class AgentMount(BaseModel):
    """Volume mounts for containerized agents (Docker/Firecracker)."""
    host_path: str = Field(..., description="Path on the host machine.")
    container_path: str = Field(..., description="Path inside the agent container.")
    read_only: bool = Field(False, description="Mount the volume as read-only.")

class AgentConfig(BaseModel):
    """Configuration schema for a Penguin Agent."""
    spec_version: Literal["0.1"] = Field("0.1", description="Version of the agent configuration schema.")
    name: str = Field(..., description="Unique identifier name for the agent.")
    description: Optional[str] = Field(None, description="Human-readable description of the agent's purpose.")
    type: str = Field(..., description="The fully qualified class name of the agent implementation (e.g., 'penguin.agent.basic.EchoAgent').")
    capabilities: List[str] = Field(default_factory=list, description="List of tags indicating agent capabilities (e.g., 'refactoring', 'testing', 'research').")
    limits: AgentLimits = Field(default_factory=AgentLimits, description="Resource limits.")
    security: AgentSecurity = Field(default_factory=AgentSecurity, description="Security constraints.")
    mounts: List[AgentMount] = Field(default_factory=list, description="Volume mounts for containerized execution.")
    tools: Optional[List[str]] = Field(None, description="Overrides allowed_tools in security, defining the specific tools available.")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables to set for the agent execution context.")
    # Future: cognition_phases: Optional[List[str]] = Field(None, description="Override default cognitive cycle phases.")

    @validator('tools', always=True)
    def tools_or_security_allowed_tools(cls, v, values):
        """Ensure tools override security.allowed_tools if both are present."""
        security = values.get('security')
        if v is not None and security and security.allowed_tools is not None:
            # If 'tools' is explicitly set, it takes precedence.
            pass
        elif v is None and security and security.allowed_tools is not None:
            # If 'tools' is not set but security.allowed_tools is, use the latter.
            return security.allowed_tools
        elif v is None and (security is None or security.allowed_tools is None):
             # Default to None, meaning system default applies.
             return None
        return v

    class Config:
        extra = 'forbid' # Disallow extra fields 