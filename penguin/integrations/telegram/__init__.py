"""Optional Telegram channel integration."""

from penguin.integrations.telegram.binding_policy import (
    TelegramBinding,
    TelegramBindingPolicy,
)
from penguin.integrations.telegram.config import TelegramConfig
from penguin.integrations.telegram.manager import TelegramManager

__all__ = [
    "TelegramBinding",
    "TelegramBindingPolicy",
    "TelegramConfig",
    "TelegramManager",
]
