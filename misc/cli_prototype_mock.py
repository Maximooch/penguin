"""
Prototype app to exercise Penguin CLI visuals without any LLM/API calls.

Run:
  python -m penguin.cli.cli_prototype_mock
or
  python penguin/cli/cli_prototype_mock.py

Keys/Commands:
  d  - inject a demo assistant message
  s  - simulate a streaming assistant reply
  a  - simulate an Action (request + result)
  t  - simulate a Tool (call + result)
  e  - simulate an error message
  g  - response-thread demo (Final + expandable steps/tools)
  k  - 4-message response-thread demo (reasoning, code/tool, notes, final)
  /demo sample  - inject collapsible reasoning message
  /exit - quit the prototype

You can also use regular CLI commands:
  /help
  /tokens
  /context list
"""

from __future__ import annotations

import asyncio
from penguin.constants import UI_ASYNC_SLEEP_SECONDS
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import logging
import argparse
from datetime import datetime

# Ensure the package root is on sys.path when running this file directly
_PKG_PARENT = Path(__file__).resolve().parents[2]  # .../penguin
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from rich.console import Console
from rich.live import Live

from penguin.cli.ui import CLIRenderer
from penguin.system.state import MessageCategory

# Disable EventBus for prototype
import penguin.cli.events as events_mod
_original_get_sync = None

def _mock_event_bus():
    """Mock EventBus that does nothing"""
    class MockEventBus:
        def subscribe(self, event_type, callback):
            pass
        def publish(self, event_type, data):
            pass
        def unsubscribe(self, event_type, callback):
            pass
    return MockEventBus()

def disable_event_bus():
    """Temporarily disable EventBus for prototype"""
    global _original_get_sync
    if hasattr(events_mod, 'EventBus'):
        _original_get_sync = events_mod.EventBus.get_sync
        events_mod.EventBus.get_sync = _mock_event_bus

def restore_event_bus():
    """Restore EventBus after prototype"""
    global _original_get_sync
    if _original_get_sync and hasattr(events_mod, 'EventBus'):
        events_mod.EventBus.get_sync = _original_get_sync


class MockCore:
    """Mock PenguinCore for prototype testing"""

    def __init__(self):
        self.conversation_manager = MockConversationManager()
        self.model_config = MockModelConfig()
        self.current_runmode_status_summary = "RunMode idle."
        self._ui_callbacks = []

        # Token usage state
        self._token_usage = {
            "current_total_tokens": 1500,
            "max_context_window_tokens": 200000,  # Context window capacity
            "categories": {
                "DIALOG": 800,
                "SYSTEM_OUTPUT": 400,
                "CONTEXT": 200,
                "SYSTEM": 100,
            }
        }

    def register_ui(self, callback):
        """Register UI callback"""
        self._ui_callbacks.append(callback)

    async def emit_ui_event(self, event_type: str, data: Dict[str, Any]):
        """Emit UI event to all registered callbacks"""
        for callback in self._ui_callbacks:
            if asyncio.iscoroutinefunction(callback):
                await callback(event_type, data)
            else:
                callback(event_type, data)

    def get_token_usage(self) -> Dict[str, Any]:
        """Get mock token usage"""
        return self._token_usage

    def update_token_usage(self, delta: int = 100):
        """Update token usage for demo purposes"""
        self._token_usage["current_total_tokens"] += delta
        self._token_usage["categories"]["DIALOG"] += delta


class MockModelConfig:
    """Mock ModelConfig"""

    def __init__(self):
        self.model = "mock-gpt-4"
        self.provider = "mock"
        self.streaming_enabled = True
        self.max_context_window_tokens = 200000  # Context window capacity


class MockConversationManager:
    """Mock ConversationManager"""

    def __init__(self):
        self.conversation = MockConversation()

    def get_token_usage(self) -> Dict[str, Any]:
        """Return mock token usage"""
        return {
            "current_total_tokens": 1500,
            "max_context_window_tokens": 200000,  # Context window capacity
            "categories": {
                "DIALOG": 800,
                "SYSTEM_OUTPUT": 400,
                "CONTEXT": 200,
                "SYSTEM": 100,
            }
        }


class MockConversation:
    """Mock Conversation"""

    def __init__(self):
        self.session = MockSession()


class MockSession:
    """Mock Session with messages list"""

    def __init__(self):
        self.messages = []
        self.id = "mock_session_123"


class MockMessage:
    """Mock Message object"""

    def __init__(self, role: str, content: str, category: MessageCategory,
                 timestamp: Optional[str] = None, metadata: Optional[Dict] = None):
        self.role = role
        self.content = content
        self.category = category
        self.timestamp = timestamp or datetime.now().isoformat()
        self.metadata = metadata or {}


class PrototypeCLI:
    """Prototype CLI that mimics the real CLI but without LLM calls"""

    def __init__(self):
        # Disable EventBus before creating renderer
        disable_event_bus()

        self.console = Console()
        self.core = MockCore()

        # Initialize with welcome message BEFORE creating renderer
        welcome_msg = MockMessage(
            role="system",
            content="Prototype CLI (no LLM)\n\n"
                   "Commands: d (demo msg), s (stream), a (action), t (tool), e (error), "
                   "g (RespThread), k (4-msg thread)\n"
                   "Also supports: /help, /tokens, /context, /demo sample, /exit",
            category=MessageCategory.SYSTEM
        )
        self.core.conversation_manager.conversation.session.messages.append(welcome_msg)

        # Now create renderer (it will read the welcome message)
        self.renderer = CLIRenderer(self.console, self.core)
        self.running = True

    async def demo_message(self):
        """Inject a demo assistant message"""
        content = (
            "<details>\n<summary>Plan / Steps</summary>\n\n"
            "1) Parse input\n\n"
            "2) Select tool(s)\n\n"
            "3) Summarize results\n\n"
            "</details>\n\n"
            "### Final\nUse endpoint X with key Y; fallback to cache on 404.\n\n"
            "Here is a short demo reply.\n\n"
            "```python\nprint('hello from Penguin prototype')\n```\n\n"
            "```diff\n--- a/demo.txt\n+++ b/demo.txt\n"
            "@@ -1,1 +1,3 @@\n-demo\n+demo\n+added-1\n+added-2\n```"
        )

        msg = MockMessage(
            role="assistant",
            content=content,
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(msg)

        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": content,
            "category": MessageCategory.DIALOG
        })

        # Update token usage
        self.core.update_token_usage(250)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def stream_sample(self):
        """Simulate streaming response"""
        long_md = (
            "Here is a longer, streaming markdown demo.\n\n"
            "### Bullet list\n- One\n- Two\n- Three\n\n"
            "### Code\n```python\nfor i in range(5):\n    print(i)\n```\n\n"
            "### Table\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n"
            "### Paragraphs\n"
            + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 12)
            + "\n\nEnd.\n"
        )

        chunks = [long_md[i:i+160] for i in range(0, len(long_md), 160)]
        accumulated_content = ""

        for i, chunk in enumerate(chunks, 1):
            accumulated_content += chunk
            await self.core.emit_ui_event("stream_chunk", {
                "role": "assistant",
                "content_so_far": accumulated_content,
                "is_final": False,
                "stream_id": "demo"
            })
            await asyncio.sleep(UI_ASYNC_SLEEP_SECONDS)

        # Final chunk
        await self.core.emit_ui_event("stream_chunk", {
            "role": "assistant",
            "content_so_far": accumulated_content,
            "is_final": True,
            "stream_id": "demo"
        })

        # Add to message history
        msg = MockMessage(
            role="assistant",
            content=accumulated_content,
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(msg)

        # Update tokens
        self.core.update_token_usage(300)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def action_sample(self):
        """Simulate an action request and result"""
        # Action request
        action_msg = MockMessage(
            role="assistant",
            content="Executing Python code to check file...",
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(action_msg)

        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": "Executing Python code to check file...",
            "category": MessageCategory.DIALOG
        })

        await asyncio.sleep(0.5)

        # Action result
        result_content = "cwd=/tmp\nexists: False\n\nFile not found at expected location."
        result_msg = MockMessage(
            role="system",
            content=f"**Action Result:**\n```\n{result_content}\n```",
            category=MessageCategory.SYSTEM_OUTPUT
        )
        self.core.conversation_manager.conversation.session.messages.append(result_msg)

        await self.core.emit_ui_event("message", {
            "role": "system",
            "content": f"**Action Result:**\n```\n{result_content}\n```",
            "category": MessageCategory.SYSTEM_OUTPUT
        })

        self.core.update_token_usage(150)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def tool_sample(self):
        """Simulate a tool call and result"""
        # Tool call
        tool_call_msg = MockMessage(
            role="assistant",
            content="Searching workspace for 'auth flow'...",
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(tool_call_msg)

        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": "Searching workspace for 'auth flow'...",
            "category": MessageCategory.DIALOG
        })

        await asyncio.sleep(0.5)

        # Tool result with long listing
        long_listing = "\n".join(
            [f"- pkg/file_{i:02d}.py:{i} call_{i}()" for i in range(1, 28)]
        )
        result_msg = MockMessage(
            role="system",
            content=f"**Search Results:**\n```\n{long_listing}\n```",
            category=MessageCategory.SYSTEM_OUTPUT
        )
        self.core.conversation_manager.conversation.session.messages.append(result_msg)

        await self.core.emit_ui_event("message", {
            "role": "system",
            "content": f"**Search Results:**\n```\n{long_listing}\n```",
            "category": MessageCategory.SYSTEM_OUTPUT
        })

        self.core.update_token_usage(200)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def error_sample(self):
        """Simulate an error message"""
        error_msg = MockMessage(
            role="system",
            content="**Error:** Sample error while parsing configuration.\n\n"
                   "Context: prototype demo environment",
            category=MessageCategory.SYSTEM_OUTPUT,
            metadata={"error": True}
        )
        self.core.conversation_manager.conversation.session.messages.append(error_msg)

        await self.core.emit_ui_event("error", {
            "message": "Sample error while parsing configuration",
            "details": "Context: prototype demo environment"
        })

    async def response_thread_demo(self):
        """Show a compact response-thread: Final visible + collapsed Steps/Tools"""
        content = (
            "### Final\n"
            "Use the Auth service's refresh endpoint and cache misses to Redis.\n\n"
            "- Endpoint: `POST /v1/tokens/refresh`\n"
            "- Fallback: serve last-good token from Redis for ≤60s window\n\n"
            "<details>\n"
            "<summary>Show steps, tools, and drafts</summary>\n\n"
            "<details>\n"
            "<summary>[3] Steps</summary>\n\n"
            "<details>\n"
            "<summary>Parse input</summary>\n\n"
            "Tokenize and normalize user input; extract intent, entities, and constraints.\n\n"
            "</details>\n\n"
            "<details>\n"
            "<summary>Select tools</summary>\n\n"
            "Choose workspace_search for code intel and run execute for quick validation.\n\n"
            "</details>\n\n"
            "<details>\n"
            "<summary>Summarize results</summary>\n\n"
            "Aggregate findings; present concise final guidance.\n\n"
            "</details>\n\n"
            "</details>\n\n"
            "#### Tool: workspace_search (call)\n"
            "```json\n{\n  \"tool\": \"workspace_search\",\n  \"query\": \"auth refresh token\",\n  \"max\": 5\n}\n```\n\n"
            "#### Tool: workspace_search (result preview)\n"
            "```text\n- services/auth/token.py:41 refresh_token()\n"
            "- services/auth/client.py:88 refresh()\n"
            "- apps/web/routes/auth.py:132 post_refresh()\n...\n```\n\n"
            "#### Draft (hidden by default)\n"
            "> Evaluate pros/cons of optimistic cache; confirm TTL semantics.\n\n"
            "</details>\n"
        )

        msg = MockMessage(
            role="assistant",
            content=content,
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(msg)

        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": content,
            "category": MessageCategory.DIALOG
        })

        self.core.update_token_usage(400)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def response_thread_demo_four(self):
        """Emit 4 separate messages: collapsed Reasoning, Code/Tool, Notes, Final"""
        # Message 1: Reasoning
        msg1 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "I need to understand the auth flow first. Let me scan the codebase for token refresh logic. "
            "I'll use workspace_search to find relevant files, then examine the implementation. "
            "This should give me the context I need to provide accurate guidance.\n\n"
            "</details>\n\n"
            "Looking at the codebase structure to understand auth flow..."
        )

        message1 = MockMessage(role="assistant", content=msg1, category=MessageCategory.DIALOG)
        self.core.conversation_manager.conversation.session.messages.append(message1)
        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": msg1,
            "category": MessageCategory.DIALOG
        })
        await asyncio.sleep(0.1)

        # Message 2: Code/Tool findings
        msg2 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "Found `services/auth/token.py` with a `refresh_token` function. "
            "Let me examine its implementation to see how it currently works. "
            "I should check if there's already caching logic or if we need to add it.\n\n"
            "</details>\n\n"
            "Found the token refresh logic in `services/auth/token.py`. Here's the current implementation:\n\n"
            "```python\n"
            "def refresh_token(old_token: str) -> str:\n"
            "    # Validate old token\n"
            "    payload = verify(old_token)\n"
            "    # Generate new token\n"
            "    return create_token(payload)\n"
            "```"
        )

        message2 = MockMessage(role="assistant", content=msg2, category=MessageCategory.DIALOG)
        self.core.conversation_manager.conversation.session.messages.append(message2)
        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": msg2,
            "category": MessageCategory.DIALOG
        })
        await asyncio.sleep(0.1)

        # Message 3: Notes
        msg3 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "I notice there's no caching layer yet. The current implementation just validates and creates a new token. "
            "For the requirement, we need to add Redis caching with 60s TTL and handle upstream failures gracefully.\n\n"
            "</details>\n\n"
            "I see the endpoint is at `/v1/tokens/refresh`. Currently there's no caching - "
            "each request hits the token service directly."
        )

        message3 = MockMessage(role="assistant", content=msg3, category=MessageCategory.DIALOG)
        self.core.conversation_manager.conversation.session.messages.append(message3)
        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": msg3,
            "category": MessageCategory.DIALOG
        })
        await asyncio.sleep(0.1)

        # Message 4: Final answer
        msg4 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "Let me structure the recommendation clearly. The solution needs:\n"
            "1. Endpoint that validates and refreshes tokens\n"
            "2. Redis cache layer with 60s TTL\n"
            "3. Fallback logic for upstream failures\n"
            "This is straightforward - we just need to add a caching middleware.\n\n"
            "</details>\n\n"
            "Use `POST /v1/tokens/refresh` with Redis caching:\n\n"
            "**Implementation:**\n\n"
            "- Endpoint validates old token and generates new one with same claims\n"
            "- Cache successful responses in Redis: `token:refresh:{user_id}` with 60s TTL\n"
            "- On upstream 5xx errors: serve cached token if available (≤60s old) and log warning\n"
            "- Return 503 only if both upstream and cache fail"
        )

        message4 = MockMessage(role="assistant", content=msg4, category=MessageCategory.DIALOG)
        self.core.conversation_manager.conversation.session.messages.append(message4)
        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": msg4,
            "category": MessageCategory.DIALOG
        })

        self.core.update_token_usage(500)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def demo_collapsible(self):
        """Inject a demo message with collapsible reasoning"""
        content = (
            "<details>\n"
            "<summary>🧠  Click to show / hide internal reasoning</summary>\n\n"
            "### Internal reasoning (collapsible)\n\n"
            "1. Parse the user's request\n"
            "2. Decide on tone → friendly but direct\n"
            "3. Build a short factual statement\n"
            "4. Offer next actionable step\n\n"
            "> _Note: this section is hidden by default – press ENTER to expand / collapse._\n\n"
            "</details>\n\n"
            "---\n\n"
            "### Final answer (always visible)\n\n"
            "This is a demo assistant reply rendered by `/demo sample`.\n"
            "Use it to verify that collapsible reasoning works correctly in the UI."
        )

        msg = MockMessage(
            role="assistant",
            content=content,
            category=MessageCategory.DIALOG,
            metadata={"demo": True}
        )
        self.core.conversation_manager.conversation.session.messages.append(msg)

        await self.core.emit_ui_event("message", {
            "role": "assistant",
            "content": content,
            "category": MessageCategory.DIALOG,
            "metadata": {"demo": True}
        })

        self.core.update_token_usage(180)
        await self.core.emit_ui_event("token_update", self.core.get_token_usage())

    async def handle_input(self, user_input: str):
        """Handle user input and route to appropriate handler"""
        # Add user message to history
        user_msg = MockMessage(
            role="user",
            content=user_input,
            category=MessageCategory.DIALOG
        )
        self.core.conversation_manager.conversation.session.messages.append(user_msg)

        await self.core.emit_ui_event("message", {
            "role": "user",
            "content": user_input,
            "category": MessageCategory.DIALOG
        })

        # Route based on input
        cmd = user_input.strip().lower()

        if cmd == "d":
            await self.demo_message()
        elif cmd == "s":
            await self.stream_sample()
        elif cmd == "a":
            await self.action_sample()
        elif cmd == "t":
            await self.tool_sample()
        elif cmd == "e":
            await self.error_sample()
        elif cmd == "g":
            await self.response_thread_demo()
        elif cmd == "k":
            await self.response_thread_demo_four()
        elif cmd in ["/demo sample", "/debug sample"]:
            await self.demo_collapsible()
        elif cmd == "/exit":
            self.running = False
        elif cmd == "/help":
            help_msg = MockMessage(
                role="system",
                content="**Available Commands:**\n\n"
                       "- d: Demo message\n"
                       "- s: Streaming sample\n"
                       "- a: Action sample\n"
                       "- t: Tool sample\n"
                       "- e: Error sample\n"
                       "- g: Response thread demo\n"
                       "- k: 4-message thread demo\n"
                       "- /demo sample: Collapsible reasoning demo\n"
                       "- /help: Show this help\n"
                       "- /tokens: Show token usage\n"
                       "- /exit: Quit prototype",
                category=MessageCategory.SYSTEM
            )
            self.core.conversation_manager.conversation.session.messages.append(help_msg)
            await self.core.emit_ui_event("message", {
                "role": "system",
                "content": help_msg.content,
                "category": MessageCategory.SYSTEM
            })
        elif cmd == "/tokens":
            usage = self.core.get_token_usage()
            tokens_msg = MockMessage(
                role="system",
                content=f"**Token Usage:**\n\n"
                       f"- Total: {usage['current_total_tokens']:,} / {usage.get('max_context_window_tokens', usage.get('max_tokens', 0)):,}\n"  # Context window usage
                       f"- Dialog: {usage['categories']['DIALOG']:,}\n"
                       f"- System Output: {usage['categories']['SYSTEM_OUTPUT']:,}\n"
                       f"- Context: {usage['categories']['CONTEXT']:,}\n"
                       f"- System: {usage['categories']['SYSTEM']:,}",
                category=MessageCategory.SYSTEM
            )
            self.core.conversation_manager.conversation.session.messages.append(tokens_msg)
            await self.core.emit_ui_event("message", {
                "role": "system",
                "content": tokens_msg.content,
                "category": MessageCategory.SYSTEM
            })
        else:
            # Echo back as a simple response
            echo_msg = MockMessage(
                role="assistant",
                content=f"Prototype mode: received '{user_input}'\n\n"
                       f"This is a mock CLI. Try commands like: d, s, a, t, e, g, k, /help, /exit",
                category=MessageCategory.DIALOG
            )
            self.core.conversation_manager.conversation.session.messages.append(echo_msg)
            await self.core.emit_ui_event("message", {
                "role": "assistant",
                "content": echo_msg.content,
                "category": MessageCategory.DIALOG
            })

    async def run(self):
        """Main event loop"""
        # Set model name
        self.renderer.set_current_model("mock-gpt-4 (prototype)")

        # Initialize renderer
        self.renderer.initialize()

        # Create live display
        with Live(
            self.renderer.get_display_renderable(),
            console=self.console,
            refresh_per_second=10,
            auto_refresh=True
        ) as live:
            self.renderer.set_live_display(live)

            # Main loop
            while self.running:
                try:
                    # Get user input (blocking)
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.console.input("[bold cyan]You:[/] ")
                    )

                    if user_input.strip():
                        await self.handle_input(user_input)

                except KeyboardInterrupt:
                    self.running = False
                    break
                except EOFError:
                    self.running = False
                    break
                except Exception as e:
                    logging.error(f"Error in main loop: {e}", exc_info=True)
                    self.console.print(f"[red]Error: {e}[/red]")

        self.console.print("\n[dim]Goodbye from Penguin CLI Prototype![/dim]")

    def __del__(self):
        """Cleanup when prototype exits"""
        restore_event_bus()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Penguin CLI prototype")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(
                Path(__file__).resolve().with_name("cli_prototype_debug.log"),
                mode="a",
                encoding="utf-8"
            ),
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info("[proto] Launching PrototypeCLI")

    # Run the prototype
    app = PrototypeCLI()
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
