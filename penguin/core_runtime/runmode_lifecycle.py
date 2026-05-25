"""RunMode lifecycle helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["start_run_mode"]


async def start_run_mode(
    owner: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    context: dict[str, Any] | None = None,
    continuous: bool = False,
    time_limit: int | None = None,
    mode_type: str = "task",
    stream_callback_for_cli: Callable[[str], Awaitable[None]] | None = None,
    ui_update_callback_for_cli: Callable[[], Awaitable[None]] | None = None,
    run_mode_factory: Callable[..., Any],
    log_error: Callable[..., None],
    logger: Any,
) -> None:
    """Start and clean up RunMode against a core-like owner."""
    owner._ui_update_callback = ui_update_callback_for_cli
    owner._runmode_stream_callback = owner._prepare_runmode_stream_callback(
        stream_callback_for_cli
    )
    owner._runmode_active = True
    owner.current_runmode_status_summary = "Starting RunMode..."

    run_mode = None
    try:
        run_mode = run_mode_factory(
            owner,
            time_limit=time_limit,
            event_callback=owner._handle_run_mode_event,
        )
        owner.run_mode = run_mode
        owner._continuous_mode = continuous

        if continuous:
            project_id = (
                (context or {}).get("project_id") if mode_type == "project" else None
            )
            await run_mode.start_continuous(
                specified_task_name=None if project_id else name,
                task_description=None if project_id else description,
                project_id=project_id,
            )
        else:
            await run_mode.start(name=name, description=description, context=context)

    except Exception as exc:
        owner._continuous_mode = False
        log_error(
            exc,
            context={
                "component": "core",
                "method": "start_run_mode",
                "task_name": name,
                "description": description,
            },
        )
        owner.current_runmode_status_summary = f"Error starting RunMode: {exc!s}"

        if owner._ui_update_callback:
            try:
                await owner._ui_update_callback()
            except Exception as callback_err:
                logger.error(f"Error in UI update callback: {callback_err}")

        raise

    finally:
        owner._runmode_active = False
        owner._runmode_stream_callback = None
        owner.run_mode = None
        owner._ui_update_callback = None

        if run_mode is None:
            owner._continuous_mode = False
        elif hasattr(run_mode, "continuous_mode") and not run_mode.continuous_mode:
            owner._continuous_mode = False

        logger.info(
            f"Exiting start_run_mode. Core _continuous_mode: {owner._continuous_mode}"
        )
