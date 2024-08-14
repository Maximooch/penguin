import logging

# import rich
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, TextColumn, BarColumn

console = Console()
MAX_CONTEXT_TOKENS = 200000  # Adjust this value as needed

class TokenTracker:
    def __init__(self):
        self.tokens = {'input': 0, 'output': 0}

    def update(self, input_tokens, output_tokens):
        self.tokens['input'] += input_tokens
        self.tokens['output'] += output_tokens

    def reset(self):
        self.tokens = {'input': 0, 'output': 0}

class Diagnostics:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.token_trackers = {
            'main_model': TokenTracker(),
            'tool_checker': TokenTracker(),
            'system_prompt': TokenTracker()
        }

    def update_tokens(self, tracker_name, input_tokens, output_tokens):
        if self.enabled:
            self.token_trackers[tracker_name].update(input_tokens, output_tokens)

    def log_token_usage(self):
        if not self.enabled:
            return

        console.print("\nToken Usage:")
        total_tokens = 0
        for name, tracker in self.token_trackers.items():
            total = tracker.tokens['input'] + tracker.tokens['output']
            total_tokens += total
            percentage = (total / MAX_CONTEXT_TOKENS) * 100
            console.print(f"{name.capitalize()}:")
            console.print(f"  Input: {tracker.tokens['input']}, Output: {tracker.tokens['output']}, Total: {total}")
            console.print(f"  Percentage of context window used: {percentage:.2f}%")
            
            with Progress(TextColumn("[progress.description]{task.description}"),
                          BarColumn(bar_width=50),
                          TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                          console=console) as progress:
                progress.add_task(f"Context window usage", total=100, completed=percentage)

        total_percentage = (total_tokens / MAX_CONTEXT_TOKENS) * 100
        console.print(f"\nTotal Token Usage: {total_tokens}")
        console.print(f"Total Percentage of Context Window Used: {total_percentage:.2f}%")

    def reset(self):
        for tracker in self.token_trackers.values():
            tracker.reset()

diagnostics = Diagnostics()

def enable_diagnostics():
    diagnostics.enabled = True
    logging.info("Diagnostics enabled")

def disable_diagnostics():
    diagnostics.enabled = False
    logging.info("Diagnostics disabled")