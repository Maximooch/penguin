"""Enhanced Context Management for Penguin Projects.

This module provides intelligent context prioritization and loading based on
current task requirements and relevance scoring.
"""

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ProjectContextManager:
    """Manages context loading and prioritization for project tasks."""
    
    def __init__(self, project_manager, conversation_manager):
        """Initialize with project manager and conversation system.
        
        Args:
            project_manager: ProjectManager instance
            conversation_manager: ConversationManager instance for context loading
        """
        self.project_manager = project_manager
        self.conversation_manager = conversation_manager
        self.context_cache = {}
        self.priority_weights = {
            "requirements": 1.0,     # Highest priority
            "architecture": 0.9,
            "design": 0.8,
            "notes": 0.7,
            "research": 0.6,
            "misc": 0.3             # Lowest priority
        }
    
    async def load_prioritized_context(
        self,
        task_id: str,
        max_context_files: int = 10,
        include_project_context: bool = True,
        include_task_context: bool = True
    ) -> Dict[str, Any]:
        """Load and prioritize context for a specific task.
        
        Args:
            task_id: ID of the task requiring context
            max_context_files: Maximum number of context files to load
            include_project_context: Whether to include project-level context
            include_task_context: Whether to include task-specific context
            
        Returns:
            Dictionary with loaded context and metadata
        """
        task = self.project_manager.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}
        
        logger.info(f"Loading prioritized context for task: {task.title}")
        
        # Collect context sources
        context_sources = []
        
        # Task-specific context
        if include_task_context and task.metadata.get("context_files"):
            for file_path in task.metadata["context_files"]:
                context_sources.append({
                    "path": file_path,
                    "type": "task_specific",
                    "priority_boost": 0.5,  # Boost task-specific context
                    "relevance": 1.0
                })
        
        # Project-level context
        if include_project_context and task.project_id:
            project = self.project_manager.get_project(task.project_id)
            if project and project.context_path:
                project_context = self._scan_project_context(
                    project.context_path, 
                    task
                )
                context_sources.extend(project_context)
        
        # Global workspace context (if no project)
        if not task.project_id:
            workspace_context = self._scan_workspace_context(task)
            context_sources.extend(workspace_context)
        
        # Score and sort context sources
        scored_sources = self._score_context_relevance(context_sources, task)
        sorted_sources = sorted(
            scored_sources, 
            key=lambda x: x["final_score"], 
            reverse=True
        )[:max_context_files]
        
        # Load the highest-priority context files
        loaded_context = []
        total_score = 0
        
        for source in sorted_sources:
            try:
                content = self._load_context_file(source["path"])
                if content:
                    loaded_context.append({
                        "file": source["path"],
                        "type": source["type"],
                        "score": source["final_score"],
                        "content": content[:2000],  # Truncate for memory management
                        "full_content": content
                    })
                    total_score += source["final_score"]
                    
                    # Add to conversation context
                    self.conversation_manager.conversation.add_context(
                        content=content,
                        source=f"context/{Path(source['path']).name}",
                        category="CONTEXT"
                    )
            except Exception as e:
                logger.warning(f"Failed to load context file {source['path']}: {e}")
        
        return {
            "task_id": task_id,
            "task_title": task.title,
            "loaded_files": len(loaded_context),
            "total_relevance_score": total_score,
            "context": loaded_context,
            "prioritization_summary": self._create_prioritization_summary(sorted_sources)
        }
    
    def _scan_project_context(self, context_path: Path, task) -> List[Dict[str, Any]]:
        """Scan project context directory for relevant files."""
        context_sources = []
        
        if not context_path.exists():
            return context_sources
        
        for file_path in context_path.rglob("*.md"):
            file_type = self._classify_context_file(file_path)
            relevance = self._calculate_file_relevance(file_path, task)
            
            context_sources.append({
                "path": str(file_path),
                "type": file_type,
                "priority_boost": 0.0,
                "relevance": relevance
            })
        
        return context_sources
    
    def _scan_workspace_context(self, task) -> List[Dict[str, Any]]:
        """Scan workspace context directory for global context."""
        context_sources = []
        workspace_context = Path("context")  # Global context folder
        
        if workspace_context.exists():
            for file_path in workspace_context.rglob("*.md"):
                file_type = self._classify_context_file(file_path)
                relevance = self._calculate_file_relevance(file_path, task)
                
                context_sources.append({
                    "path": str(file_path),
                    "type": file_type,
                    "priority_boost": 0.0,
                    "relevance": relevance
                })
        
        return context_sources
    
    def _classify_context_file(self, file_path: Path) -> str:
        """Classify context file type based on name and content."""
        name_lower = file_path.stem.lower()
        
        # Classification rules
        if any(keyword in name_lower for keyword in ["requirement", "spec", "specification"]):
            return "requirements"
        elif any(keyword in name_lower for keyword in ["architecture", "arch", "design", "structure"]):
            return "architecture"
        elif any(keyword in name_lower for keyword in ["design", "ui", "ux", "mockup"]):
            return "design"
        elif any(keyword in name_lower for keyword in ["research", "analysis", "study"]):
            return "research"
        elif any(keyword in name_lower for keyword in ["note", "memo", "log"]):
            return "notes"
        else:
            return "misc"
    
    def _calculate_file_relevance(self, file_path: Path, task) -> float:
        """Calculate relevance score for a context file to a task."""
        relevance = 0.0
        
        # Check file name relevance
        file_name = file_path.stem.lower()
        task_title_words = set(task.title.lower().split())
        task_desc_words = set(task.description.lower().split()) if task.description else set()
        
        # Name-based relevance
        name_words = set(file_name.replace("_", " ").replace("-", " ").split())
        title_overlap = len(name_words.intersection(task_title_words))
        desc_overlap = len(name_words.intersection(task_desc_words))
        
        relevance += title_overlap * 0.3
        relevance += desc_overlap * 0.2
        
        # Tag-based relevance
        if hasattr(task, 'tags') and task.tags:
            task_tags = set(tag.lower() for tag in task.tags)
            if task_tags.intersection(name_words):
                relevance += 0.4
        
        # Acceptance criteria relevance
        if task.acceptance_criteria:
            criteria_text = " ".join(task.acceptance_criteria).lower()
            criteria_words = set(criteria_text.split())
            criteria_overlap = len(name_words.intersection(criteria_words))
            relevance += criteria_overlap * 0.1
        
        # File age (newer files get slight boost)
        try:
            age_days = (Path().cwd() - file_path.stat().st_mtime) / 86400
            if age_days < 7:  # Files modified in last week
                relevance += 0.1
        except (OSError, AttributeError):
            pass
        
        return min(relevance, 1.0)  # Cap at 1.0
    
    def _score_context_relevance(self, sources: List[Dict[str, Any]], task) -> List[Dict[str, Any]]:
        """Calculate final relevance scores for context sources."""
        scored_sources = []
        
        for source in sources:
            base_priority = self.priority_weights.get(source["type"], 0.5)
            relevance = source["relevance"]
            priority_boost = source["priority_boost"]
            
            # Final score combines type priority, relevance, and boosts
            final_score = (base_priority * 0.4) + (relevance * 0.5) + (priority_boost * 0.1)
            
            source["final_score"] = final_score
            scored_sources.append(source)
        
        return scored_sources
    
    def _load_context_file(self, file_path: str) -> Optional[str]:
        """Load content from a context file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to load context file {file_path}: {e}")
            return None
    
    def _create_prioritization_summary(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a summary of context prioritization decisions."""
        by_type = defaultdict(list)
        for source in sources:
            by_type[source["type"]].append(source["final_score"])
        
        return {
            "total_sources": len(sources),
            "by_type": {
                t: {
                    "count": len(scores),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "max_score": max(scores) if scores else 0
                }
                for t, scores in by_type.items()
            },
            "prioritization_weights": self.priority_weights
        } 