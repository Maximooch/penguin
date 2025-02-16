"""
Visualization module for Project/Task Manager
Provides various visualization methods for project statistics and task relationships
"""

from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
import plotext as plt
from matplotlib.dates import DateFormatter
from rich.console import Console

matplotlib.use("Agg")  # For headless environments


class ProjectVisualizer:
    def __init__(self, output_dir: Path = Path("workspace/visualizations")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

    def _get_task_attr(self, task, attr, default=None):
        """Safely get task attribute whether it's a dict or object"""
        if isinstance(task, dict):
            return task.get(attr, default)
        return getattr(task, attr, default)

    def _get_tasks(self, project):
        """Get tasks whether project is a dict or object"""
        if isinstance(project, dict):
            return project.get("tasks", {}).values()
        return project.tasks.values()

    def create_dashboard(
        self, projects: list, save_name: str = "project_stats.png"
    ) -> Path:
        """Generate comprehensive visual statistics dashboard for projects"""
        save_path = self.output_dir / save_name

        # Create figure with subplots
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle("Project Statistics Dashboard", fontsize=16)

        # 1. Task Status Distribution (Pie Chart)
        status_counts = {"active": 0, "completed": 0, "archived": 0}
        for project in projects:
            for task in self._get_tasks(project):
                status = self._get_task_attr(task, "status", "active")
                status_counts[status] += 1

        ax1.pie(
            status_counts.values(),
            labels=status_counts.keys(),
            autopct="%1.1f%%",
            colors=["#FF9999", "#66B2FF", "#99FF99"],
        )
        ax1.set_title("Task Status Distribution")

        # 2. Priority Distribution (Bar Chart)
        priority_counts = {1: 0, 2: 0, 3: 0}
        for project in projects:
            for task in self._get_tasks(project):
                priority = self._get_task_attr(task, "priority", 3)
                priority_counts[priority] += 1

        ax2.bar(
            ["High", "Medium", "Low"],
            priority_counts.values(),
            color=["#FF0000", "#FFA500", "#00FF00"],
        )
        ax2.set_title("Task Priority Distribution")

        # 3. Task Dependencies Network
        G = nx.DiGraph()
        for project in projects:
            for task in self._get_tasks(project):
                title = self._get_task_attr(task, "title", "Untitled")
                progress = self._get_task_attr(task, "progress", 0)
                priority = self._get_task_attr(task, "priority", 3)
                dependencies = self._get_task_attr(task, "dependencies", [])

                G.add_node(title, progress=progress, priority=priority)
                for dep_id in dependencies:
                    for dep_task in self._get_tasks(project):
                        if self._get_task_attr(dep_task, "id") == dep_id:
                            G.add_edge(title, self._get_task_attr(dep_task, "title"))
                            break

        if G.nodes():  # Only draw if there are nodes
            pos = nx.spring_layout(G)
            nx.draw(
                G,
                pos,
                ax=ax3,
                node_color=[G.nodes[node]["progress"] / 100 for node in G.nodes()],
                node_size=[3000 / G.nodes[node]["priority"] for node in G.nodes()],
                cmap=plt.cm.RdYlGn,
                with_labels=True,
                arrows=True,
                edge_color="gray",
                font_size=8,
            )
        ax3.set_title("Task Dependencies Network")

        # 4. Progress Timeline
        dates = []
        progresses = []
        titles = []
        for project in projects:
            for task in self._get_tasks(project):
                due_date = self._get_task_attr(task, "due_date")
                if due_date:
                    dates.append(datetime.fromisoformat(due_date))
                    progresses.append(self._get_task_attr(task, "progress", 0))
                    titles.append(self._get_task_attr(task, "title", "Untitled"))

        if dates:
            scatter = ax4.scatter(
                dates, progresses, alpha=0.6, c=progresses, cmap="RdYlGn"
            )
            ax4.xaxis.set_major_formatter(DateFormatter("%Y-%m-%d"))
            plt.xticks(rotation=45)
            ax4.set_title("Task Progress vs Due Date")
            ax4.set_xlabel("Due Date")
            ax4.set_ylabel("Progress (%)")

            plt.colorbar(scatter, ax=ax4, label="Progress %")

            for i, title in enumerate(titles):
                ax4.annotate(
                    title,
                    (dates[i], progresses[i]),
                    xytext=(5, 5),
                    textcoords="offset points",
                    fontsize=8,
                    alpha=0.7,
                )

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close()

        return save_path

    def show_terminal_charts(self, projects: list) -> None:
        """Display ASCII charts directly in terminal"""
        import plotext as ptx

        for project in projects:
            # Clear previous output
            ptx.clear_terminal()
            ptx.clc()

            # Sort tasks by priority
            tasks = sorted(
                self._get_tasks(project),
                key=lambda x: self._get_task_attr(x, "priority", 3),
            )
            titles = [self._get_task_attr(t, "title", "Untitled") for t in tasks]
            progress = [self._get_task_attr(t, "progress", 0) for t in tasks]

            if not tasks:
                self.console.print("[yellow]No tasks found in project[/]")
                continue

            # Create progress bar chart
            ptx.bar(titles, progress, width=0.8)
            project_name = self._get_task_attr(project, "name", "Project")
            ptx.title(f"{project_name} - Task Progress")
            ptx.xlabel("Tasks")
            ptx.ylabel("Progress %")
            ptx.ylim(0, 100)

            # Add color based on progress
            colors = [
                "red" if p < 30 else "yellow" if p < 70 else "green" for p in progress
            ]
            ptx.bar_colors(colors)

            ptx.show()
            input("Press Enter to continue...")

    def create_gantt_chart(self, projects: list, save_name: str = "gantt.png") -> Path:
        """Generate a Gantt chart for project timeline"""
        save_path = self.output_dir / save_name

        fig, ax = plt.subplots(figsize=(15, 8))

        # Collect all tasks
        tasks = []
        for project in projects:
            for task in self._get_tasks(project):
                due_date = self._get_task_attr(task, "due_date")
                created_at = self._get_task_attr(task, "created_at")
                if due_date and created_at:
                    tasks.append(
                        {
                            "title": self._get_task_attr(task, "title", "Untitled"),
                            "start": datetime.fromisoformat(created_at),
                            "end": datetime.fromisoformat(due_date),
                            "progress": self._get_task_attr(task, "progress", 0),
                            "priority": self._get_task_attr(task, "priority", 3),
                        }
                    )

        if not tasks:
            self.console.print("[yellow]No tasks with dates found for Gantt chart[/]")
            return save_path

        # Sort tasks by start date
        tasks.sort(key=lambda x: x["start"])

        # Create Gantt bars
        for idx, task in enumerate(tasks):
            duration = task["end"] - task["start"]
            progress_date = task["start"] + (duration * task["progress"] / 100)

            # Draw full task duration
            ax.barh(
                idx,
                duration.total_seconds(),
                left=task["start"],
                alpha=0.3,
                color=["red", "orange", "green"][task["priority"] - 1],
            )

            # Draw progress overlay
            if task["progress"] > 0:
                ax.barh(
                    idx,
                    (progress_date - task["start"]).total_seconds(),
                    left=task["start"],
                    alpha=0.8,
                    color=["darkred", "darkorange", "darkgreen"][task["priority"] - 1],
                )

        # Customize appearance
        ax.set_yticks(range(len(tasks)))
        ax.set_yticklabels([t["title"] for t in tasks])
        ax.xaxis.set_major_formatter(DateFormatter("%Y-%m-%d"))
        plt.xticks(rotation=45)

        plt.title("Project Timeline")
        plt.xlabel("Date")
        plt.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close()

        return save_path
