"""
Shared command parsing utilities for both CLI and TUI.

This module wraps `CommandRegistry` to provide:
  - Robust parsing (multi-word command names, quoted args with shlex)
  - Minimal validation for required parameters and types
  - Usage/Help text per command
  - Suggestions for partial inputs

Intended usage:
  - TUI: route slash commands through `parse()` then delegate to Interface
  - CLI: for commands forwarded as strings, use `parse()` to normalize and validate

NOTE: This layer does not execute commands. It only parses and validates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import shlex

from .command_registry import CommandRegistry, Command, CommandParameter


@dataclass
class ParsedCommand:
    name: str
    handler: str
    args: Dict[str, Any]
    original: str


@dataclass
class ParseError:
    message: str
    usage: Optional[str] = None
    suggestions: Optional[List[str]] = None


class SharedParser:
    """A thin facade over CommandRegistry with stricter validation and usage text."""

    def __init__(self, registry: Optional[CommandRegistry] = None):
        self.registry = registry or CommandRegistry()

    def suggest(self, partial: str) -> List[str]:
        return self.registry.get_suggestions(partial)

    def parse(self, input_str: str) -> Tuple[Optional[ParsedCommand], Optional[ParseError]]:
        """Parse a slash-style command string into a ParsedCommand or a ParseError.

        Accepts either "/cmd sub ..." or "cmd sub ...". Quoted args are supported.
        """
        raw = (input_str or "").strip()
        if not raw:
            return None, ParseError("Empty command.", usage=self.get_global_help())

        # Normalize leading slash
        if raw.startswith("/"):
            raw = raw[1:]

        # Use registry's token-aware longest prefix match
        cmd, args_dict = self.registry.parse_input(raw)
        if not cmd:
            return None, ParseError(
                f"Unknown command: {input_str.strip()}",
                usage=self.get_global_help(),
                suggestions=self.suggest(input_str),
            )

        # Validate required params and coerce types via shlex-split on remainder
        error = self._validate_command(cmd, args_dict)
        if error:
            return None, error

        return ParsedCommand(name=cmd.name, handler=cmd.handler or "", args=args_dict, original=input_str), None

    # ----------------------- helpers -----------------------
    def _validate_command(self, command: Command, args: Dict[str, Any]) -> Optional[ParseError]:
        missing: List[str] = []
        type_errors: List[str] = []

        for p in command.parameters or []:
            if p.required and (p.name not in args or args[p.name] in (None, "")):
                missing.append(p.name)
                continue
            if p.name in args and args[p.name] not in (None, ""):
                val = args[p.name]
                if p.type == "int":
                    try:
                        args[p.name] = int(val)  # coerce
                    except Exception:
                        type_errors.append(f"{p.name}=<int>")
                elif p.type == "bool":
                    args[p.name] = str(val).lower() in ("1", "true", "yes", "on")
                # strings and other types pass-through

        if missing or type_errors:
            usage = self.usage_for(command)
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing: {', '.join(missing)}")
            if type_errors:
                msg_parts.append(f"Type errors: {', '.join(type_errors)}")
            return ParseError("; ".join(msg_parts), usage=usage)
        return None

    def usage_for(self, command: Command) -> str:
        parts: List[str] = [f"/{command.name}"]
        for p in command.parameters or []:
            token = f"<{p.name}>" if p.required else f"[{p.name}]"
            parts.append(token)
        usage_line = " ".join(parts)
        detail: List[str] = [usage_line, ""]
        if command.parameters:
            for p in command.parameters:
                req = "required" if p.required else "optional"
                detail.append(f"  - {p.name}: {p.type}, {req}. {p.description or ''}")
        return "\n".join(detail)

    def get_global_help(self) -> str:
        return self.registry.get_help_text()


# Convenience function for quick use without instantiating
_GLOBAL = SharedParser()

def parse(command_str: str) -> Tuple[Optional[ParsedCommand], Optional[ParseError]]:
    return _GLOBAL.parse(command_str)

def suggest(partial: str) -> List[str]:
    return _GLOBAL.suggest(partial)

def usage_for(command_name: str) -> str:
    cmd = _GLOBAL.registry.find_command(command_name)
    return _GLOBAL.usage_for(cmd) if cmd else _GLOBAL.get_global_help()


