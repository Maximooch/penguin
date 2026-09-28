#!/usr/bin/env python3
"""A calm, deterministic terminal aquarium built with Rich.

Examples:
    python terminal-aquarium.py
    python terminal-aquarium.py --duration 0 --seed 42
    python terminal-aquarium.py --fast --width 60 --height 16
    python terminal-aquarium.py --duration 30 --fps 60 --fish 60 --bubbles 300

A duration of zero runs until Ctrl-C. Animation is automatically skipped when
stdout is not an interactive terminal, which keeps redirected output useful.
"""

from __future__ import annotations

import argparse
import math
import random
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


@dataclass
class Fish:
    """A fish with its own speed, direction, and bobbing phase."""

    x: float
    base_y: float
    speed: float
    direction: int
    right_sprite: str
    left_sprite: str
    color: str
    bob_phase: float
    bob_amount: float

    def update(self, delta: float, width: int) -> None:
        """Move and wrap the fish within the water column."""
        self.x += self.speed * self.direction * delta
        sprite_width = len(self.sprite)
        if self.direction > 0 and self.x > width:
            self.x = -sprite_width
        elif self.direction < 0 and self.x < -sprite_width:
            self.x = float(width)

    @property
    def sprite(self) -> str:
        """Return the fish sprite facing its direction of travel."""
        return self.right_sprite if self.direction > 0 else self.left_sprite

    def row(self, elapsed: float) -> int:
        """Return the bobbing row for the current time."""
        return int(
            round(
                self.base_y + math.sin(elapsed * 1.4 + self.bob_phase) * self.bob_amount
            )
        )


@dataclass
class Bubble:
    """A bubble that rises and respawns near the aquarium floor."""

    x: float
    y: float
    speed: float
    glyph: str
    phase: float

    def update(self, delta: float, height: int, rng: random.Random, width: int) -> None:
        """Rise, wobble, and respawn the bubble when it reaches the surface."""
        self.y -= self.speed * delta
        self.x += math.sin(self.phase + self.y * 0.35) * delta * 0.3
        if self.y < 2:
            self.y = float(height - 3)
            self.x = rng.uniform(2, max(2, width - 3))
            self.speed = rng.uniform(1.0, 2.5)
            self.glyph = rng.choice(("o", "°", "·"))


@dataclass(frozen=True)
class Plant:
    """A fixed piece of seaweed anchored to the sandy floor."""

    x: int
    height: int
    phase: float
    color: str


@dataclass(frozen=True)
class Spark:
    """A tiny particle that flickers at a deterministic interval."""

    x: int
    y: int
    phase: float


class Canvas:
    """A fixed-width character canvas with optional Rich styles per cell."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._chars: list[list[str]] = [[" "] * width for _ in range(height)]
        self._styles: list[list[Optional[str]]] = [
            [None] * width for _ in range(height)
        ]

    def put(self, x: int, y: int, value: str, style: Optional[str] = None) -> None:
        """Place a string, clipping it to the canvas boundaries."""
        if y < 0 or y >= self.height:
            return
        for offset, char in enumerate(value):
            column = x + offset
            if 0 <= column < self.width:
                self._chars[y][column] = char
                self._styles[y][column] = style

    def fill(self, y: int, value: str, style: Optional[str] = None) -> None:
        """Fill one row with a repeating string."""
        if not value:
            return
        self.put(0, y, (value * (self.width // len(value) + 1))[: self.width], style)

    def text(self) -> Text:
        """Convert the canvas to a Rich Text renderable."""
        output = Text()
        for row_index, (chars, styles) in enumerate(zip(self._chars, self._styles)):
            current_style: Optional[str] = None
            buffer: list[str] = []
            for char, style in zip(chars, styles):
                if style != current_style:
                    if buffer:
                        output.append("".join(buffer), style=current_style)
                        buffer = []
                    current_style = style
                buffer.append(char)
            if buffer:
                output.append("".join(buffer), style=current_style)
            if row_index < self.height - 1:
                output.append("\n")
        return output


class Aquarium:
    """Own the aquarium simulation state and render each frame."""

    FISH_SPRITES: tuple[tuple[str, str], ...] = (
        ("><>", "<><"),
        ("><((('", "'))))><"),
        ("><>", "<><"),
        ("><((('>", "<'))))<"),
    )
    FISH_COLORS = ("bright_cyan", "bright_yellow", "bright_magenta", "bright_white")

    def __init__(
        self,
        width: int,
        height: int,
        rng: random.Random,
        fish_count: Optional[int] = None,
        bubble_count: Optional[int] = None,
        plant_count: Optional[int] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.rng = rng
        self.fish = self._make_fish(fish_count)
        self.bubbles = self._make_bubbles(bubble_count)
        self.plants = self._make_plants(plant_count)
        self.sparks = self._make_sparks()
        self.elapsed = 0.0

    def _make_fish(self, requested_count: Optional[int] = None) -> list[Fish]:
        """Create fish distributed across the available water."""
        count = (
            requested_count
            if requested_count is not None
            else max(3, min(6, self.width // 15))
        )
        fish: list[Fish] = []
        for index in range(count):
            right_sprite, left_sprite = self.rng.choice(self.FISH_SPRITES)
            direction = self.rng.choice((-1, 1))
            fish.append(
                Fish(
                    x=self.rng.uniform(1, max(1, self.width - 3)),
                    base_y=self.rng.uniform(3, max(3, self.height - 5)),
                    speed=self.rng.uniform(2.0, 5.0) * (1.0 + index * 0.04),
                    direction=direction,
                    right_sprite=right_sprite,
                    left_sprite=left_sprite,
                    color=self.rng.choice(self.FISH_COLORS),
                    bob_phase=self.rng.uniform(0.0, math.tau),
                    bob_amount=self.rng.choice((0.0, 0.0, 1.0)),
                )
            )
        return fish

    def _make_bubbles(self, requested_count: Optional[int] = None) -> list[Bubble]:
        """Create a small set of rising bubbles."""
        count = (
            requested_count
            if requested_count is not None
            else max(5, min(10, self.width // 8))
        )
        return [
            Bubble(
                x=self.rng.uniform(2, max(2, self.width - 3)),
                y=self.rng.uniform(2, max(2, self.height - 3)),
                speed=self.rng.uniform(1.0, 2.5),
                glyph=self.rng.choice(("o", "°", "·")),
                phase=self.rng.uniform(0.0, math.tau),
            )
            for _ in range(count)
        ]

    def _make_plants(self, requested_count: Optional[int] = None) -> list[Plant]:
        """Create seaweed anchors while keeping space for the fish."""
        count = (
            requested_count
            if requested_count is not None
            else max(3, min(8, self.width // 10))
        )
        plants: list[Plant] = []
        used_columns = set()
        for _ in range(count):
            column = self.rng.randrange(2, max(3, self.width - 2))
            if column in used_columns:
                continue
            used_columns.add(column)
            plants.append(
                Plant(
                    x=column,
                    height=self.rng.randint(2, max(2, min(6, self.height // 3))),
                    phase=self.rng.uniform(0.0, math.tau),
                    color=self.rng.choice(("green", "bright_green", "dark_green")),
                )
            )
        return plants

    def _make_sparks(self) -> list[Spark]:
        """Create fixed water particles for subtle depth."""
        count = max(12, min(28, self.width * self.height // 55))
        return [
            Spark(
                x=self.rng.randrange(self.width),
                y=self.rng.randrange(2, max(3, self.height - 3)),
                phase=self.rng.uniform(0.0, math.tau),
            )
            for _ in range(count)
        ]

    def update(self, delta: float) -> None:
        """Advance every moving entity by *delta* seconds."""
        self.elapsed += delta
        for fish in self.fish:
            fish.update(delta, self.width)
        for bubble in self.bubbles:
            bubble.update(delta, self.height, self.rng, self.width)

    def render(self) -> Panel:
        """Render the current aquarium frame."""
        canvas = Canvas(self.width, self.height)
        self._draw_background(canvas)
        self._draw_plants(canvas)
        self._draw_sparks(canvas)
        self._draw_bubbles(canvas)
        self._draw_fish(canvas)

        status = Text(
            f"fish {len(self.fish)}  •  bubbles {len(self.bubbles)}  •  seed-driven  •  Ctrl-C",
            style="dim cyan",
            justify="center",
        )
        return Panel(
            Group(canvas.text(), status),
            title="[bold bright_cyan]TERMINAL AQUARIUM[/bold bright_cyan]",
            subtitle="[dim]a small quiet corner of the terminal[/dim]",
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(1, 1),
            width=self.width + 4,
        )

    def _draw_background(self, canvas: Canvas) -> None:
        """Draw the water surface and sandy floor."""
        waves = "~   ~  ~    ~  "
        canvas.fill(0, waves, "bright_cyan")
        canvas.fill(1, ".  . .   .  .", "blue")
        for row in range(self.height - 2, self.height):
            canvas.fill(
                row,
                ".,  . . , .  ",
                "gold1" if row == self.height - 2 else "dark_orange",
            )

    def _draw_plants(self, canvas: Canvas) -> None:
        """Draw gently waving seaweed from the floor upward."""
        floor = self.height - 3
        for plant in self.plants:
            for offset in range(plant.height):
                row = floor - offset
                sway = math.sin(self.elapsed * 1.2 + plant.phase + offset * 0.8)
                column = plant.x + int(round(sway))
                glyph = "|" if offset % 2 else ("/" if sway >= 0 else "\\")
                canvas.put(column, row, glyph, plant.color)

    def _draw_sparks(self, canvas: Canvas) -> None:
        """Draw flickering particles in open water."""
        for spark in self.sparks:
            brightness = math.sin(self.elapsed * 1.8 + spark.phase)
            if brightness > 0.45:
                canvas.put(spark.x, spark.y, "·", "bright_blue")

    def _draw_bubbles(self, canvas: Canvas) -> None:
        """Draw rising bubbles above the fish layer."""
        for bubble in self.bubbles:
            column = int(round(bubble.x))
            row = int(round(bubble.y))
            canvas.put(column, row, bubble.glyph, "bright_cyan")

    def _draw_fish(self, canvas: Canvas) -> None:
        """Draw fish above the background and particles."""
        for fish in self.fish:
            canvas.put(
                int(round(fish.x)), fish.row(self.elapsed), fish.sprite, fish.color
            )


def non_negative_count(value: str) -> int:
    """Parse a count that may be zero but never negative."""
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return count


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=float,
        default=12.0,
        help="seconds to animate; 0 runs until Ctrl-C",
    )
    parser.add_argument(
        "--fps", type=float, default=18.0, help="target frames per second"
    )
    parser.add_argument("--seed", type=int, help="make the scene deterministic")
    parser.add_argument("--width", type=int, help="scene width in characters")
    parser.add_argument("--height", type=int, help="scene height in rows")
    parser.add_argument(
        "--fish",
        type=non_negative_count,
        help="number of fish (default: automatic)",
    )
    parser.add_argument(
        "--bubbles",
        type=non_negative_count,
        help="number of bubbles (default: automatic)",
    )
    parser.add_argument(
        "--plants",
        type=non_negative_count,
        help="number of seaweed plants (default: automatic)",
    )
    parser.add_argument("--fast", action="store_true", help="render one static frame")
    return parser


def resolve_dimensions(
    console: Console, requested_width: Optional[int], requested_height: Optional[int]
) -> tuple[int, int]:
    """Choose dimensions that fit the current terminal when unspecified."""
    terminal_width = console.size.width
    terminal_height = console.size.height
    width = requested_width or min(88, max(42, terminal_width - 6))
    height = requested_height or min(24, max(14, terminal_height - 10))
    return max(24, min(width, 120)), max(10, min(height, 40))


def can_animate(console: Console, args: argparse.Namespace) -> bool:
    """Return whether live animation is safe for this invocation."""
    return (
        not args.fast
        and console.is_terminal
        and not getattr(console, "is_dumb_terminal", False)
    )


def run(args: argparse.Namespace, console: Console) -> int:
    """Run the aquarium until its duration expires or Ctrl-C is pressed."""
    if args.duration < 0:
        raise ValueError("--duration must be zero or greater")
    if args.fps <= 0:
        raise ValueError("--fps must be greater than zero")

    width, height = resolve_dimensions(console, args.width, args.height)
    aquarium = Aquarium(
        width,
        height,
        random.Random(args.seed),
        fish_count=args.fish,
        bubble_count=args.bubbles,
        plant_count=args.plants,
    )
    if not can_animate(console, args):
        console.print(aquarium.render())
        return 0

    frame_seconds = 1.0 / args.fps
    started = time.monotonic()
    previous = started
    with Live(
        aquarium.render(),
        console=console,
        refresh_per_second=args.fps,
        transient=True,
        vertical_overflow="crop",
    ) as live:
        while args.duration == 0 or aquarium.elapsed < args.duration:
            now = time.monotonic()
            delta = min(0.2, max(0.0, now - previous))
            previous = now
            aquarium.update(delta)
            live.update(aquarium.render(), refresh=True)
            elapsed_wall = now - started
            if args.duration > 0 and elapsed_wall >= args.duration:
                break
            time.sleep(frame_seconds)
        live.update(aquarium.render(), refresh=True)
        time.sleep(0.15)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run Terminal Aquarium."""
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        return run(args, console)
    except KeyboardInterrupt:
        return 0
    except ValueError as error:
        console.print(f"[bold red]Error:[/bold red] {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
