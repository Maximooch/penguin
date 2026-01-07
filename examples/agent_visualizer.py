#!/usr/bin/env python3
"""
Mock CLI visualization of Penguin multi-agent system.

Simulates a parent agent orchestrating dozens of sub-agents with
real-time status updates, progress tracking, and context sharing.

Usage:
    python agent_visualizer.py [--agents N] [--speed SPEED]

Requirements:
    pip install rich
"""

import argparse
import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


class AgentState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


STATE_STYLES = {
    AgentState.PENDING: ("⏳", "dim"),
    AgentState.RUNNING: ("●", "green bold"),
    AgentState.PAUSED: ("⏸", "yellow"),
    AgentState.COMPLETED: ("✓", "green"),
    AgentState.FAILED: ("✗", "red bold"),
    AgentState.CANCELLED: ("○", "dim red"),
}

AGENT_ROLES = [
    "planner", "implementer", "reviewer", "tester", "documenter",
    "analyzer", "refactor", "debugger", "optimizer", "explorer",
    "searcher", "validator", "formatter", "linter", "builder",
]

TASK_DESCRIPTIONS = [
    "Analyzing codebase structure",
    "Implementing feature X",
    "Reviewing pull request",
    "Running test suite",
    "Generating documentation",
    "Searching for patterns",
    "Refactoring module",
    "Debugging issue #42",
    "Optimizing performance",
    "Exploring dependencies",
    "Validating schemas",
    "Formatting code",
    "Linting files",
    "Building project",
    "Indexing workspace",
]


@dataclass
class MockAgent:
    id: str
    role: str
    parent_id: Optional[str]
    state: AgentState = AgentState.PENDING
    progress: float = 0.0
    task: str = ""
    tokens_used: int = 0
    tokens_limit: int = 50000
    shares_context: bool = False
    start_time: Optional[float] = None
    children: List[str] = field(default_factory=list)
    messages_sent: int = 0
    messages_received: int = 0

    def elapsed(self) -> str:
        if self.start_time is None:
            return "—"
        elapsed = time.time() - self.start_time
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        return f"{int(elapsed // 60)}m {int(elapsed % 60)}s"


class AgentSimulator:
    """Simulates agent lifecycle and state transitions."""

    def __init__(self, num_agents: int = 24, speed: float = 1.0):
        self.agents: Dict[str, MockAgent] = {}
        self.num_agents = num_agents
        self.speed = speed
        self.parent_id = "penguin-main"
        self._setup_agents()

    def _setup_agents(self):
        # Create parent agent
        self.agents[self.parent_id] = MockAgent(
            id=self.parent_id,
            role="orchestrator",
            parent_id=None,
            state=AgentState.RUNNING,
            task="Orchestrating sub-agents",
            start_time=time.time(),
            tokens_limit=200000,
        )

        # Create sub-agents in waves
        for i in range(self.num_agents):
            agent_id = f"worker-{i:02d}"
            role = random.choice(AGENT_ROLES)
            shares_context = random.random() < 0.4  # 40% share context

            agent = MockAgent(
                id=agent_id,
                role=role,
                parent_id=self.parent_id,
                state=AgentState.PENDING,
                task=random.choice(TASK_DESCRIPTIONS),
                shares_context=shares_context,
                tokens_limit=random.randint(20000, 80000),
            )
            self.agents[agent_id] = agent
            self.agents[self.parent_id].children.append(agent_id)

    async def simulate_step(self):
        """Simulate one step of agent activity."""
        for agent_id, agent in list(self.agents.items()):
            if agent_id == self.parent_id:
                # Parent agent slowly accumulates tokens
                agent.tokens_used = min(
                    agent.tokens_used + random.randint(100, 500),
                    agent.tokens_limit
                )
                continue

            # State transitions
            if agent.state == AgentState.PENDING:
                # Chance to start
                if random.random() < 0.15 * self.speed:
                    agent.state = AgentState.RUNNING
                    agent.start_time = time.time()
                    agent.progress = 0.0

            elif agent.state == AgentState.RUNNING:
                # Progress
                agent.progress += random.uniform(0.5, 3.0) * self.speed
                agent.tokens_used += random.randint(500, 2000)

                # Random message activity
                if random.random() < 0.1:
                    agent.messages_sent += 1
                    # Find another agent to receive
                    other = random.choice(list(self.agents.values()))
                    other.messages_received += 1

                # Chance to pause
                if random.random() < 0.02:
                    agent.state = AgentState.PAUSED

                # Complete or fail
                if agent.progress >= 100:
                    agent.progress = 100
                    if random.random() < 0.9:
                        agent.state = AgentState.COMPLETED
                    else:
                        agent.state = AgentState.FAILED

            elif agent.state == AgentState.PAUSED:
                # Chance to resume
                if random.random() < 0.1 * self.speed:
                    agent.state = AgentState.RUNNING

            elif agent.state in (AgentState.COMPLETED, AgentState.FAILED):
                # Chance to restart with new task
                if random.random() < 0.05 * self.speed:
                    agent.state = AgentState.PENDING
                    agent.progress = 0.0
                    agent.task = random.choice(TASK_DESCRIPTIONS)
                    agent.tokens_used = 0
                    agent.start_time = None

        await asyncio.sleep(0.1)


class AgentVisualizer:
    """Rich-based terminal visualization of agent system."""

    def __init__(self, simulator: AgentSimulator):
        self.simulator = simulator
        self.console = Console()
        self.start_time = time.time()

    def make_header(self) -> Panel:
        """Create header panel with system stats."""
        parent = self.simulator.agents[self.simulator.parent_id]

        # Count states
        states = {s: 0 for s in AgentState}
        for agent in self.simulator.agents.values():
            states[agent.state] += 1

        total_tokens = sum(a.tokens_used for a in self.simulator.agents.values())

        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="left")
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_column(justify="right")

        status_text = Text()
        status_text.append("● ", "green bold")
        status_text.append(f"{states[AgentState.RUNNING]} running  ", "green")
        status_text.append("⏳ ", "dim")
        status_text.append(f"{states[AgentState.PENDING]} pending  ", "dim")
        status_text.append("⏸ ", "yellow")
        status_text.append(f"{states[AgentState.PAUSED]} paused  ", "yellow")
        status_text.append("✓ ", "green")
        status_text.append(f"{states[AgentState.COMPLETED]} done  ", "green dim")
        status_text.append("✗ ", "red")
        status_text.append(f"{states[AgentState.FAILED]} failed", "red dim")

        grid.add_row(
            Text("🐧 PENGUIN MULTI-AGENT SYSTEM", style="bold cyan"),
            status_text,
            Text(f"⏱ {elapsed_str}", style="blue"),
            Text(f"🎫 {total_tokens:,} tokens", style="magenta"),
            Text(f"{len(self.simulator.agents)} agents", style="dim"),
        )

        return Panel(grid, style="blue", padding=(0, 1))

    def make_agent_tree(self) -> Panel:
        """Create tree view of agent hierarchy."""
        parent = self.simulator.agents[self.simulator.parent_id]

        tree = Tree(
            f"[bold cyan]🐧 {parent.id}[/] [dim]({parent.role})[/]"
        )

        # Group children by state for better visualization
        running = []
        pending = []
        paused = []
        completed = []
        failed = []

        for child_id in parent.children:
            child = self.simulator.agents[child_id]
            if child.state == AgentState.RUNNING:
                running.append(child)
            elif child.state == AgentState.PENDING:
                pending.append(child)
            elif child.state == AgentState.PAUSED:
                paused.append(child)
            elif child.state == AgentState.COMPLETED:
                completed.append(child)
            else:
                failed.append(child)

        def add_agents(branch_name: str, agents: List[MockAgent], style: str):
            if not agents:
                return
            branch = tree.add(f"[{style}]{branch_name} ({len(agents)})[/]")
            for agent in agents[:8]:  # Limit display
                icon, agent_style = STATE_STYLES[agent.state]
                ctx = "⟷" if agent.shares_context else "○"
                branch.add(
                    f"[{agent_style}]{icon}[/] {agent.id} "
                    f"[dim]{ctx} {agent.role}[/]"
                )
            if len(agents) > 8:
                branch.add(f"[dim]... and {len(agents) - 8} more[/]")

        add_agents("Running", running, "green bold")
        add_agents("Pending", pending, "dim")
        add_agents("Paused", paused, "yellow")
        add_agents("Completed", completed, "green dim")
        add_agents("Failed", failed, "red dim")

        return Panel(tree, title="[bold]Agent Hierarchy[/]", border_style="dim")

    def make_running_table(self) -> Panel:
        """Create detailed table of running agents."""
        table = Table(
            show_header=True,
            header_style="bold",
            border_style="dim",
            expand=True,
            padding=(0, 1),
        )
        table.add_column("Agent", style="cyan", width=12)
        table.add_column("Role", style="dim", width=12)
        table.add_column("Task", width=30, no_wrap=True)
        table.add_column("Progress", width=20)
        table.add_column("Tokens", justify="right", width=12)
        table.add_column("Time", justify="right", width=8)
        table.add_column("Ctx", justify="center", width=3)
        table.add_column("Msg", justify="right", width=5)

        running = [
            a for a in self.simulator.agents.values()
            if a.state == AgentState.RUNNING and a.id != self.simulator.parent_id
        ]

        for agent in sorted(running, key=lambda a: a.id)[:15]:
            # Progress bar using Unicode blocks
            filled = int(agent.progress / 5)
            bar = "█" * filled + "░" * (20 - filled)
            pct = f"{agent.progress:5.1f}%"

            progress_text = Text()
            progress_text.append(bar[:filled], "green")
            progress_text.append(bar[filled:], "dim")
            progress_text.append(f" {pct}", "green" if agent.progress > 50 else "yellow")

            token_pct = agent.tokens_used / agent.tokens_limit * 100
            token_style = "green" if token_pct < 60 else "yellow" if token_pct < 80 else "red"

            table.add_row(
                agent.id,
                agent.role,
                agent.task[:28] + ".." if len(agent.task) > 30 else agent.task,
                progress_text,
                Text(f"{agent.tokens_used:,}", style=token_style),
                agent.elapsed(),
                "⟷" if agent.shares_context else "○",
                str(agent.messages_sent + agent.messages_received),
            )

        if len(running) > 15:
            table.add_row(
                f"[dim]... +{len(running) - 15} more running[/]",
                "", "", "", "", "", "", ""
            )

        return Panel(
            table,
            title=f"[bold green]● Running Agents ({len(running)})[/]",
            border_style="green",
        )

    def make_recent_activity(self) -> Panel:
        """Create log of recent agent activity."""
        activities = []

        for agent in self.simulator.agents.values():
            if agent.state == AgentState.RUNNING and random.random() < 0.3:
                activities.append(
                    f"[green]●[/] [cyan]{agent.id}[/] executing: {agent.task[:40]}"
                )
            elif agent.state == AgentState.COMPLETED and random.random() < 0.2:
                activities.append(
                    f"[green]✓[/] [cyan]{agent.id}[/] completed task"
                )
            elif agent.state == AgentState.FAILED and random.random() < 0.3:
                activities.append(
                    f"[red]✗[/] [cyan]{agent.id}[/] encountered error"
                )

        # Show last 6 activities
        text = Text("\n".join(activities[-6:]) if activities else "[dim]No recent activity[/]")
        return Panel(text, title="[bold]Recent Activity[/]", border_style="dim", height=8)

    def make_stats(self) -> Panel:
        """Create statistics panel."""
        agents = list(self.simulator.agents.values())

        total_messages = sum(a.messages_sent for a in agents)
        shared_ctx = sum(1 for a in agents if a.shares_context)
        avg_progress = sum(a.progress for a in agents if a.state == AgentState.RUNNING) / max(1, sum(1 for a in agents if a.state == AgentState.RUNNING))

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left")
        table.add_column(justify="right")

        table.add_row("Total Messages:", f"[cyan]{total_messages}[/]")
        table.add_row("Shared Context:", f"[magenta]{shared_ctx}[/] agents")
        table.add_row("Avg Progress:", f"[yellow]{avg_progress:.1f}%[/]")
        table.add_row("Concurrency:", f"[green]{sum(1 for a in agents if a.state == AgentState.RUNNING)}[/] / 10")

        return Panel(table, title="[bold]Statistics[/]", border_style="dim")

    def make_layout(self) -> Layout:
        """Create the full layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=10),
        )

        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )

        layout["footer"].split_row(
            Layout(name="activity", ratio=2),
            Layout(name="stats", ratio=1),
        )

        layout["header"].update(self.make_header())
        layout["left"].update(self.make_agent_tree())
        layout["right"].update(self.make_running_table())
        layout["activity"].update(self.make_recent_activity())
        layout["stats"].update(self.make_stats())

        return layout

    async def run(self):
        """Run the visualization loop."""
        with Live(
            self.make_layout(),
            console=self.console,
            refresh_per_second=10,
            screen=True,
        ) as live:
            try:
                while True:
                    await self.simulator.simulate_step()
                    live.update(self.make_layout())
            except KeyboardInterrupt:
                pass


async def main():
    parser = argparse.ArgumentParser(
        description="Penguin Multi-Agent Visualizer"
    )
    parser.add_argument(
        "--agents", "-n",
        type=int,
        default=24,
        help="Number of sub-agents to simulate (default: 24)"
    )
    parser.add_argument(
        "--speed", "-s",
        type=float,
        default=1.0,
        help="Simulation speed multiplier (default: 1.0)"
    )
    args = parser.parse_args()

    simulator = AgentSimulator(num_agents=args.agents, speed=args.speed)
    visualizer = AgentVisualizer(simulator)

    print("\033[2J\033[H")  # Clear screen
    print("🐧 Starting Penguin Multi-Agent Visualizer...")
    print(f"   Simulating {args.agents} sub-agents at {args.speed}x speed")
    print("   Press Ctrl+C to exit\n")
    await asyncio.sleep(1)

    await visualizer.run()


if __name__ == "__main__":
    asyncio.run(main())
