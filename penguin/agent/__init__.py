"""High-level PenguinAgent wrapper around PenguinCore."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from penguin.api_client import PenguinClient
from penguin.config import WORKSPACE_PATH, Config
from penguin.core import PenguinCore


class PenguinAgent:
    """Synchronous convenience wrapper for :class:`PenguinCore`.

    Parameters
    ----------
    workspace_path:
        Base workspace directory. Defaults to the configured Penguin workspace.
    model, provider:
        Optional overrides forwarded to :class:`PenguinClient` / :meth:`PenguinCore.create`.
    charter_path:
        Path to a shared charter/instructions file. If omitted PenguinAgent attempts to
        discover one automatically (``context/TASK_CHARTER.md`` or ``context/SMOKE_CHARTER.md``).
    auto_load_docs:
        When ``True`` (default) project documentation such as ``PENGUIN.md`` and ``AGENTS.md``
        is automatically loaded as context for every chat.
    default_agent_id:
        Agent identifier to use when one is not supplied explicitly to :meth:`chat`.
    config:
        Optional :class:`~penguin.config.Config` instance to reuse (advanced use only).
    """

    #: default files checked for project documentation (in priority order)
    PROJECT_DOC_CANDIDATES: Sequence[str] = ("PENGUIN.md", "AGENTS.md", "README.md")

    def __init__(
        self,
        *,
        workspace_path: Optional[str | Path] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        charter_path: Optional[str | Path] = None,
        auto_load_docs: bool = True,
        default_agent_id: str = "default",
        config: Optional[Config] = None,
    ) -> None:
        self.workspace_path = Path(workspace_path or WORKSPACE_PATH).resolve()
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        (self.workspace_path / "projects").mkdir(exist_ok=True)
        (self.workspace_path / "context").mkdir(exist_ok=True)

        self._loop = asyncio.new_event_loop()
        self._client = PenguinClient(
            model=model,
            provider=provider,
            workspace_path=str(self.workspace_path),
        )
        if config is not None:
            self._client.config = config

        self._run(self._client.initialize())
        self.core: PenguinCore = self._client._core  # type: ignore[attr-defined]
        self.default_agent_id = default_agent_id

        self.charter_path = self._resolve_charter(charter_path)
        self.project_docs: List[str] = self._discover_project_docs() if auto_load_docs else []

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def __enter__(self) -> "PenguinAgent":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: D401 - standard signature
        self.close()

    async def aclose(self) -> None:
        await self._client.close()
        self._loop.close()

    def close(self) -> None:
        """Synchronously close the underlying client/event loop."""
        try:
            self._run(self._client.close())
        finally:
            if not self._loop.is_closed():
                self._loop.close()

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------
    def chat(
        self,
        message: str,
        *,
        agent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        context_files: Optional[Iterable[str]] = None,
        max_iterations: int = 5,
        multi_step: bool = True,
    ) -> Dict[str, Any]:
        """Send a message to the assistant and return the structured response."""

        effective_agent = agent_id or self.default_agent_id
        files = self._prepare_context_files(context_files)
        payload: Dict[str, Any] = {"text": message}
        return self._run(
            self.core.process(
                payload,
                context=context,
                agent_id=effective_agent,
                context_files=files,
                max_iterations=max_iterations,
                multi_step=multi_step,
            )
        )

    def send_to_agent(
        self,
        target_agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Route a structured message to another agent using the shared MessageBus."""

        return self._run(
            self.core.send_to_agent(
                target_agent_id,
                content,
                message_type=message_type,
                metadata=metadata,
                channel=channel,
            )
        )

    def register_agent(
        self,
        agent_id: str,
        *,
        system_prompt: Optional[str] = None,
        activate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Register an additional persona on the underlying core."""

        self.core.register_agent(
            agent_id,
            system_prompt=system_prompt,
            activate=activate,
            **kwargs,
        )

    def create_sub_agent(self, agent_id: str, *, parent_agent_id: str, **kwargs: Any) -> None:
        self.core.create_sub_agent(agent_id, parent_agent_id=parent_agent_id, **kwargs)

    def list_agents(self) -> List[str]:
        return self.core.list_agents()

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def get_charter(self) -> Optional[str]:
        return self.charter_path.read_text(encoding="utf-8") if self.charter_path and self.charter_path.exists() else None

    def project_documents(self) -> List[str]:
        return list(self.project_docs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _resolve_charter(self, explicit: Optional[str | Path]) -> Optional[Path]:
        if explicit:
            candidate = Path(explicit).resolve()
            return candidate if candidate.exists() else None
        for rel in ["context/TASK_CHARTER.md", "context/SMOKE_CHARTER.md"]:
            candidate = (self.workspace_path / rel).resolve()
            if candidate.exists():
                return candidate
        return None

    def _discover_project_docs(self) -> List[str]:
        docs: List[str] = []
        for name in self.PROJECT_DOC_CANDIDATES:
            candidate = (self.workspace_path / name).resolve()
            if candidate.exists():
                docs.append(candidate.as_posix())
        return docs

    def _prepare_context_files(self, extra: Optional[Iterable[str]]) -> List[str]:
        files: List[str] = []
        if self.charter_path and self.charter_path.exists():
            files.append(self.charter_path.as_posix())
        files.extend(self.project_docs)
        if extra:
            for item in extra:
                path = Path(item).resolve()
                if path.exists():
                    files.append(path.as_posix())
        # Preserve order while removing duplicates
        seen = set()
        unique: List[str] = []
        for path in files:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return unique

__all__ = ["PenguinAgent"]
