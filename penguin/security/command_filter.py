"""Command filtering for safe execution in restricted permission modes.

This module provides command parsing and validation to allow safe execute
operations in read_only mode. It blocks destructive commands while allowing
read-only operations like grep, find, cat, etc.

Usage:
    from penguin.security.command_filter import is_command_safe, CommandFilterResult

    result = is_command_safe("grep -r 'pattern' src/")
    if result.allowed:
        # execute command
    else:
        # deny with result.reason
"""

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, Tuple


class CommandRisk(Enum):
    """Risk level of a command."""
    SAFE = "safe"           # Allowed in read_only mode
    DANGEROUS = "dangerous" # Blocked - destructive operation
    UNKNOWN = "unknown"     # Not in allowlist - blocked by default


@dataclass
class CommandFilterResult:
    """Result of command safety check."""
    allowed: bool
    risk: CommandRisk
    reason: str
    blocked_segment: Optional[str] = None  # Which part of a chain was blocked


# =============================================================================
# SAFE COMMAND ALLOWLIST
# =============================================================================

# Commands that only read data - safe in read_only mode
SAFE_READ_COMMANDS: Set[str] = {
    # File reading
    "cat", "head", "tail", "less", "more", "bat",

    # Searching
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "ripgrep",

    # Finding files
    "find", "fd", "locate", "which", "whereis", "type",

    # Listing / directory info
    "ls", "ll", "la", "tree", "exa", "eza", "lsd", "du", "df", "stat",

    # Text processing (read-only)
    "wc", "sort", "uniq", "diff", "comm", "cut", "awk", "sed",
    "tr", "column", "fold", "fmt", "nl", "tac", "rev",
    "paste", "join", "expand", "unexpand",

    # JSON/YAML processing
    "jq", "yq",

    # Archive listing (not extraction)
    "zipinfo", "tar", "unzip",  # Will check flags

    # System info (read-only)
    "echo", "printf", "pwd", "whoami", "date", "cal",
    "env", "printenv", "uname", "hostname", "id",
    "uptime", "free", "top", "htop", "ps", "pgrep",

    # Development tools (read-only operations)
    "python", "python3", "node", "ruby",  # Will check for -c with safe commands
    "file", "strings", "xxd", "hexdump", "od",
    "md5sum", "sha256sum", "shasum",
    "wc", "expr", "bc", "seq",

    # Network info (read-only)
    "ping", "traceroute", "dig", "nslookup", "host", "whois",
    "curl", "wget", "http",  # Will check flags for write operations

    # Version checks
    "git", "npm", "pip", "cargo", "go", "ruby", "python",
}

# Git subcommands that are safe (read-only)
SAFE_GIT_SUBCOMMANDS: Set[str] = {
    "log", "show", "diff", "status", "branch", "tag",
    "describe", "shortlog", "blame", "annotate",
    "ls-files", "ls-tree", "ls-remote",
    "rev-parse", "rev-list", "cat-file",
    "config", "remote",  # Reading config/remotes is safe
    "stash list",  # Listing stashes is safe
    "reflog",
    "grep", "log", "whatchanged",
}

# Git subcommands that modify state - BLOCKED
DANGEROUS_GIT_SUBCOMMANDS: Set[str] = {
    "push", "commit", "merge", "rebase", "reset",
    "checkout", "switch", "restore",
    "add", "rm", "mv",
    "clean", "gc", "prune",
    "pull", "fetch",  # Fetch modifies refs
    "cherry-pick", "revert",
    "stash push", "stash pop", "stash drop", "stash apply",
    "branch -d", "branch -D", "branch -m",
    "tag -d",
    "init", "clone",
}

# Dangerous commands - always blocked
DANGEROUS_COMMANDS: Set[str] = {
    # File modification
    "rm", "rmdir", "unlink", "shred",
    "mv", "cp", "install",
    "touch", "mkdir", "mkfifo", "mknod",

    # Permissions
    "chmod", "chown", "chgrp", "chattr",

    # Links
    "ln",

    # Editors (can modify files)
    "vim", "vi", "nano", "emacs", "ed",  # Editors can modify files
    "code", "subl", "atom",

    # Privilege escalation
    "sudo", "su", "doas", "pkexec",

    # Process control
    "kill", "pkill", "killall", "xkill",

    # System modification
    "mount", "umount", "mkfs", "fdisk", "parted",
    "systemctl", "service", "init",

    # Package managers
    "apt", "apt-get", "yum", "dnf", "pacman", "brew",
    "pip install", "npm install", "cargo install",

    # Network modification
    "iptables", "ufw", "firewall-cmd",

    # Other dangerous
    "dd", "format", "shutdown", "reboot", "halt",
}

# Dangerous patterns in command strings
DANGEROUS_PATTERNS: List[str] = [
    r">",           # Redirect (overwrite)
    r">>",          # Redirect (append)
    r"\$\(",        # Command substitution $(...)
    r"`",           # Backtick command substitution
    r"\$\{",        # Variable expansion with commands
    r";\s*rm",      # Chained rm
    r"&&\s*rm",     # Conditional rm
    r"\|\|\s*rm",   # Conditional rm
]

# Dangerous flags for otherwise safe commands
DANGEROUS_FLAGS: dict = {
    "curl": {"-o", "-O", "--output", "-w", "--write-out"},
    "wget": {"-O", "--output-document", "-P", "--directory-prefix"},
    "tar": {"-x", "--extract", "-c", "--create", "-r", "--append"},
    "unzip": {"-o", "-d"},  # Extract flags
    "sed": {"-i", "--in-place"},
    "awk": {"-i"},  # In-place editing (gawk)
    "python": {"-c"},  # Will need to check the -c argument
    "python3": {"-c"},
    "node": {"-e", "--eval"},
    "ruby": {"-e"},
}


# =============================================================================
# COMMAND PARSING
# =============================================================================

def _split_command_chain(command: str) -> List[str]:
    """Split a command string into individual commands (pipes, semicolons, &&, ||).

    Returns list of individual command strings.
    """
    # First, check for dangerous patterns that we block entirely
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return []  # Return empty to trigger block

    # Split on pipe, semicolon, &&, ||
    # This is a simplified split - doesn't handle all edge cases
    segments = re.split(r'\s*(?:\||\|\||&&|;)\s*', command)

    return [seg.strip() for seg in segments if seg.strip()]


def _parse_command(command_str: str) -> Tuple[str, List[str]]:
    """Parse a command string into base command and arguments.

    Returns (base_command, arguments)
    """
    try:
        parts = shlex.split(command_str)
    except ValueError:
        # shlex couldn't parse - treat as single command
        parts = command_str.split()

    if not parts:
        return "", []

    return parts[0], parts[1:]


def _check_git_command(args: List[str]) -> CommandFilterResult:
    """Check if a git command is safe.

    Args should be the arguments after 'git', e.g., ['log', '--oneline']
    """
    if not args:
        # Just 'git' with no subcommand - safe (shows help)
        return CommandFilterResult(True, CommandRisk.SAFE, "git help is safe")

    subcommand = args[0]

    # Check for dangerous subcommands (including compound ones like "stash pop")
    if len(args) > 1:
        compound = f"{subcommand} {args[1]}"
        if compound in DANGEROUS_GIT_SUBCOMMANDS:
            return CommandFilterResult(
                False, CommandRisk.DANGEROUS,
                f"git {compound} modifies repository state",
                blocked_segment=f"git {compound}"
            )

    if subcommand in DANGEROUS_GIT_SUBCOMMANDS:
        return CommandFilterResult(
            False, CommandRisk.DANGEROUS,
            f"git {subcommand} modifies repository state",
            blocked_segment=f"git {subcommand}"
        )

    if subcommand in SAFE_GIT_SUBCOMMANDS:
        return CommandFilterResult(True, CommandRisk.SAFE, f"git {subcommand} is read-only")

    # Unknown git subcommand - block by default
    return CommandFilterResult(
        False, CommandRisk.UNKNOWN,
        f"git {subcommand} is not in safe subcommands list",
        blocked_segment=f"git {subcommand}"
    )


def _check_single_command(command_str: str) -> CommandFilterResult:
    """Check if a single command (no pipes/chains) is safe."""

    base_cmd, args = _parse_command(command_str)

    if not base_cmd:
        return CommandFilterResult(False, CommandRisk.UNKNOWN, "Empty command")

    # Get the actual command name (strip path if present)
    cmd_name = base_cmd.split("/")[-1]

    # Check explicit dangerous commands
    if cmd_name in DANGEROUS_COMMANDS:
        return CommandFilterResult(
            False, CommandRisk.DANGEROUS,
            f"'{cmd_name}' is a dangerous command",
            blocked_segment=command_str
        )

    # Special handling for git
    if cmd_name == "git":
        return _check_git_command(args)

    # Check if command is in safe list
    if cmd_name not in SAFE_READ_COMMANDS:
        return CommandFilterResult(
            False, CommandRisk.UNKNOWN,
            f"'{cmd_name}' is not in the safe commands allowlist",
            blocked_segment=command_str
        )

    # Check for dangerous flags
    if cmd_name in DANGEROUS_FLAGS:
        dangerous = DANGEROUS_FLAGS[cmd_name]
        for arg in args:
            # Check both short and long flags
            flag = arg.split("=")[0]  # Handle --flag=value

            # Direct match
            if flag in dangerous:
                return CommandFilterResult(
                    False, CommandRisk.DANGEROUS,
                    f"'{cmd_name}' with '{flag}' can modify files",
                    blocked_segment=command_str
                )

            # Check for combined short flags like -xf (contains -x)
            if flag.startswith("-") and not flag.startswith("--"):
                for d in dangerous:
                    # Match single-char flags within combined flags
                    if d.startswith("-") and len(d) == 2:
                        char = d[1]
                        if char in flag[1:]:  # Check if char is in the flags after -
                            return CommandFilterResult(
                                False, CommandRisk.DANGEROUS,
                                f"'{cmd_name}' with '{d}' (in '{flag}') can modify files",
                                blocked_segment=command_str
                            )

    return CommandFilterResult(True, CommandRisk.SAFE, f"'{cmd_name}' is a safe read command")


# =============================================================================
# PUBLIC API
# =============================================================================

def is_command_safe(command: str) -> CommandFilterResult:
    """Check if a command string is safe for read_only mode.

    Parses the command, handles pipes/chains, and validates each segment.

    Args:
        command: The full command string to check

    Returns:
        CommandFilterResult with allowed status and reason
    """
    if not command or not command.strip():
        return CommandFilterResult(False, CommandRisk.UNKNOWN, "Empty command")

    command = command.strip()

    # Check for dangerous patterns first (before splitting)
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            match = re.search(pattern, command)
            return CommandFilterResult(
                False, CommandRisk.DANGEROUS,
                f"Command contains dangerous pattern: {pattern}",
                blocked_segment=match.group() if match else pattern
            )

    # Split into chain segments
    segments = _split_command_chain(command)

    if not segments:
        return CommandFilterResult(
            False, CommandRisk.DANGEROUS,
            "Command contains dangerous patterns or syntax"
        )

    # Check each segment
    for segment in segments:
        result = _check_single_command(segment)
        if not result.allowed:
            return result

    return CommandFilterResult(
        True, CommandRisk.SAFE,
        f"All {len(segments)} command(s) in chain are safe"
    )


def get_safe_commands_summary() -> dict:
    """Return a summary of safe commands for documentation/display."""
    return {
        "safe_commands": sorted(SAFE_READ_COMMANDS),
        "safe_git_subcommands": sorted(SAFE_GIT_SUBCOMMANDS),
        "dangerous_commands": sorted(DANGEROUS_COMMANDS),
        "dangerous_git_subcommands": sorted(DANGEROUS_GIT_SUBCOMMANDS),
    }
