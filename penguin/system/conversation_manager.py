from pathlib import Path
import json
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ConversationManager:
    def __init__(self, conversations_path: Path):
        self.conversations_path = Path(conversations_path)
        self.conversations_path.mkdir(parents=True, exist_ok=True)
        
    def save_conversation(self, messages: List[Dict], name: Optional[str] = None) -> str:
        """Save a conversation with optional custom name"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        conv_name = name or f"conversation_{timestamp}"
        conv_path = self.conversations_path / f"{conv_name}.json"
        
        try:
            with conv_path.open('w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': timestamp,
                    'name': conv_name,
                    'messages': messages
                }, f, indent=2)
            return conv_name
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")
            raise

    def list_conversations(self) -> List[Dict]:
        """List all saved conversations"""
        conversations = []
        for conv_file in self.conversations_path.glob('*.json'):
            try:
                with conv_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    conversations.append({
                        'name': data.get('name', conv_file.stem),
                        'timestamp': data.get('timestamp'),
                        'path': str(conv_file)
                    })
            except Exception as e:
                logger.error(f"Error reading conversation {conv_file}: {e}")
                continue
        return sorted(conversations, key=lambda x: x['timestamp'], reverse=True)

    def load_conversation(self, name: str) -> Optional[List[Dict]]:
        """Load a specific conversation by name"""
        conv_path = self.conversations_path / f"{name}.json"
        try:
            with conv_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('messages', [])
        except FileNotFoundError:
            logger.error(f"Conversation {name} not found")
            return None
        except Exception as e:
            logger.error(f"Error loading conversation {name}: {e}")
            return None