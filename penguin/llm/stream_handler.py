from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Callable


class StreamHandler(ABC):
    def __init__(self, chunk_callback: Callable[[str], None] = None):
        """
        Initialize with optional callback for chunk processing
        Args:
            chunk_callback: Function to handle each chunk of streamed content
        """
        self.chunk_callback = chunk_callback

    @abstractmethod
    async def handle_stream(self, stream: AsyncIterator[Any]) -> str:
        """Process a stream and return the collected response"""
        pass


class DefaultStreamHandler(StreamHandler):
    async def handle_stream(self, stream: AsyncIterator[Any]) -> str:
        collected_chunks = []
        try:
            async for chunk in stream:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        collected_chunks.append(delta.content)
                        if self.chunk_callback:
                            self.chunk_callback(delta.content)
            return "".join(collected_chunks)
        except Exception as e:
            raise ValueError(f"Error processing stream: {str(e)}")
