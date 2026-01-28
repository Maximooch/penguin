
"""
Journal 247 System - Phase 1 (Manual)
Manages daily session logs with YAML frontmatter.
"""

import os
import re
import yaml
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JournalEntry:
    """Represents a single journal entry."""
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
    """Manages daily journal files in context/journal/."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.journal_dir = self.project_root / "context" / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        self.today_file = self.journal_dir / f"{today}.md"

    def write_entry(
        self,
        content: str,
        entry_type: str = "note",
        session_id: str = "manual",
        agent_id: str = "penguin",
        tokens: int = 0
    ) -> bool:
        """Manually write a journal entry."""
        try:
            entry = JournalEntry(
                timestamp=datetime.now().isoformat(),
                entry_type=entry_type,
                session_id=session_id,
                agent_id=agent_id,
                tokens=tokens,
                content=content
            )

            with open(self.today_file, 'a', encoding='utf-8') as f:
                f.write(entry.to_yaml_frontmatter())
                f.flush()
                os.fsync(f.fileno())

            return True
        except Exception as e:
            logger.error(f"Failed to write journal: {e}")
            return False

    def read_last_entries(self, count: int = 50) -> List[JournalEntry]:
        """Read last N entries from today's journal."""
        if not self.today_file.exists():
            return []

        try:
            with open(self.today_file, 'r', encoding='utf-8') as f:
                content = f.read()

            entries = []
            pattern = r'---\s*\n(.*?)\n---\s*\n(.*?)\n(?=---|$)'

            for match in re.finditer(pattern, content, re.DOTALL):
                try:
                    metadata = yaml.safe_load(match.group(1))
                    entries.append(JournalEntry(
                        timestamp=metadata.get('timestamp', ''),
                        entry_type=metadata.get('entry_type', 'unknown'),
                        session_id=metadata.get('session_id', ''),
                        agent_id=metadata.get('agent_id', 'main'),
                        tokens=metadata.get('tokens', 0),
                        content=match.group(2).strip()
                    ))
                except Exception:
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
                try:
                    metadata = yaml.safe_load(match.group(1))
                    entries.append(JournalEntry(
                        timestamp=metadata.get('timestamp', ''),
                        entry_type=metadata.get('entry_type', 'unknown'),
                        session_id=metadata.get('session_id', ''),
                        agent_id=metadata.get('agent_id', 'main'),
                        tokens=metadata.get('tokens', 0),
                        content=match.group(2).strip()
                    ))
                except Exception:
                    continue

            return entries
        except Exception as e:
            logger.error(f"Failed to read journal: {e}")
            return []

    def list_dates(self) -> List[str]:
        """List all available journal dates."""
        try:
            return sorted([f.stem for f in self.journal_dir.glob("*.md")])
        except Exception as e:
            logger.error(f"Failed to list journals: {e}")
            return []

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search across all journals."""
        results = []
        for journal_file in sorted(self.journal_dir.glob("*.md")):
            entries = self.read_date(journal_file.stem)
            for entry in entries:
                if query.lower() in entry.content.lower():
                    results.append({
                        'date': journal_file.stem,
                        'timestamp': entry.timestamp,
                        'entry_type': entry.entry_type,
                        'content': entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
                    })
        return results
