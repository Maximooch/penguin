"""Prompt and output-style compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging

from penguin.system_prompt import (
    get_system_prompt,
    normalize_prompt_mode,
    normalize_work_mode,
)

from . import prompt_settings as core_prompt_settings

__all__ = ["PromptCoreFacade"]

logger = logging.getLogger("penguin.core")


class PromptCoreFacade:
    """Compatibility methods for prompt mode and output style settings."""

    def set_prompt_mode(self, mode: str) -> str:
        """Rebuild and set the system prompt using the prompt builder mode."""
        return core_prompt_settings.set_prompt_mode(
            self,
            mode,
            get_system_prompt=get_system_prompt,
            normalize_prompt_mode=normalize_prompt_mode,
            logger=logger,
        )

    def get_prompt_mode(self) -> str:
        """Return current prompt mode name."""
        return core_prompt_settings.get_prompt_mode(self)

    def set_work_mode(self, mode: str) -> str:
        """Set task intent without changing personality or response style."""

        return core_prompt_settings.set_work_mode(
            self,
            mode,
            get_system_prompt=get_system_prompt,
            normalize_work_mode=normalize_work_mode,
            logger=logger,
        )

    def get_work_mode(self) -> str:
        """Return the current task-intent mode."""

        return core_prompt_settings.get_work_mode(self)

    def set_output_style(self, style: str) -> str:
        """Set output formatting style and rebuild system prompt."""
        from penguin.prompt.builder import set_output_formatting

        return core_prompt_settings.set_output_style(
            self,
            style,
            get_system_prompt=get_system_prompt,
            set_output_formatting=set_output_formatting,
            logger=logger,
        )

    def get_output_style(self) -> str:
        """Return current output formatting style."""
        return core_prompt_settings.get_output_style(self)

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt for both core and API client."""
        core_prompt_settings.set_core_system_prompt(self, prompt)
