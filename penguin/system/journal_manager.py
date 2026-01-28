
"""
Journal 247 System - Phase 1 Implementation
Manages daily session logs with YAML frontmatter metadata.
"""

import os
import re
import yaml
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JournalEntry:
    """Represents a single journal entry with metadata."""
    timestamp: str
    entry_type: str
    session_id: str
    agent_id: str
    tokens: int
    content: str

    def to_yaml_frontmatter(self) -> str:
        """Convert to YAML frontmatter format."""
        metadata = {
            'timestamp': self.timestamp,
            'entry_type': self.entry_type,
            'session_id': self.session_id,
            'agent_id': self.agent_id,
            'tokens': self.tokens
        }

        yaml_str = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
        return f"---\n{yaml_str}---\n\n{self.content}\n"


class JournalManager:
    """
    Manages daily journal files for Penguin sessions.

    Journals are stored in context/journal/YYYY-MM-DD.md with YAML frontmatter.
    """

    def __init__(self, project_root: Path, session_id: str, agent_id: str = "main"):
        """
        Initialize the journal manager.

        Args:
            project_root: Root directory of the current project
            session_id: Unique identifier for this session
            agent_id: Identifier for the agent (default: "main")
        """
        self.project_root = Path(project_root)
        self.session_id = session_id
        self.agent_id = agent_id

        # Journal directory is in context/journal/
        self.journal_dir = self.project_root / "context" / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        # Today's journal file
        today = datetime.now().strftime("%Y-%m-%d")
        self.today_file = self.journal_dir / f"{today}.md"

        logger.info(f"JournalManager initialized: {self.today_file}")

    def write_entry(self, content: str, entry_type: str = "chat_message", tokens: int = 0) -> bool:
        """Write a journal entry."""
        try:
            entry = JournalEntry(
                timestamp=datetime.now().isoformat(),
                entry_type=entry_type,
                session_id=self.session_id,
                agent_id=self.agent_id,
                tokens=tokens,
                content=content
            )

            with open(self.today_file, 'a', encoding='utf-8') as f:
                f.write(entry.to_yaml_frontmatter())
                f.flush()
                os.fsync(f.fileno())

            logger.debug(f"Wrote journal entry: {entry_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to write journal entry: {e}")
            return False

    def read_last_entries(self, count: int = 50) -> List[JournalEntry]:
        """Read the last N entries from today's journal."""
        if not self.today_file.exists():
            return []

        try:
            with open(self.today_file, 'r', encoding='utf-8') as f:
                content = f.read()

            entries = []
            # Find all --- blocks
            pattern = r'---\s*\n(.*?)\n---\s*\n(.*?)\n(?=---|$)'

            for match in re.finditer(pattern, content, re.DOTALL):
                metadata_yaml = match.group(1)
                entry_content = match.group(2).strip()

                try:
                    metadata = yaml.safe_load(metadata_yaml)
                    entry = JournalEntry(
                        timestamp=metadata.get('timestamp', ''),
                        entry_type=metadata.get('entry_type', 'unknown'),
                        session_id=metadata.get('session_id', ''),
                        agent_id=metadata.get('agent_id', 'main'),
                        tokens=metadata.get('tokens', 0),
                        content=entry_content
                    )
                    entries.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to parse journal entry: {e}")
                    continue

            return entries[-count:] if len(entries) > count else entries

        except Exception as e:
            logger.error(f"Failed to read journal: {e}")
            return []

    def read_date(self, date_str: str) -> List[JournalEntry]:
        """Read all entries from a specific date."""
        journal_file = self.journal_dir / f"{date_str}.md"

        if not journal_file.exists():
            return []

        try:
            with open(journal_file, 'r', encoding='utf-8') as f:
                content = f.read()

            entries = []
            pattern = r'---\s*\n(.*?)\n---\s*\n(.*?)\n(?=---|$)'

            for match in re.finditer(pattern, content, re.DOTALL):
                metadata_yaml = match.group(1)
                entry_content = match.group(2).strip()

                try:
                    metadata = yaml.safe_load(metadata_yaml)
                    entry = JournalEntry(
                        timestamp=metadata.get('timestamp', ''),
                        entry_type=metadata.get('entry_type', 'unknown'),
                        session_id=metadata.get('session_id', ''),
                        agent_id=metadata.get('agent_id', 'main'),
                        tokens=metadata.get('tokens', 0),
                        content=entry_content
                    )
                    entries.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to parse journal entry: {e}")
                    continue

            return entries

        except Exception as e:
            logger.error(f"Failed to read journal for {date_str}: {e}")
            return []

    def list_available_dates(self) -> List[str]:
        """List all available journal dates."""
        try:
            files = sorted(self.journal_dir.glob("*.md"))
            return [f.stem for f in files]
        except Exception as e:
            logger.error(f"Failed to list journals: {e}")
            return []

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search across all journal entries."""
        results = []

        for journal_file in sorted(self.journal_dir.glob("*.md")):
            date_str = journal_file.stem
            entries = self.read_date(date_str)

            for entry in entries:
                if query.lower() in entry.content.lower():
                    results.append({
                        'date': date_str,
                        'timestamp': entry.timestamp,
                        'entry_type': entry.entry_type,
                        'content': entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
                    })

        return results
