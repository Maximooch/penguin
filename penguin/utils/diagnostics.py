import logging
from typing import Dict

import tiktoken  # type: ignore
from rich.console import Console  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.progress import BarColumn, Progress, TextColumn  # type: ignore

console = Console()
MAX_CONTEXT_TOKENS = 200000


class TokenTracker:
    def __init__(self):
        self.tokens = {"input": 0, "output": 0}
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def update(self, input_tokens: int, output_tokens: int):
        """Update token counts directly with numbers"""
        print(f"[TokenTracker] Updating tokens: +{input_tokens} input, +{output_tokens} output")
        self.tokens["input"] += input_tokens
        self.tokens["output"] += output_tokens
        print(f"[TokenTracker] New token counts: {self.tokens['input']} input, {self.tokens['output']} output")

    def reset(self):
        """Reset token counts"""
        print("[TokenTracker] Resetting token counts")
        self.tokens = {"input": 0, "output": 0}


class Diagnostics:
    def __init__(self):
        self.enabled = True
        self.token_trackers: Dict[str, TokenTracker] = {
            "main_model": TokenTracker(),
            "tools": TokenTracker(),
            "memory": TokenTracker(),
        }
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def update_tokens(self, tracker_name: str, input_text: str, output_text: str = ""):
        """Update token counts for a specific tracker"""
        if not self.enabled:
            logging.debug("Diagnostics disabled, skipping token update")
            return

        print(f"[Diagnostics] Updating tokens for {tracker_name}")
        
        input_tokens = self.count_tokens(input_text)
        output_tokens = self.count_tokens(output_text)
        
        if tracker_name in self.token_trackers:
            print(f"[Diagnostics] Counted {input_tokens} input tokens, {output_tokens} output tokens")
            self.token_trackers[tracker_name].update(input_tokens, output_tokens)
        else:
            print(f"[Diagnostics] WARNING: Unknown tracker {tracker_name}")

    def log_token_usage(self):
        """Log current token usage with rich formatting"""
        if not self.enabled:
            return

        console.print("\nToken Usage Summary:")
        total_tokens = 0

        for name, tracker in self.token_trackers.items():
            total = tracker.tokens["input"] + tracker.tokens["output"]
            total_tokens += total

            console.print(
                Panel(
                    # f"Input: {tracker.tokens['input']}\n"
                    # f"Output: {tracker.tokens['output']}\n"
                    f"Total: {total}",
                    title=f"{name.title()}",
                )
            )

        percentage = (total_tokens / MAX_CONTEXT_TOKENS) * 100

        console.print(f"\nTotal Token Usage: {total_tokens}")
        console.print(f"Context Window Used: {percentage:.1f}%")

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=50),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            progress.add_task(
                "Context window usage", total=100, completed=min(percentage, 100)
            )

    def get_total_tokens(self) -> int:
        """Get total tokens across all trackers"""
        if not self.enabled:
            return 0
            
        total = 0
        for name, tracker in self.token_trackers.items():
            total += tracker.tokens["input"] + tracker.tokens["output"]
        
        print(f"[Diagnostics] Total tokens used: {total}")
        return total

    def reset(self):
        """Reset all token trackers"""
        for tracker in self.token_trackers.values():
            tracker.reset()


# Global diagnostics instance
diagnostics = Diagnostics()


def enable_diagnostics():
    diagnostics.enabled = True
    logging.info("Diagnostics enabled")


def disable_diagnostics():
    diagnostics.enabled = False
    logging.info("Diagnostics disabled")
