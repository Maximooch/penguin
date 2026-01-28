
"""
Journal CLI Commands for Penguin 247 System
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Any, Dict

from penguin.cli.commands import registry, CommandCategory
from penguin.system.journal_manager import JournalManager

logger = logging.getLogger(__name__)


@registry.register(
    "journal",
    CommandCategory.CONTEXT,
    "Manage session journals",
    usage="/journal [today|yesterday|last N|search QUERY|read DATE]"
)
async def journal_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """
    Manage daily session journals.

    Commands:
        /journal today              - Show today's journal
        /journal yesterday          - Show yesterday's journal
        /journal last N             - Show last N entries from today
        /journal read YYYY-MM-DD    - Read specific date
        /journal search QUERY       - Search across all journals
        /journal list               - List available journal dates
    """
    try:
        # Get journal manager from core
        journal_manager = getattr(core.conversation_manager.conversation, 'journal_manager', None)

        if not journal_manager:
            # Try to initialize one
            import os
            project_root = Path(os.getcwd())
            session_id = getattr(core.conversation_manager.conversation.session, 'id', 'unknown')

            journal_manager = JournalManager(
                project_root=project_root,
                session_id=session_id,
                agent_id="main"
            )

        if not args:
            # Default: show today's last 20 entries
            entries = journal_manager.read_last_entries(count=20)
            return _format_journal_output("Today's Journal (Last 20 entries)", entries)

        command = args[0].lower()

        if command == "today":
            entries = journal_manager.read_last_entries(count=50)
            return _format_journal_output("Today's Journal", entries)

        elif command == "yesterday":
            yesterday = (datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            entries = journal_manager.read_date(yesterday)
            return _format_journal_output(f"Journal for {yesterday}", entries)

        elif command == "last" and len(args) > 1:
            try:
                count = int(args[1])
                entries = journal_manager.read_last_entries(count=count)
                return _format_journal_output(f"Last {count} Entries", entries)
            except ValueError:
                return {"error": f"Invalid number: {args[1]}"}

        elif command == "read" and len(args) > 1:
            date_str = args[1]
            entries = journal_manager.read_date(date_str)
            if entries:
                return _format_journal_output(f"Journal for {date_str}", entries)
            else:
                return {"status": f"No journal entries found for {date_str}"}

        elif command == "search" and len(args) > 1:
            query = " ".join(args[1:])
            results = journal_manager.search(query)
            return _format_search_results(query, results)

        elif command == "list":
            dates = journal_manager.list_available_dates()
            if dates:
                output = "**Available Journal Dates:**\n\n"
                for date in dates[-20:]:  # Last 20 dates
                    output += f"  • {date}\n"
                return {"status": output}
            else:
                return {"status": "No journals found"}

        else:
            return {
                "error": f"Unknown command: {command}",
                "usage": "/journal [today|yesterday|last N|read DATE|search QUERY|list]"
            }

    except Exception as e:
        logger.error(f"Journal command failed: {e}")
        return {"error": f"Journal command failed: {str(e)}"}


def _format_journal_output(title: str, entries: list) -> Dict[str, Any]:
    """Format journal entries for display."""
    if not entries:
        return {"status": f"{title}\n\nNo entries found."}

    output = f"**{title}**\n\n"

    for entry in entries:
        time_str = entry.timestamp.split("T")[1][:5] if "T" in entry.timestamp else "???"
        output += f"**[{time_str}]** ({entry.entry_type})\n"
        output += f"{entry.content[:200]}"
        if len(entry.content) > 200:
            output += "..."
        output += "\n\n"

    return {"status": output}


def _format_search_results(query: str, results: list) -> Dict[str, Any]:
    """Format search results for display."""
    if not results:
        return {"status": f'No results found for "{query}"'}

    output = f'**Search Results for "{query}"**\n\n'

    for result in results[:20]:  # Limit to 20 results
        output += f"**{result['date']}** - {result['entry_type']}\n"
        output += f"{result['content']}\n\n"

    return {"status": output}
