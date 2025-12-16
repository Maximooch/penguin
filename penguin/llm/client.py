"""
Link-aware LLM Client for Penguin.

This module provides the LLMClient class that wraps existing gateways (OpenRouter, LiteLLM)
with Link proxy integration for unified billing, analytics, and data collection.

Usage:
    # Via environment variables (set by Link when spawning Penguin)
    client = LLMClient.from_env(model_config)
    
    # Via explicit configuration
    config = LLMClientConfig(
        base_url="http://localhost:3001/api/v1",
        link=LinkConfig(user_id="user-123", session_id="sess-456")
    )
    client = LLMClient(model_config, config)
    
    # Runtime reconfiguration (via API)
    client.update_config(base_url="https://linkplatform.ai/api/v1")
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .model_config import ModelConfig

logger = logging.getLogger(__name__)


@dataclass
class LinkConfig:
    """Configuration for Link platform integration.
    
    These values are typically set by Link when spawning a Penguin session,
    either via environment variables or runtime API call.
    """
    user_id: Optional[str] = None  # Required for billing attribution
    session_id: Optional[str] = None  # Optional session tracking
    agent_id: Optional[str] = None  # Optional multi-agent scenarios
    workspace_id: Optional[str] = None  # Optional org-level billing
    api_key: Optional[str] = None  # Production auth (Bearer token)
    
    @classmethod
    def from_env(cls) -> "LinkConfig":
        """Load Link configuration from environment variables."""
        return cls(
            user_id=os.getenv("LINK_USER_ID"),
            session_id=os.getenv("LINK_SESSION_ID"),
            agent_id=os.getenv("LINK_AGENT_ID"),
            workspace_id=os.getenv("LINK_WORKSPACE_ID"),
            api_key=os.getenv("LINK_INFERENCE_API_KEY"),
        )
    
    def to_headers(self) -> Dict[str, str]:
        """Convert Link config to HTTP headers for the inference proxy.
        
        Returns headers in X-Link-* format (kebab-case).
        """
        headers: Dict[str, str] = {}
        
        if self.user_id:
            headers["X-Link-User-Id"] = self.user_id
        if self.session_id:
            headers["X-Link-Session-Id"] = self.session_id
        if self.agent_id:
            headers["X-Link-Agent-Id"] = self.agent_id
        if self.workspace_id:
            headers["X-Link-Workspace-Id"] = self.workspace_id
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        return headers
    
    @property
    def is_configured(self) -> bool:
        """Check if Link integration is configured (at minimum, user_id is set)."""
        return bool(self.user_id)
    
    def __repr__(self) -> str:
        return (
            f"LinkConfig(user_id={self.user_id!r}, session_id={self.session_id!r}, "
            f"agent_id={self.agent_id!r}, api_key={'***' if self.api_key else None})"
        )


@dataclass
class LLMClientConfig:
    """Full configuration for LLM client with Link integration.
    
    Attributes:
        base_url: LLM API endpoint. Defaults to OpenRouter if not set.
        link: Link platform configuration for billing/analytics.
        timeout_ms: Request timeout in milliseconds.
    """
    base_url: Optional[str] = None  # None = use gateway default (OpenRouter)
    link: LinkConfig = field(default_factory=LinkConfig)
    timeout_ms: int = 120_000  # 2 minutes default
    
    # Internal tracking
    _source: str = "default"  # "default", "env", "runtime_api"
    
    @classmethod
    def from_env(cls) -> "LLMClientConfig":
        """Load configuration from environment variables."""
        base_url = os.getenv("OPENAI_BASE_URL")
        link = LinkConfig.from_env()
        
        config = cls(
            base_url=base_url,
            link=link,
            _source="env" if base_url or link.is_configured else "default",
        )
        
        if link.is_configured:
            logger.info(f"Link integration configured: user_id={link.user_id}, base_url={base_url or 'default'}")
        elif base_url:
            logger.info(f"Custom LLM base_url configured: {base_url}")
            
        return config
    
    @property
    def effective_base_url(self) -> str:
        """Return the effective base URL, with default fallback."""
        return self.base_url or "https://openrouter.ai/api/v1"
    
    @property
    def is_link_proxy(self) -> bool:
        """Check if we're routing through Link's proxy (not direct to OpenRouter)."""
        if not self.base_url:
            return False
        # Link proxy URLs contain 'link' or are localhost:3001
        lower_url = self.base_url.lower()
        return (
            "link" in lower_url or 
            "localhost:3001" in lower_url or
            "127.0.0.1:3001" in lower_url
        )


class LLMClient:
    """Link-aware LLM client that wraps existing gateways.
    
    This client adds Link header injection and configurable base URLs
    on top of the existing OpenRouterGateway or LiteLLMGateway.
    
    Thread-safe for runtime configuration updates.
    """
    
    def __init__(
        self,
        model_config: "ModelConfig",
        config: Optional[LLMClientConfig] = None,
    ):
        """Initialize LLM client with optional Link configuration.
        
        Args:
            model_config: Model configuration (provider, model name, etc.)
            config: LLM client config including Link settings. If None, loads from env.
        """
        self.model_config = model_config
        self._config = config or LLMClientConfig.from_env()
        self._config_lock = threading.RLock()
        self._gateway: Optional[Any] = None
        self._gateway_lock = threading.RLock()
        
        logger.info(
            f"LLMClient initialized: model={model_config.model}, "
            f"base_url={self._config.effective_base_url}, "
            f"link_configured={self._config.link.is_configured}"
        )
    
    @classmethod
    def from_env(cls, model_config: "ModelConfig") -> "LLMClient":
        """Create LLM client with configuration from environment variables."""
        return cls(model_config, LLMClientConfig.from_env())
    
    @property
    def config(self) -> LLMClientConfig:
        """Get current configuration (thread-safe read)."""
        with self._config_lock:
            return self._config
    
    def update_config(
        self,
        base_url: Optional[str] = None,
        link_user_id: Optional[str] = None,
        link_session_id: Optional[str] = None,
        link_agent_id: Optional[str] = None,
        link_workspace_id: Optional[str] = None,
        link_api_key: Optional[str] = None,
    ) -> LLMClientConfig:
        """Update configuration at runtime (thread-safe).
        
        Only non-None values are updated. Returns the new configuration.
        This invalidates the cached gateway, forcing recreation on next request.
        
        Args:
            base_url: New LLM API endpoint
            link_user_id: Link user ID for billing
            link_session_id: Link session ID
            link_agent_id: Link agent ID
            link_workspace_id: Link workspace ID
            link_api_key: Link API key for production auth
            
        Returns:
            Updated LLMClientConfig
        """
        with self._config_lock:
            # Update Link config
            link = self._config.link
            new_link = LinkConfig(
                user_id=link_user_id if link_user_id is not None else link.user_id,
                session_id=link_session_id if link_session_id is not None else link.session_id,
                agent_id=link_agent_id if link_agent_id is not None else link.agent_id,
                workspace_id=link_workspace_id if link_workspace_id is not None else link.workspace_id,
                api_key=link_api_key if link_api_key is not None else link.api_key,
            )
            
            # Update main config
            new_base_url = base_url if base_url is not None else self._config.base_url
            
            self._config = LLMClientConfig(
                base_url=new_base_url,
                link=new_link,
                timeout_ms=self._config.timeout_ms,
                _source="runtime_api",
            )
            
            logger.info(
                f"LLMClient config updated: base_url={self._config.effective_base_url}, "
                f"link_user_id={new_link.user_id}"
            )
            
        # Invalidate cached gateway
        with self._gateway_lock:
            self._gateway = None
            
        return self._config
    
    def get_link_headers(self) -> Dict[str, str]:
        """Get Link headers for the current configuration.
        
        Returns empty dict if Link is not configured.
        """
        with self._config_lock:
            if not self._config.link.is_configured:
                return {}
            
            headers = self._config.link.to_headers()
            
            # Log warning if routing through Link proxy without user_id
            if self._config.is_link_proxy and not self._config.link.user_id:
                logger.warning(
                    "Request routed through Link proxy without X-Link-User-Id header. "
                    "Billing attribution will fail."
                )
                
            return headers
    
    def _get_gateway(self) -> Any:
        """Get or create the underlying gateway with current configuration.
        
        Lazily creates the gateway and caches it. Cache is invalidated
        when configuration changes.
        """
        with self._gateway_lock:
            if self._gateway is not None:
                return self._gateway
            
            # Create gateway based on client preference
            preference = self.model_config.client_preference
            
            if preference == "openrouter":
                from .openrouter_gateway import OpenRouterGateway
                
                # Get current config
                with self._config_lock:
                    base_url = self._config.base_url  # None = use gateway default
                    link_headers = self.get_link_headers()
                
                self._gateway = OpenRouterGateway(
                    self.model_config,
                    base_url=base_url,
                    extra_headers=link_headers,
                )
                
            elif preference == "litellm":
                from .litellm_gateway import LiteLLMGateway
                
                # LiteLLM gateway needs different handling
                # For now, create with Link headers passed through
                with self._config_lock:
                    link_headers = self.get_link_headers()
                
                self._gateway = LiteLLMGateway(
                    self.model_config,
                    extra_headers=link_headers,
                )
                
            else:
                # Native adapters - pass through for now
                from .adapters import get_adapter
                self._gateway = get_adapter(self.model_config.provider, self.model_config)
                
            return self._gateway
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Make a chat completion request through the configured gateway.
        
        This is the main entry point for LLM requests. It:
        1. Gets/creates the appropriate gateway
        2. Injects Link headers if configured
        3. Forwards the request to the gateway
        
        Args:
            messages: Chat messages in OpenAI format
            max_output_tokens: Maximum tokens in response
            temperature: Sampling temperature
            stream: Whether to stream the response
            stream_callback: Callback for streaming chunks
            **kwargs: Additional arguments passed to the gateway
            
        Returns:
            Response dict with 'content', 'model', 'usage', etc.
        """
        gateway = self._get_gateway()
        
        # Refresh Link headers on each request (in case config was updated)
        with self._config_lock:
            link_headers = self.get_link_headers()
            
        # Update gateway headers if it supports it
        if hasattr(gateway, 'extra_headers') and link_headers:
            # Merge new headers with existing
            if isinstance(gateway.extra_headers, dict):
                gateway.extra_headers.update(link_headers)
            else:
                gateway.extra_headers = link_headers
        
        # Forward to gateway
        return await gateway.chat_completion(
            messages=messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            stream=stream,
            stream_callback=stream_callback,
            **kwargs,
        )
    
    async def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens in messages using the gateway's token counter."""
        gateway = self._get_gateway()
        if hasattr(gateway, 'count_tokens'):
            return await gateway.count_tokens(messages)
        # Fallback: rough estimate
        import tiktoken
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            text = " ".join(m.get("content", "") for m in messages if isinstance(m.get("content"), str))
            return len(enc.encode(text))
        except Exception:
            return sum(len(str(m.get("content", ""))) // 4 for m in messages)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current client status for diagnostics."""
        with self._config_lock:
            return {
                "base_url": self._config.effective_base_url,
                "is_link_proxy": self._config.is_link_proxy,
                "link_configured": self._config.link.is_configured,
                "link_user_id": self._config.link.user_id,
                "link_session_id": self._config.link.session_id,
                "config_source": self._config._source,
                "client_preference": self.model_config.client_preference,
                "model": self.model_config.model,
            }
