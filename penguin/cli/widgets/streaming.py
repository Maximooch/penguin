"""
Streaming State Machine for managing complex streaming logic.

This will be fully implemented in Phase 2 to replace the complex
streaming chain in ChatMessage.
"""

from enum import Enum
from typing import Optional, Callable, Any
import re


class StreamState(Enum):
    """States for the streaming state machine."""
    IDLE = "idle"
    STREAMING = "streaming"
    CLEANING = "cleaning"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    ERROR = "error"


class StreamingStateMachine:
    """
    State machine for handling streaming content.
    
    This will replace the complex 297-line chain in ChatMessage
    during Phase 2 refactoring.
    """
    
    def __init__(self):
        self.state = StreamState.IDLE
        self.buffer = ""
        self.cleaned_content = ""
        self.reasoning_buffer = ""
        self.chunk_count = 0
        
        # Callbacks
        self.on_chunk: Optional[Callable[[str], None]] = None
        self.on_complete: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        
    def process_chunk(self, chunk: str, is_final: bool = False) -> None:
        """
        Process a streaming chunk based on current state.
        
        Args:
            chunk: The text chunk to process
            is_final: Whether this is the final chunk
        """
        self.chunk_count += 1
        
        if self.state == StreamState.IDLE:
            self.state = StreamState.STREAMING
        
        if self.state == StreamState.STREAMING:
            # Add to buffer
            self.buffer += chunk
            
            # Clean streaming artifacts
            cleaned = self._clean_chunk(chunk)
            self.cleaned_content += cleaned
            
            # Check for reasoning content
            if self._is_reasoning_content(cleaned):
                self.reasoning_buffer += cleaned
            
            # Notify callback
            if self.on_chunk:
                self.on_chunk(cleaned)
            
            # Check if we should finalize
            if is_final:
                self.state = StreamState.FINALIZING
                self._finalize()
        
        elif self.state == StreamState.ERROR:
            # In error state, ignore further chunks
            return
    
    def _clean_chunk(self, chunk: str) -> str:
        """
        Clean streaming artifacts from a chunk.
        
        This is a simplified version - full implementation in Phase 2.
        """
        if not chunk:
            return chunk
        
        # Remove common artifacts
        cleaned = chunk
        artifacts = ['\x00', '\ufffd', '\r']
        for artifact in artifacts:
            cleaned = cleaned.replace(artifact, '')
        
        # Clean excessive whitespace
        cleaned = re.sub(r' {3,}', ' ', cleaned)
        cleaned = re.sub(r'\n{4,}', '\n\n\n', cleaned)
        
        return cleaned
    
    def _is_reasoning_content(self, content: str) -> bool:
        """Check if content appears to be reasoning/thinking content."""
        indicators = [
            "<thinking>",
            "</thinking>",
            "> ",  # Blockquote style reasoning
            "🧠",  # Reasoning emoji
        ]
        return any(indicator in content for indicator in indicators)
    
    def _finalize(self) -> None:
        """Finalize the streaming content."""
        self.state = StreamState.COMPLETE
        
        # Final cleanup
        final_content = self._final_cleanup(self.cleaned_content)
        
        # Process reasoning if present
        if self.reasoning_buffer:
            final_content = self._wrap_reasoning(final_content, self.reasoning_buffer)
        
        # Notify completion
        if self.on_complete:
            self.on_complete(final_content)
    
    def _final_cleanup(self, content: str) -> str:
        """Perform final cleanup on complete content."""
        # Remove trailing whitespace
        lines = content.split('\n')
        content = '\n'.join(line.rstrip() for line in lines)
        return content.strip()
    
    def _wrap_reasoning(self, content: str, reasoning: str) -> str:
        """Wrap reasoning content in collapsible section."""
        # Simple wrapping for now - full implementation in Phase 2
        if not reasoning.strip():
            return content
        
        wrapped = (
            "<details>\n"
            f"<summary>🧠 Internal Reasoning</summary>\n\n"
            f"{reasoning.strip()}\n\n"
            "</details>\n\n"
        )
        
        # Prepend reasoning to content
        return wrapped + content
    
    def reset(self) -> None:
        """Reset the state machine."""
        self.state = StreamState.IDLE
        self.buffer = ""
        self.cleaned_content = ""
        self.reasoning_buffer = ""
        self.chunk_count = 0
    
    def abort(self, error: str = "Stream aborted") -> None:
        """Abort the stream with an error."""
        self.state = StreamState.ERROR
        if self.on_error:
            self.on_error(error)
