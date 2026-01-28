
"""
Journal CLI Commands - Manual journaling
"""

import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timedelta

from penguin.cli.commands import registry, CommandCategory
from penguin.system.journal_manager import JournalManager


@registry.register(
    "journal",
    CommandCategory.CONTEXT,
    "Manage daily journals manually",
    usage="/journal [today|yesterday|last N|read DATE|search QUERY|write TEXT|list]"
)
async def journal_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """
    Manual journal management.

    Commands:
        /journal today              - Show today's journal
        /journal yesterday          - Show yesterday's journal  
        /journal last N             - Show last N entries
        /journal read YYYY-MM-DD    - Read specific date
        /journal search QUERY       - Search all journals
        /journal write TEXT         - Write entry to today
        /journal list               - List available dates
    """
    try:
        project_root = Path(os.getcwd())
        journal_mgr = JournalManager(project_root)

        if not args:
            return {"error": "Missing subcommand. Use: today, yesterday, last, read, search, write, list"}

        cmd = args[0].lower()

        if cmd == "today":
            entries = journal_mgr.read_last_entries(50)
            return _format_entries("Today's Journal", entries)

        elif cmd == "yesterday":
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            entries = journal_mgr.read_date(yesterday)
            return _format_entries(f"Journal for {yesterday}", entries)

        elif cmd == "last" and len(args) > 1:
            try:
                n = int(args[1])
                entries = journal_mgr.read_last_entries(n)
                return _format_entries(f"Last {n} Entries", entries)
            except ValueError:
                return {"error": f"Invalid number: {args[1]}"}

        elif cmd == "read" and len(args) > 1:
            date_str = args[1]
            entries = journal_mgr.read_date(date_str)
            return _format_entries(f"Journal for {date_str}", entries)

        elif cmd == "search" and len(args) > 1:
            query = " ".join(args[1:])
            results = journal_mgr.search(query)
            return _format_search(query, results)

        elif cmd == "write" and len(args) > 1:
            text = " ".join(args[1:])
            success = journal_mgr.write_entry(
                content=text,
                entry_type="manual",
                session_id="cli"
            )
            if success:
                return {"status": f"Wrote to journal: {text[:50]}..."}
            return {"error": "Failed to write journal entry"}

        elif cmd == "list":
            dates = journal_mgr.list_dates()
            if dates:
                output = "**Available Journal Dates:**\n\n" + "\n".join([f"• {d}" for d in dates[-20:]])
                return {"status": output}
            return {"status": "No journals found"}

        else:
            return {"error": f"Unknown command: {cmd}"}

    except Exception as e:
        return {"error": f"Journal command failed: {str(e)}"}


def _format_entries(title: str, entries: list) -> Dict[str, Any]:
    if not entries:
        return {"status": f"{title}\n\nNo entries found."}

    output = f"**{title}**\n\n"
    for entry in entries:
        time = entry.timestamp.split("T")[1][:5] if "T" in entry.timestamp else "???"
        output += f"[{time}] ({entry.entry_type})\n{entry.content[:150]}\n\n"

    return {"status": output}


def _format_search(query: str, results: list) -> Dict[str, Any]:
    if not results:
        return {"status": f'No results for "{query}"'}

    output = f'**Search: "{query}"**\n\n'
    for r in results[:20]:
        output += f"**{r['date']}** ({r['entry_type']})\n{r['content']}\n\n"

    return {"status": output}
