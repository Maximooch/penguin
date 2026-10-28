"""Opt-in ACP routing over independent root runtime instances."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from acp import RequestError
from acp.schema import DeleteSessionRequest, PromptRequest

from penguin.core_runtime.isolation import RuntimeServices
from penguin.integrations.acp.server import PenguinACPAgent


@dataclass
class Runtime:
    agent: PenguinACPAgent
    services: RuntimeServices


class IsolatedACPAgent:
    """One mutable core per root, with bounded lifetime and shared atomic storage.

    Creation is serialized; prompts in different roots are independent. Closed
    roots with unresolved background work remain allocated; idle closed roots
    release their runtime and reconstruct from saved state on load.
    """

    def __init__(self, catalog: Runtime, factory: Callable, *, limit: int = 16):
        if not catalog.agent._registry.available:
            raise ValueError("Isolated ACP sessions require native persistence")
        self.catalog, self.factory, self.limit = catalog, factory, limit
        self.roots: dict[str, Runtime] = {}
        self._allocation = asyncio.Lock()
        self._connection = None
        self._transport = None
        self._initialization = None
        self._closed = False

    def on_connect(self, conn):
        self._connection = conn
        self.catalog.agent.on_connect(conn)

    async def initialize(
        self, protocol_version, client_capabilities=None, client_info=None, **kwargs
    ):
        if self._initialization is not None:
            raise RequestError.invalid_request({"reason": "Already initialized"})
        self.catalog.agent._transport = self._transport
        with self.catalog.services.activate():
            response = await self.catalog.agent.initialize(
                protocol_version, client_capabilities, client_info, **kwargs
            )
        self._initialization = (
            protocol_version,
            client_capabilities,
            client_info,
            kwargs,
        )
        return response

    def _runtime(self, sid):
        runtime = self.roots.get(sid)
        if runtime is None:
            runtime = next(
                (r for r in self.roots.values() if sid in r.agent._children.children),
                None,
            )
        if runtime is None:
            raise RequestError.invalid_params(
                {"reason": "Unknown active isolated session; load it first"}
            )
        return runtime

    async def _allocate(self):
        if self._initialization is None or self._closed:
            raise RequestError.invalid_request({"reason": "Initialize first"})
        if len(self.roots) >= self.limit:
            raise RequestError.invalid_request(
                {
                    "reason": (
                        "Isolated runtime limit reached; close or delete "
                        "an idle session, or restart adapter"
                    )
                }
            )
        runtime = await self.factory()
        try:
            runtime.agent._transport = self._transport
            runtime.agent.on_connect(self._connection)
            with runtime.services.activate():
                await runtime.agent.initialize(
                    *self._initialization[:3], **self._initialization[3]
                )
            return runtime
        except BaseException:
            await self._dispose(runtime)
            raise

    async def new_session(
        self, cwd, mcp_servers=None, additional_directories=None, **kwargs
    ):
        async with self._allocation:
            runtime = await self._allocate()
            try:
                with runtime.services.activate():
                    response = await runtime.agent.new_session(
                        cwd,
                        mcp_servers=mcp_servers,
                        additional_directories=additional_directories,
                        **kwargs,
                    )
                if response.session_id in self.roots:
                    raise RequestError.internal_error(
                        {"reason": "Duplicate native session ID"}
                    )
                self.roots[response.session_id] = runtime
                return response
            except BaseException:
                await self._dispose(runtime)
                raise

    async def _restore(self, method, cwd, session_id, **kwargs):
        async with self._allocation:
            runtime = self.roots.get(session_id)
            fresh = runtime is None
            if fresh:
                runtime = await self._allocate()
            try:
                with runtime.services.activate():
                    response = await getattr(runtime.agent, method)(
                        cwd=cwd, session_id=session_id, **kwargs
                    )
                self.roots[session_id] = runtime
                return response
            except BaseException:
                if fresh:
                    await self._dispose(runtime)
                raise

    async def load_session(self, cwd, session_id, **kwargs):
        return await self._restore("load_session", cwd, session_id, **kwargs)

    async def resume_session(self, cwd, session_id, **kwargs):
        return await self._restore("resume_session", cwd, session_id, **kwargs)

    async def list_sessions(self, cwd=None, cursor=None, **kwargs):
        runtime = self.catalog
        with runtime.services.activate():
            store = runtime.agent._registry.store
            # The catalog never executes prompts; discard only its clean read
            # cache and reload the index under the native store's shared lock.
            with store._store_lock:
                store.session_index = store._load_or_create_index()
                store._saved_index = deepcopy(store.session_index)
                store.sessions.clear()
            return await runtime.agent.list_sessions(cwd=cwd, cursor=cursor, **kwargs)

    async def _call(self, method, session_id, **kwargs):
        runtime = self._runtime(session_id)
        with runtime.services.activate():
            return await getattr(runtime.agent, method)(session_id=session_id, **kwargs)

    async def prompt(self, session_id, prompt, **kwargs):
        return await self._call("prompt", session_id, prompt=prompt, **kwargs)

    async def cancel(self, session_id, **kwargs):
        return await self._call("cancel", session_id, **kwargs)

    async def set_session_mode(self, session_id, mode_id, **kwargs):
        return await self._call(
            "set_session_mode", session_id, mode_id=mode_id, **kwargs
        )

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        return await self._call(
            "set_config_option", session_id, config_id=config_id, value=value, **kwargs
        )

    async def close_session(self, session_id, **kwargs):
        async with self._allocation:
            runtime = self._runtime(session_id)
            response = await self._call("close_session", session_id, **kwargs)
            unresolved = any(
                sid == session_id and not state.get("completed")
                for (sid, _), state in runtime.agent._processes.states.items()
            )
            if not unresolved:
                self.roots.pop(session_id, None)
                await self._dispose(runtime)
            return response

    async def delete_session(self, session_id):
        async with self._allocation:
            runtime = self.roots.get(session_id)
            fresh = runtime is None
            if fresh:
                runtime = await self._allocate()
            try:
                with runtime.services.activate():
                    response = await runtime.agent.delete_session(session_id)
                self.roots.pop(session_id, None)
                await self._dispose(runtime)
                return response
            except BaseException:
                if fresh:
                    await self._dispose(runtime)
                raise

    async def _delete_request(self, params):
        request = DeleteSessionRequest.model_validate(params)
        return await self.delete_session(request.session_id)

    async def _prompt_request(self, params):
        request = PromptRequest.model_validate(params)
        return await self.prompt(request.session_id, request.prompt)

    async def _cancel_prompt_request(self, params, task):
        request = PromptRequest.model_validate(params)
        runtime = self._runtime(request.session_id)
        with runtime.services.activate():
            return await runtime.agent._cancel_prompt_request(params, task)

    async def _send_commands(self, sid):
        runtime = self._runtime(sid)
        with runtime.services.activate():
            return await runtime.agent._send_commands(sid)

    async def _dispose(self, runtime):
        with runtime.services.activate():
            tasks = []
            for sid, session in runtime.agent.sessions.items():
                if (
                    session.task is not None
                    and session.task is not asyncio.current_task()
                ):
                    tasks.append(session.task)
                    await runtime.agent.cancel(sid)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            runtime.agent.close()
            from penguin.multi.executor import get_executor

            executor = get_executor()
            if executor is not None:
                await executor.shutdown()
            manager = getattr(runtime.agent.core, "tool_manager", None)
            shutdown_agents = getattr(manager, "shutdown_background_agents", None)
            if callable(shutdown_agents):
                await shutdown_agents()
            process_tools = getattr(manager, "_process_tools", None)
            if process_tools is not None:
                await asyncio.to_thread(process_tools.close)
            else:
                process_runtime = getattr(manager, "_process_runtime", None)
                if process_runtime is not None:
                    await asyncio.to_thread(process_runtime.cleanup)
            pool = runtime.services.values.get("connection_pool")
            if pool is not None:
                await pool.close_all()
            store = runtime.agent._registry.store
            stopper = getattr(store, "_stop_auto_save", None)
            if stopper is not None:
                stopper.set()
                thread = getattr(store, "_auto_save_thread", None)
                if thread is not None:
                    await asyncio.to_thread(thread.join, 1)

    async def aclose(self):
        self._closed = True
        for runtime in [*self.roots.values(), self.catalog]:
            await self._dispose(runtime)
        self.roots.clear()
