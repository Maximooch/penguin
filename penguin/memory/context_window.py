# Class to handle context windows.
# Handles truncation through summarization and relevance to maintain context within a set limit.
# Keeps system messages out of the truncation.

# Should be modular in general according to Penguin standards.


# truncate non system messages when context window is exceeded. this will newly include summary notes in order to maintain context within the window.

# summary notes will work similar to declarative memory, but only for the session. After the session is over, the summary notes will be archived.


from typing import Any, Dict, List, Tuple

from llm.model_config import ModelConfig

from .summary_notes import SummaryNotes


class ContextWindowManager:
    def __init__(self, model_config: ModelConfig):
        self.max_tokens = model_config.max_tokens or 128000
        self.max_history_tokens = model_config.max_history_tokens or self.max_tokens
        self.summary_notes = SummaryNotes()

    def manage_context(
        self, messages: List[Dict[str, Any]], token_count: int
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Manage the context window when approaching or exceeding token limits.
        Returns: (processed_messages, was_truncated)
        """
        if token_count <= self.max_tokens:
            return messages, False

        # Separate system and non-system messages
        system_messages = [msg for msg in messages if msg["role"] == "system"]
        non_system_messages = [msg for msg in messages if msg["role"] != "system"]

        # Truncate oldest non-system messages
        truncated_non_system_messages = self._truncate_oldest_non_system_messages(
            non_system_messages
        )

        # Combine system and truncated non-system messages
        processed_messages = system_messages + truncated_non_system_messages

        return processed_messages, True

    def _truncate_oldest_non_system_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        total_tokens = 0
        truncated_messages = []
        for message in messages:
            message_tokens = self.adapter.count_tokens(str(message.get("content", "")))
            if total_tokens + message_tokens > self.max_history_tokens:
                break
            total_tokens += message_tokens
            truncated_messages.append(message)
        return truncated_messages
