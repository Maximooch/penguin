"""
Atomic Multi-File Edit Tool (LLM-friendly facade)

Parses a simple per-file block format and delegates actual patching to the
robust editors in penguin.tools.core.support. Supports dry-run previews,
transactional apply, and new-file creation via support.apply_unified_patch.
"""
import os
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import difflib
import re

@dataclass
class FileEdit:
    """Represents an edit to a single file"""
    file_path: str
    diff_content: str
    backup_path: Optional[str] = None
    applied: bool = False
    
@dataclass 
class MultiEditResult:
    """Result of a multi-file edit operation"""
    success: bool
    files_edited: List[str]
    files_failed: List[str] 
    error_messages: Dict[str, str]
    backup_paths: Dict[str, str]
    rollback_performed: bool = False

class MultiEdit:
    """
    Atomic multi-file editor with transactional semantics.
    All changes apply or none do (atomic).
    """
    
    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root).resolve()
        
    def parse_multiedit_block(self, multiedit_content: str) -> List[FileEdit]:
        """
        Parse multiedit block content into individual file edits.
        
        Expected format:
        file1.py:
        --- a/file1.py
        +++ b/file1.py
        @@ -10,2 +10,3 @@
         def hello():
        +    \"\"\"Say hello\"\"\"
             print("hello")
        
        file2.py:
        --- a/file2.py
        +++ b/file2.py
        ...
        """
        edits = []
        
        # Split by file sections (lines starting with filename and ending with colon)
        # Be generous: allow filenames without extensions and dotfiles
        sections = re.split(r'\n([^\n:]+):\n', multiedit_content.strip())
        
        # First section is empty/header, then alternating filenames and diffs
        for i in range(1, len(sections), 2):
            if i + 1 < len(sections):
                filename = sections[i].strip()
                diff_content = sections[i + 1].strip()
                
                # Resolve file path relative to workspace
                file_path = self.workspace_root / filename
                
                edits.append(FileEdit(
                    file_path=str(file_path),
                    diff_content=diff_content
                ))
        
        return edits
    
    def create_backups(self, edits: List[FileEdit]) -> bool:
        """Create backups for all files that will be modified"""
        for edit in edits:
            file_path = Path(edit.file_path)
            if file_path.exists():
                backup_path = f"{edit.file_path}.bak"
                counter = 1
                while Path(backup_path).exists():
                    backup_path = f"{edit.file_path}.bak.{counter}"
                    counter += 1
                try:
                    shutil.copy2(edit.file_path, backup_path)
                    edit.backup_path = backup_path
                except Exception as e:
                    print(f"Failed to create backup for {edit.file_path}: {e}")
                    return False
        return True
    
    def _build_unified_patch(self, edits: List[FileEdit]) -> str:
        """Construct a consolidated unified patch text from FileEdit blocks."""
        parts: List[str] = []
        for e in edits:
            # Ensure rel path from workspace root
            rel = str(Path(e.file_path))
            # If diff content already includes headers, keep as-is; otherwise wrap
            if re.search(r"^--- ", e.diff_content, flags=re.M):
                parts.append(e.diff_content if e.diff_content.endswith('\n') else e.diff_content + '\n')
            else:
                header = f"--- a/{rel}\n+++ b/{rel}\n"
                body = e.diff_content if e.diff_content.endswith('\n') else e.diff_content + '\n'
                parts.append(header + body)
        return "\n".join(parts)
    
    def rollback_changes(self, edits: List[FileEdit]) -> bool:
        """Rollback all changes by restoring from backups"""
        success = True
        
        for edit in edits:
            if edit.applied and edit.backup_path and Path(edit.backup_path).exists():
                try:
                    # Restore from backup
                    shutil.copy2(edit.backup_path, edit.file_path)
                    edit.applied = False
                except Exception as e:
                    print(f"Failed to rollback {edit.file_path}: {e}")
                    success = False
        
        return success
    
    def cleanup_backups(self, edits: List[FileEdit], keep_backups: bool = True):
        """Clean up backup files"""
        if keep_backups:
            return
            
        for edit in edits:
            if edit.backup_path and Path(edit.backup_path).exists():
                try:
                    os.remove(edit.backup_path)
                except Exception as e:
                    print(f"Warning: Failed to cleanup backup {edit.backup_path}: {e}")
    
    def apply_multiedit(self, multiedit_content: str, dry_run: bool = True) -> MultiEditResult:
        """
        Apply multi-file edits atomically.
        
        Args:
            multiedit_content: The multiedit block content
            dry_run: If True, only show what would be changed
            
        Returns:
            MultiEditResult with success status and details
        """
        # Parse the edits
        edits = self.parse_multiedit_block(multiedit_content)
        
        if not edits:
            return MultiEditResult(
                success=False,
                files_edited=[],
                files_failed=[],
                error_messages={"parse": "No valid file edits found in multiedit block"},
                backup_paths={}
            )
        
        if dry_run:
            # For dry-run, show previews using support.preview_unified_diff
            from penguin.tools.core.support import preview_unified_diff
            print("DRY RUN - Would apply the following changes:")
            for edit in edits:
                print(f"\n📁 {edit.file_path}")
                print(preview_unified_diff(edit.diff_content))
            return MultiEditResult(
                success=True,
                files_edited=[edit.file_path for edit in edits],
                files_failed=[],
                error_messages={},
                backup_paths={}
            )
        
        # Build a consolidated unified patch and delegate to support.apply_unified_patch
        from penguin.tools.core.support import apply_unified_patch
        unified_patch = self._build_unified_patch(edits)
        res = apply_unified_patch(unified_patch, workspace_path=str(self.workspace_root), backup=True, return_json=True)
        # The support function returns JSON on success or error string on failure
        files_edited: List[str] = []
        created: List[str] = []
        files_failed: List[str] = []
        error_messages: Dict[str, str] = {}
        try:
            import json
            parsed = json.loads(res)
            if isinstance(parsed, dict) and parsed.get("status") == "success":
                files_edited = [str(Path(p)) for p in parsed.get("files", [])]
                created = [str(Path(p)) for p in parsed.get("created", [])]
                return MultiEditResult(
                    success=True,
                    files_edited=files_edited,
                    files_failed=[],
                    error_messages={},
                    backup_paths={}
                )
        except Exception:
            # Non-JSON means an error string
            files_failed = [e.file_path for e in edits]
            error_messages = {"apply": res}
            return MultiEditResult(
                success=False,
                files_edited=files_edited,
                files_failed=files_failed,
                error_messages=error_messages,
                backup_paths={},
                rollback_performed=True
            )

# Global instance
_multiedit = MultiEdit()

def apply_multiedit(multiedit_content: str, dry_run: bool = True, workspace_root: str = ".") -> MultiEditResult:
    """
    Convenience function to apply multi-file edits.
    
    Args:
        multiedit_content: The multiedit block content  
        dry_run: If True, only show what would be changed
        workspace_root: Root directory for resolving relative paths
        
    Returns:
        MultiEditResult with success status and details
    """
    global _multiedit
    _multiedit.workspace_root = Path(workspace_root).resolve()
    return _multiedit.apply_multiedit(multiedit_content, dry_run)
