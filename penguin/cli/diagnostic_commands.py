"""Performance and profiling CLI command registration."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["bind_diagnostic_commands"]


def bind_diagnostic_commands(
    app: typer.Typer,
    initialize: Callable[..., Awaitable[None]],
    run_interactive: Callable[[], Awaitable[None]],
    console_getter: Callable[[], Any],
    logger_getter: Callable[[], Any],
) -> dict[str, Any]:
    """Register diagnostic commands and return compatibility exports."""

    async def _initialize_core_components_globally(**kwargs: Any) -> None:
        await initialize(**kwargs)

    async def _run_interactive_chat() -> None:
        await run_interactive()

    def _console() -> Any:
        return console_getter()

    def _logger() -> Any:
        return logger_getter()

    # Profile command remains largely the same, ensure it uses `console` correctly
    @app.command()
    def perf_test(
        iterations: int = typer.Option(
            3, "--iterations", "-i", help="Number of test iterations to run"
        ),
        show_report: bool = typer.Option(
            True, "--show-report/--no-report", help="Show detailed performance report"
        ),
    ):
        """
        Run startup performance benchmarks to compare normal vs fast startup modes.
        """

        async def _async_perf_test():
            import time

            from penguin.utils.profiling import (
                enable_profiling,
                print_startup_report,
                reset_profiling,
            )

            _console().print(
                "[bold blue]🚀 Penguin Startup Performance Test[/bold blue]"
            )
            _console().print("=" * 60)

            enable_profiling()

            normal_times = []
            fast_times = []

            for iteration in range(iterations):
                _console().print(
                    f"\n[yellow]Iteration {iteration + 1}/{iterations}[/yellow]"
                )

                # Test normal startup
                _console().print("  Testing normal startup...")
                reset_profiling()
                start_time = time.perf_counter()

                try:
                    from penguin.core import PenguinCore

                    core_normal = await PenguinCore.create(
                        fast_startup=False, show_progress=False
                    )
                    normal_time = time.perf_counter() - start_time
                    normal_times.append(normal_time)
                    _console().print(f"    ✓ Normal startup: {normal_time:.4f}s")

                    # Clean up
                    if hasattr(core_normal, "reset_state"):
                        await core_normal.reset_state()
                    del core_normal

                except Exception as e:
                    _console().print(f"    ✗ Normal startup failed: {e}")
                    normal_times.append(float("inf"))

                # Test fast startup
                _console().print("  Testing fast startup...")
                reset_profiling()
                start_time = time.perf_counter()

                try:
                    from penguin.core import PenguinCore

                    core_fast = await PenguinCore.create(
                        fast_startup=True, show_progress=False
                    )
                    fast_time = time.perf_counter() - start_time
                    fast_times.append(fast_time)
                    _console().print(f"    ✓ Fast startup: {fast_time:.4f}s")

                    # Clean up
                    if hasattr(core_fast, "reset_state"):
                        await core_fast.reset_state()
                    del core_fast

                except Exception as e:
                    _console().print(f"    ✗ Fast startup failed: {e}")
                    fast_times.append(float("inf"))

            # Calculate statistics
            valid_normal = [t for t in normal_times if t != float("inf")]
            valid_fast = [t for t in fast_times if t != float("inf")]

            _console().print(
                "\n[bold blue]📊 Performance Results "
                f"({iterations} iterations)[/bold blue]"
            )
            _console().print("=" * 60)

            if valid_normal and valid_fast:
                avg_normal = sum(valid_normal) / len(valid_normal)
                avg_fast = sum(valid_fast) / len(valid_fast)

                improvement = ((avg_normal - avg_fast) / avg_normal) * 100
                speedup = avg_normal / avg_fast if avg_fast > 0 else float("inf")

                _console().print(
                    f"Normal startup:  {avg_normal:.4f}s avg "
                    f"(range: {min(valid_normal):.4f}s - "
                    f"{max(valid_normal):.4f}s)"
                )
                _console().print(
                    f"Fast startup:    {avg_fast:.4f}s avg "
                    f"(range: {min(valid_fast):.4f}s - {max(valid_fast):.4f}s)"
                )
                _console().print("")
                _console().print(
                    "Performance improvement: "
                    f"[bold green]{improvement:.1f}% faster[/bold green]"
                )
                _console().print(
                    f"Speedup factor: [bold green]{speedup:.2f}x[/bold green]"
                )

                if improvement > 0:
                    _console().print(
                        "\n[bold green]🎉 Fast startup mode is working![/bold green]"
                    )
                else:
                    _console().print(
                        "\n[bold yellow]⚠️ Fast startup mode might not be "
                        "working as expected[/bold yellow]"
                    )
            else:
                _console().print(
                    "[red]Could not complete performance tests due to errors[/red]"
                )

            if show_report:
                _console().print(
                    "\n[bold blue]📈 Detailed Performance Report[/bold blue]"
                )
                print_startup_report()

        asyncio.run(_async_perf_test())

    @app.command()
    def profile(
        output_file: str = typer.Option(
            "penguin_profile",
            "--output",
            "-o",
            help="Output file name for profile data (without extension)",
        ),
        view: bool = typer.Option(
            False, "--view", "-v", help="Open the profile visualization after saving"
        ),
    ):
        """
        Start Penguin with profiling enabled to analyze startup performance.
        Results are saved for later analysis with tools like snakeviz.
        """
        import cProfile
        import io
        import pstats

        # from pathlib import Path # Already imported
        import subprocess
        # import sys # Already imported

        # Create a profile directory if it doesn't exist
        profile_dir = Path("profiles")
        profile_dir.mkdir(exist_ok=True)

        # Prepare the output file name
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        actual_output_file = (
            output_file
            if output_file != "penguin_profile"
            else f"penguin_profile_{timestamp}"
        )

        output_path = profile_dir / f"{actual_output_file}.prof"
        stats_path = profile_dir / f"{actual_output_file}.txt"

        _console().print(
            "[bold blue]Starting Penguin with profiling enabled...[/bold blue]"
        )
        _console().print(f"Profile data will be saved to: [cyan]{output_path}[/cyan]")

        def run_profiled_penguin_interactive():
            # This goes through main_entry, which initializes and runs interactive.
            # We need to simulate running `penguin` command itself.
            # Profile `_run_interactive_chat` after components are initialized.
            async def profiled_interactive_session():
                await _initialize_core_components_globally()  # Ensure init
                await _run_interactive_chat()

            try:
                asyncio.run(profiled_interactive_session())
            except KeyboardInterrupt:
                _console().print(
                    "[yellow]Penguin interactive session interrupted by user "
                    "during profiling.[/yellow]"
                )
            except SystemExit:  # Catch typer.Exit
                _console().print(
                    "[yellow]Penguin exited during profiling (SystemExit).[/yellow]"
                )
            except Exception as e:
                _console().print(
                    f"[red]Error during profiled interactive run: {e!s}[/red]"
                )
                _logger().error(f"Profiling error: {e}", exc_info=True)

        profiler = cProfile.Profile()
        profiler.enable()

        run_profiled_penguin_interactive()  # Call the modified function

        profiler.disable()
        _console().print("[green]Profiling complete.[/green]")

        profiler.dump_stats(str(output_path))
        _console().print(f"Profile data saved to: [cyan]{output_path}[/cyan]")

        s = io.StringIO()
        # Sort by cumulative time, then standard name for consistent ordering
        ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative", "name")
        ps.print_stats(30)  # Print top 30 functions
        stats_content = s.getvalue()

        with open(stats_path, "w") as f:
            f.write(stats_content)

        _console().print(f"Profile summary saved to: [cyan]{stats_path}[/cyan]")
        _console().print("[bold]Top 30 functions by cumulative time:[/bold]")
        _console().print(stats_content)

        if view:
            try:
                subprocess.run(["snakeviz", str(output_path)], check=True)
            except FileNotFoundError:
                _console().print(
                    "[yellow]snakeviz command not found. Please install snakeviz "
                    "to view profiles.[/yellow]"
                )
                _console().print(
                    "[yellow]You can manually visualize the profile with: "
                    f"snakeviz {output_path}[/yellow]"
                )
            except Exception as e:
                _console().print(
                    f"[yellow]Could not open visualization: {e!s}[/yellow]"
                )
                _console().print(
                    "[yellow]You can manually visualize the profile with: "
                    f"snakeviz {output_path}[/yellow]"
                )

        _console().print("[bold green]Profiling session ended.[/bold green]")
        _console().print(f"[dim]To visualize: snakeviz {output_path}[/dim]")

    return {"perf_test": perf_test, "profile": profile}
