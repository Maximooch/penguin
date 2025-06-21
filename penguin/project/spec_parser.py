"""Project Specification Parser for Penguin Dream Workflow.

This module implements Point 0 from dream.md: parsing natural language project
descriptions into structured, actionable project plans with tasks and dependencies.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import re

logger = logging.getLogger(__name__)


class ProjectSpecificationParser:
    """Parses natural language project specifications into structured plans."""
    
    def __init__(self, engine, project_manager):
        """Initialize with Engine and ProjectManager instances.
        
        Args:
            engine: Engine instance for LLM processing
            project_manager: ProjectManager for creating projects/tasks
        """
        self.engine = engine
        self.project_manager = project_manager
        
    async def parse_project_specification(
        self,
        specification: str,
        project_name: Optional[str] = None,
        context_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Parse a natural language project specification into a structured plan.
        
        Args:
            specification: Natural language description of the project
            project_name: Optional project name override
            context_files: Optional list of context files to include
            
        Returns:
            Dictionary with parsing results and created project/tasks
        """
        logger.info("Parsing project specification with Engine")
        
        try:
            # Prepare the specification analysis prompt
            analysis_prompt = self._create_specification_prompt(
                specification, project_name, context_files
            )
            
            # Route through Engine for LLM analysis
            logger.info("Routing specification through Engine for analysis")
            result = await self.engine.run_task(
                task_prompt=analysis_prompt,
                max_iterations=3,
                task_name="Parse Project Specification",
                task_context={"operation": "project_specification_parsing"},
                enable_events=False
            )
            
            # Extract the structured plan from the result
            structured_plan = self._extract_structured_plan(result)
            
            if not structured_plan:
                return {
                    "status": "error",
                    "message": "Failed to extract structured plan from Engine response",
                    "raw_result": result
                }
            
            # Create the project and tasks from the structured plan
            creation_result = await self._create_project_from_plan(structured_plan)
            
            return {
                "status": "success",
                "message": "Project specification parsed and created successfully",
                "structured_plan": structured_plan,
                "creation_result": creation_result,
                "original_spec": specification
            }
            
        except Exception as e:
            logger.error(f"Error parsing project specification: {e}")
            return {
                "status": "error",
                "message": f"Parsing failed: {str(e)}",
                "original_spec": specification
            }
    
    def _create_specification_prompt(
        self,
        specification: str,
        project_name: Optional[str] = None,
        context_files: Optional[List[str]] = None
    ) -> str:
        """Create the prompt for Engine to analyze the project specification."""
        
        prompt = f"""Parse this project specification into a structured work breakdown.

PROJECT SPECIFICATION:
{specification}

INSTRUCTIONS:
1. Extract the main project goal and create a clear project description
2. Break down the work into specific, actionable tasks
3. Identify task dependencies and priorities
4. Define clear acceptance criteria for each task
5. Estimate complexity and suggest resource constraints

{f"SUGGESTED PROJECT NAME: {project_name}" if project_name else ""}

{f"ADDITIONAL CONTEXT FILES: {', '.join(context_files)}" if context_files else ""}

REQUIRED OUTPUT FORMAT:
Respond with ONLY a JSON object in this exact structure:

{{
    "project": {{
        "name": "Clear project name",
        "description": "Detailed project description",
        "tags": ["tag1", "tag2"],
        "budget_tokens": estimated_token_budget_or_null,
        "budget_minutes": estimated_time_budget_or_null
    }},
    "tasks": [
        {{
            "title": "Task title",
            "description": "Detailed task description",
            "priority": priority_number_0_to_10,
            "dependencies": ["task_title_1", "task_title_2"],
            "acceptance_criteria": ["criteria 1", "criteria 2"],
            "tags": ["tag1", "tag2"],
            "budget_tokens": estimated_tokens_or_null,
            "budget_minutes": estimated_minutes_or_null,
            "allowed_tools": ["tool1", "tool2"] or null
        }}
    ]
}}

Ensure:
- Task titles are unique within the project
- Dependencies reference exact task titles
- Priorities are 0-10 (0 = highest priority)
- All tasks have clear, testable acceptance criteria
- Dependencies form a valid DAG (no cycles)
"""
        
        return prompt
    
    def _extract_structured_plan(self, engine_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract structured plan from Engine result."""
        try:
            # Get the final response from Engine
            response_text = ""
            if "final_response" in engine_result:
                response_text = engine_result["final_response"]
            elif "conversation_history" in engine_result:
                # Extract from conversation history
                for message in reversed(engine_result["conversation_history"]):
                    if message.get("role") == "assistant":
                        response_text = message.get("content", "")
                        break
            
            if not response_text:
                logger.error("No response text found in Engine result")
                return None
            
            # Try to extract JSON from the response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.error("No JSON found in Engine response")
                return None
            
            json_text = response_text[json_start:json_end]
            structured_plan = json.loads(json_text)
            
            # Validate the structure
            if not self._validate_plan_structure(structured_plan):
                logger.error("Invalid plan structure received from Engine")
                return None
            
            return structured_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Engine response: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting structured plan: {e}")
            return None
    
    def _validate_plan_structure(self, plan: Dict[str, Any]) -> bool:
        """Validate that the plan has the expected structure."""
        try:
            # Check required top-level keys
            if "project" not in plan or "tasks" not in plan:
                return False
            
            # Check project structure
            project = plan["project"]
            required_project_fields = ["name", "description"]
            if not all(field in project for field in required_project_fields):
                return False
            
            # Check tasks structure
            tasks = plan["tasks"]
            if not isinstance(tasks, list) or len(tasks) == 0:
                return False
            
            required_task_fields = ["title", "description", "priority"]
            for task in tasks:
                if not all(field in task for field in required_task_fields):
                    return False
                
                # Validate priority range
                if not isinstance(task["priority"], int) or not (0 <= task["priority"] <= 10):
                    return False
            
            # Check for duplicate task titles
            task_titles = [task["title"] for task in tasks]
            if len(task_titles) != len(set(task_titles)):
                return False
            
            # Validate dependencies reference existing tasks
            for task in tasks:
                if "dependencies" in task and task["dependencies"]:
                    for dep in task["dependencies"]:
                        if dep not in task_titles:
                            return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating plan structure: {e}")
            return False
    
    async def _create_project_from_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Create project and tasks from structured plan."""
        try:
            # Create the project
            project_data = plan["project"]
            project = await self.project_manager.create_project_async(
                name=project_data["name"],
                description=project_data["description"],
                tags=project_data.get("tags", []),
                budget_tokens=project_data.get("budget_tokens"),
                budget_minutes=project_data.get("budget_minutes")
            )
            
            # Create tasks with dependency mapping
            tasks = plan["tasks"]
            created_tasks = {}
            task_id_mapping = {}  # title -> task_id
            
            # Sort tasks by priority and dependencies (topological sort)
            sorted_tasks = self._topological_sort_tasks(tasks)
            
            # Create tasks in dependency order
            for task_data in sorted_tasks:
                # Map dependency titles to task IDs
                dependencies = []
                if task_data.get("dependencies"):
                    dependencies = [
                        task_id_mapping[dep_title] 
                        for dep_title in task_data["dependencies"]
                        if dep_title in task_id_mapping
                    ]
                
                task = await self.project_manager.create_task_async(
                    title=task_data["title"],
                    description=task_data["description"],
                    project_id=project.id,
                    priority=task_data["priority"],
                    tags=task_data.get("tags", []),
                    dependencies=dependencies,
                    budget_tokens=task_data.get("budget_tokens"),
                    budget_minutes=task_data.get("budget_minutes"),
                    allowed_tools=task_data.get("allowed_tools"),
                    acceptance_criteria=task_data.get("acceptance_criteria", [])
                )
                
                created_tasks[task.title] = task
                task_id_mapping[task.title] = task.id
            
            return {
                "status": "success",
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description
                },
                "tasks_created": len(created_tasks),
                "task_details": [
                    {
                        "id": task.id,
                        "title": task.title,
                        "priority": task.priority,
                        "dependencies": len(task.dependencies)
                    }
                    for task in created_tasks.values()
                ]
            }
            
        except Exception as e:
            logger.error(f"Error creating project from plan: {e}")
            return {
                "status": "error",
                "message": f"Failed to create project: {str(e)}"
            }
    
    def _topological_sort_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort tasks in dependency order using topological sort."""
        from collections import deque, defaultdict
        
        # Build dependency graph
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        task_map = {task["title"]: task for task in tasks}
        
        # Initialize in-degree for all tasks
        for task in tasks:
            in_degree[task["title"]] = 0
        
        # Build the graph
        for task in tasks:
            title = task["title"]
            dependencies = task.get("dependencies", [])
            
            for dep in dependencies:
                if dep in task_map:
                    graph[dep].append(title)
                    in_degree[title] += 1
        
        # Perform topological sort
        queue = deque([title for title in in_degree if in_degree[title] == 0])
        sorted_titles = []
        
        while queue:
            current = queue.popleft()
            sorted_titles.append(current)
            
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # Return tasks in sorted order
        return [task_map[title] for title in sorted_titles if title in task_map]

    async def parse_project_specification_from_markdown(
        self,
        markdown_content: str,
    ) -> Dict[str, Any]:
        """
        Parses a project specification from a simple Markdown format.

        This is the simplified MVP parser that bypasses the LLM Engine.
        It expects a format with a main project title and a list of tasks.

        Args:
            markdown_content: The string content of the markdown file.

        Returns:
            A dictionary with the parsing result.
        """
        logger.info("Parsing project specification from Markdown (MVP version)")
        try:
            plan = self._parse_markdown_to_structured_plan(markdown_content)

            if not plan:
                return {
                    "status": "error",
                    "message": "Failed to parse valid project and tasks from Markdown.",
                }

            # Use the existing method to create the project and tasks in the DB
            creation_result = await self._create_project_from_plan(plan)

            return {
                "status": "success",
                "message": "Project parsed and created successfully from Markdown.",
                "structured_plan": plan,
                "creation_result": creation_result,
            }

        except Exception as e:
            logger.error(f"Error parsing project specification from Markdown: {e}")
            return {
                "status": "error",
                "message": f"Markdown parsing failed: {str(e)}",
            }

    def _parse_markdown_to_structured_plan(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Extracts a project title and tasks from markdown content.

        Expected format:
        # Project Title
        ...
        ## Tasks
        - Task 1 description
        - Task 2 description
        """
        project_title_match = re.search(r"^\s*#\s*(.+)", content, re.MULTILINE)
        if not project_title_match:
            logger.error("No H1 title found for project name in Markdown.")
            return None
        project_name = project_title_match.group(1).strip()

        # Find tasks under a "Tasks" heading
        tasks_section_match = re.search(r"##\s*Tasks\s*\n((?:-|\*)\s*.+\n?)+", content, re.IGNORECASE)
        if not tasks_section_match:
            logger.error("No '## Tasks' section with a list of tasks found.")
            return None
        
        tasks_content = tasks_section_match.group(0)
        task_items = re.findall(r"^\s*(?:-|\*)\s*(.+)", tasks_content, re.MULTILINE)

        if not task_items:
            logger.error("Task list found but no task items could be parsed.")
            return None

        tasks_structured = []
        for i, task_desc in enumerate(task_items):
            tasks_structured.append({
                "title": task_desc.strip(),
                "description": task_desc.strip(),
                "priority": i, # Simple priority based on order
                "dependencies": [],
                "acceptance_criteria": ["Completed as described."],
            })
            
        plan = {
            "project": {
                "name": project_name,
                "description": f"A project named '{project_name}' parsed from Markdown.",
            },
            "tasks": tasks_structured
        }

        return plan


# Convenience function for direct usage
async def parse_project_specification_from_markdown(
    markdown_content: str,
    project_manager,
) -> Dict[str, Any]:
    """Convenience function to parse a project spec from markdown."""
    # For MVP, engine is not required for the markdown parser
    parser = ProjectSpecificationParser(engine=None, project_manager=project_manager)
    return await parser.parse_project_specification_from_markdown(markdown_content)


async def parse_project_specification(
    specification: str,
    engine,
    project_manager,
    project_name: Optional[str] = None,
    context_files: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Convenience function to parse a project specification.
    
    Args:
        specification: Natural language project description
        engine: Engine instance
        project_manager: ProjectManager instance
        project_name: Optional project name override
        context_files: Optional context files to include
        
    Returns:
        Dictionary with parsing and creation results
    """
    parser = ProjectSpecificationParser(engine, project_manager)
    return await parser.parse_project_specification(
        specification, project_name, context_files
    ) 