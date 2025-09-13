"""
Context Contributors System - DISABLED FOR NOW
Implements smart context assembly with contributor ranking within existing CONTEXT category.
Phase 2 of prompting overhaul - minimal approach that extends existing ContextWindowManager.

STATUS: DISABLED - Engineering considerations need more time before shipping
"""

# Feature flag to disable the entire module
CONTEXT_CONTRIBUTORS_ENABLED = False

if not CONTEXT_CONTRIBUTORS_ENABLED:
    # Stub out the main functions when disabled
    def assemble_smart_context(*args, **kwargs):
        return "", {"error": "Context contributors system disabled", "status": "disabled"}
    
    def get_contributor_manager(*args, **kwargs):
        class DisabledManager:
            def assemble_context_content(self, *args, **kwargs):
                return "", {"error": "Context contributors system disabled", "status": "disabled"}
        return DisabledManager()
    
    # Early exit - don't load the rest of the module when disabled
    import sys
    sys.modules[__name__].__dict__.update(locals())

# Rest of the module code (disabled but preserved for future use)
if CONTEXT_CONTRIBUTORS_ENABLED:
    import os
    import logging
    from pathlib import Path
    from typing import Dict, List, Tuple, Optional, Any
    from dataclasses import dataclass
    from enum import Enum

    logger = logging.getLogger(__name__)

class ContributorType(Enum):
    """Types of context contributors"""
    WORKING_FILES = "working_files"
    PROJECT_DOCS = "project_docs" 
    RETRIEVAL = "retrieval"
    CODEBASE_MAP = "codebase_map"

@dataclass
class Contributor:
    """A context contributor with content and metadata"""
    type: ContributorType
    content: str
    weight: float
    salience_score: float = 0.0
    token_count: int = 0
    source_path: Optional[str] = None
    
    def __post_init__(self):
        if not self.token_count and self.content:
            # Rough estimate - will be updated by accurate counter
            self.token_count = len(self.content) // 4

@dataclass
class ContextContribution:
    """Result of contributor selection and ranking"""
    selected_contributors: List[Contributor]
    total_tokens: int
    tokens_by_type: Dict[ContributorType, int]
    overflow_contributors: List[Contributor]  # Contributors that didn't fit

class ContextContributorManager:
    """
    Manages context contributors within the existing CONTEXT category.
    Ranks and selects contributors based on salience and token budgets.
    """
    
    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root).resolve()
        
        # Default weights for contributor types (from roadmap)
        self.type_weights = {
            ContributorType.WORKING_FILES: 0.4,
            ContributorType.PROJECT_DOCS: 0.15,
            ContributorType.RETRIEVAL: 0.25,
            ContributorType.CODEBASE_MAP: 0.2
        }
        
    def create_project_docs_contributor(self) -> Optional[Contributor]:
        """Create contributor from project documentation files (PENGUIN.md, AGENTS.md, README.md)"""
        content_parts = []
        
        # Priority order: PENGUIN.md > AGENTS.md > README.md
        doc_files = [
            ("PENGUIN.md", "Project Instructions", 2400),  # 600 tokens worth
            ("AGENTS.md", "Agent Specifications", 2000),   # 500 tokens worth  
            ("README.md", "Project Overview", 1200)        # 300 tokens worth
        ]
        
        for filename, section_title, max_chars in doc_files:
            doc_path = self.workspace_root / filename
            if doc_path.exists():
                try:
                    with open(doc_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Limit content to prevent context overflow
                        if len(content) > max_chars:
                            content = content[:max_chars] + "\n... (truncated)"
                        content_parts.append(f"## {section_title} ({filename})\n{content}")
                        
                        # If we found PENGUIN.md or AGENTS.md, don't fall back to README  
                        if filename in ["PENGUIN.md", "AGENTS.md"]:
                            break
                            
                except Exception as e:
                    logger.warning(f"Failed to read {filename}: {e}")
        
        if content_parts:
            return Contributor(
                type=ContributorType.PROJECT_DOCS,
                content="\n\n".join(content_parts),
                weight=self.type_weights[ContributorType.PROJECT_DOCS],
                salience_score=1.0,  # Always relevant
                source_path=str(penguin_md if penguin_md.exists() else self.workspace_root / "README.md")
            )
        
        return None
    
    def create_working_files_contributor(self, touched_files: List[str], current_diff: Optional[str] = None) -> Optional[Contributor]:
        """Create contributor for working/touched files"""
        if not touched_files and not current_diff:
            return None
            
        content_parts = []
        
        # Add current diff if available
        if current_diff:
            content_parts.append(f"## Current Changes\n```diff\n{current_diff}\n```")
        
        # Add touched files summary (headers + signatures)
        for file_path in touched_files[:5]:  # Limit to 5 most recent
            try:
                path = Path(file_path)
                if path.exists() and path.is_file():
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        
                    # Include: file header + function/class signatures
                    summary_lines = []
                    in_multiline_comment = False
                    
                    for i, line in enumerate(lines[:50]):  # Only check first 50 lines
                        # Track multiline comments
                        if '"""' in line or "'''" in line:
                            in_multiline_comment = not in_multiline_comment
                            
                        # Include imports, class/function definitions, and key comments
                        if (line.strip().startswith(('import ', 'from ', 'class ', 'def ', '# ', 'interface ', 'function '))
                            or in_multiline_comment
                            or i < 10):  # Always include first 10 lines
                            summary_lines.append(line.rstrip())
                    
                    if summary_lines:
                        content_parts.append(f"## {path.name}\n```\n" + "\n".join(summary_lines) + "\n```")
                        
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")
        
        if content_parts:
            return Contributor(
                type=ContributorType.WORKING_FILES,
                content="\n\n".join(content_parts),
                weight=self.type_weights[ContributorType.WORKING_FILES],
                salience_score=1.0,  # Always high salience for working files
            )
        
        return None
    
    def create_retrieval_contributor(self, search_results: List[str]) -> Optional[Contributor]:
        """Create contributor from search/retrieval results"""
        if not search_results:
            return None
            
        # Convert search results to evidence bundles (path + quoted lines)
        evidence_bundles = []
        for result in search_results[:10]:  # Limit to top 10
            # Assume result format: "path:line_num:content" 
            if ':' in result:
                parts = result.split(':', 2)
                if len(parts) == 3:
                    path, line_num, content = parts
                    evidence_bundles.append(f"`{path}:{line_num}`: {content[:100]}{'...' if len(content) > 100 else ''}")
                else:
                    evidence_bundles.append(result[:150] + ('...' if len(result) > 150 else ''))
            else:
                evidence_bundles.append(result[:150] + ('...' if len(result) > 150 else ''))
        
        if evidence_bundles:
            content = "## Search Results\n" + "\n".join(f"- {bundle}" for bundle in evidence_bundles)
            return Contributor(
                type=ContributorType.RETRIEVAL,
                content=content,
                weight=self.type_weights[ContributorType.RETRIEVAL],
                salience_score=0.8,  # High relevance for search results
            )
        
        return None
    
    def create_codebase_map_contributor(self, file_tree: Optional[List[str]] = None) -> Optional[Contributor]:
        """Create contributor with basic codebase structure"""
        if file_tree:
            # Use provided file tree
            tree_content = "\n".join(file_tree[:30])  # Limit to 30 files
        else:
            # Generate basic file tree
            try:
                import os
                tree_lines = []
                for root, dirs, files in os.walk(self.workspace_root):
                    # Skip hidden and common ignored directories
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', '.git']]
                    
                    level = root.replace(str(self.workspace_root), '').count(os.sep)
                    indent = '  ' * level
                    tree_lines.append(f"{indent}{os.path.basename(root)}/")
                    
                    # Add files (limit per directory)
                    for file in files[:5]:  # Max 5 files per dir
                        if not file.startswith('.'):
                            tree_lines.append(f"{indent}  {file}")
                    
                    if len(tree_lines) > 50:  # Overall limit
                        tree_lines.append("  ... (truncated)")
                        break
                
                tree_content = "\n".join(tree_lines)
            except Exception as e:
                logger.warning(f"Failed to generate file tree: {e}")
                return None
        
        if tree_content:
            content = f"## Project Structure\n```\n{tree_content}\n```"
            return Contributor(
                type=ContributorType.CODEBASE_MAP,
                content=content,
                weight=self.type_weights[ContributorType.CODEBASE_MAP],
                salience_score=0.5,  # Moderate relevance
            )
        
        return None
    
    def calculate_salience(self, contributor: Contributor, current_task: Optional[str] = None, 
                          recent_files: Optional[List[str]] = None) -> float:
        """Calculate salience score for a contributor based on context"""
        base_score = contributor.salience_score
        
        # Boost score based on task relevance
        if current_task and contributor.content:
            task_keywords = current_task.lower().split()
            content_lower = contributor.content.lower()
            keyword_matches = sum(1 for keyword in task_keywords if keyword in content_lower)
            keyword_boost = min(0.3, keyword_matches * 0.1)
            base_score += keyword_boost
        
        # Boost working files that match recent activity
        if contributor.type == ContributorType.WORKING_FILES and recent_files:
            if contributor.source_path and any(Path(contributor.source_path).name in rf for rf in recent_files):
                base_score += 0.2
        
        # Recency boost for project docs (they're always somewhat relevant)
        if contributor.type == ContributorType.PROJECT_DOCS:
            base_score += 0.1
        
        return min(1.0, base_score)  # Cap at 1.0
    
    def select_contributors(self, available_contributors: List[Contributor], 
                          token_budget: int, token_counter) -> ContextContribution:
        """
        Select and rank contributors to fit within token budget.
        Uses salience scoring and type weights for selection.
        """
        if not available_contributors:
            return ContextContribution([], 0, {}, [])
        
        # Update token counts with accurate counter
        for contributor in available_contributors:
            contributor.token_count = token_counter(contributor.content)
        
        # Sort by combined score (weight * salience)
        def score_contributor(c: Contributor) -> float:
            return c.weight * c.salience_score
        
        sorted_contributors = sorted(available_contributors, key=score_contributor, reverse=True)
        
        # Select contributors that fit in budget
        selected = []
        total_tokens = 0
        tokens_by_type = {}
        overflow = []
        
        for contributor in sorted_contributors:
            if total_tokens + contributor.token_count <= token_budget:
                selected.append(contributor)
                total_tokens += contributor.token_count
                
                # Track tokens by type
                if contributor.type not in tokens_by_type:
                    tokens_by_type[contributor.type] = 0
                tokens_by_type[contributor.type] += contributor.token_count
            else:
                overflow.append(contributor)
        
        return ContextContribution(
            selected_contributors=selected,
            total_tokens=total_tokens,
            tokens_by_type=tokens_by_type,
            overflow_contributors=overflow
        )
    
    def assemble_context_content(self, 
                               touched_files: Optional[List[str]] = None,
                               current_diff: Optional[str] = None,
                               search_results: Optional[List[str]] = None,
                               file_tree: Optional[List[str]] = None,
                               current_task: Optional[str] = None,
                               token_budget: int = 50000,
                               token_counter = None) -> Tuple[str, Dict[str, Any]]:
        """
        Assemble context content from contributors within token budget.
        
        Returns:
            Tuple of (assembled_content, debug_info)
        """
        if token_counter is None:
            # Use simple fallback counter
            token_counter = lambda x: len(str(x)) // 4
        
        # Create all possible contributors
        contributors = []
        
        # Project docs (auto-load PENGUIN.md/README.md)
        project_docs = self.create_project_docs_contributor()
        if project_docs:
            contributors.append(project_docs)
        
        # Working files
        working_files = self.create_working_files_contributor(touched_files or [], current_diff)
        if working_files:
            contributors.append(working_files)
        
        # Retrieval results
        if search_results:
            retrieval = self.create_retrieval_contributor(search_results)
            if retrieval:
                contributors.append(retrieval)
        
        # Codebase map
        codebase_map = self.create_codebase_map_contributor(file_tree)
        if codebase_map:
            contributors.append(codebase_map)
        
        # Calculate salience scores
        for contributor in contributors:
            contributor.salience_score = self.calculate_salience(
                contributor, current_task, touched_files
            )
        
        # Select contributors within budget
        contribution = self.select_contributors(contributors, token_budget, token_counter)
        
        # Assemble final content
        content_parts = []
        for contributor in contribution.selected_contributors:
            content_parts.append(contributor.content)
        
        assembled_content = "\n\n".join(content_parts)
        
        # Debug information
        debug_info = {
            "total_tokens": contribution.total_tokens,
            "tokens_by_type": {t.value: count for t, count in contribution.tokens_by_type.items()},
            "contributors_used": len(contribution.selected_contributors),
            "contributors_overflow": len(contribution.overflow_contributors),
            "budget_utilization": contribution.total_tokens / token_budget if token_budget > 0 else 0
        }
        
        return assembled_content, debug_info

# Global instance for easy access
_contributor_manager = ContextContributorManager()

def get_contributor_manager(workspace_root: str = ".") -> ContextContributorManager:
    """Get the global context contributor manager"""
    global _contributor_manager
    _contributor_manager.workspace_root = Path(workspace_root).resolve()
    return _contributor_manager

def assemble_smart_context(touched_files: Optional[List[str]] = None,
                         current_diff: Optional[str] = None,
                         search_results: Optional[List[str]] = None,
                         file_tree: Optional[List[str]] = None,
                         current_task: Optional[str] = None,
                         token_budget: int = 50000,
                         token_counter = None,
                         workspace_root: str = ".") -> Tuple[str, Dict[str, Any]]:
    """
    Convenience function to assemble smart context content.
    
    Returns:
        Tuple of (context_content, debug_info)
    """
    manager = get_contributor_manager(workspace_root)
    return manager.assemble_context_content(
        touched_files=touched_files,
        current_diff=current_diff,
        search_results=search_results,
        file_tree=file_tree,
        current_task=current_task,
        token_budget=token_budget,
        token_counter=token_counter
    )