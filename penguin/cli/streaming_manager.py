"""
Streaming Manager - Handle streaming state and progress tracking.

Extracted from PenguinCLI during Phase 4, Stage 3.
"""

from typing import Optional, List, Tuple


class StreamingManager:
    """Manages streaming state and progress tracking.

    Handles:
    - Streaming state management
    - Progress tracking and callbacks
    - Stream finalization
    - Safe progress stopping
    """

    def __init__(self, streaming_display):
        """Initialize StreamingManager.

        Args:
            streaming_display: StreamingDisplay instance
        """
        self.streaming_display = streaming_display
        self.is_streaming = False
        self.streaming_buffer = ""
        self.streaming_reasoning_buffer = ""
        self.streaming_role = "assistant"
        self._active_stream_id = None
        self._last_processed_turn = None
        self.progress = None

    def set_streaming(self, streaming: bool) -> None:
        """Set streaming state.

        Args:
            streaming: Whether streaming is active
        """
        self.is_streaming = streaming

    def reset_stream_state(self) -> None:
        """Forget the current stream: no stream id and empty buffers."""
        self.is_streaming = False
        self._active_stream_id = None
        self.streaming_buffer = ""
        self.streaming_reasoning_buffer = ""

    def finalize_streaming(self) -> None:
        """Finalize streaming session.

        Stops any active streaming display and resets buffers.
        """
        if self._active_stream_id is not None or self.is_streaming:
            if self.streaming_display.is_active:
                self.streaming_display.stop(finalize=True)
            self.reset_stream_state()

    def safely_stop_progress(self) -> None:
        """Safely stop any active progress displays.

        This method ensures that progress displays are stopped
        without raising exceptions, which is important for
        clean shutdown during streaming.
        """
        if self.progress is not None:
            try:
                self.progress.stop()
                self.progress = None
            except Exception:
                # Ignore errors when stopping progress
                pass

        # Also stop streaming display if active. The stream it was showing is
        # abandoned, so forget it too; otherwise the next stream's chunks are
        # ignored as belonging to a foreign stream.
        if self.streaming_display.is_active:
            try:
                self.streaming_display.stop(finalize=False)
            except Exception:
                # Ignore errors when stopping streaming
                pass
            self.reset_stream_state()

    def on_progress_update(self, data: dict) -> None:
        """Handle progress updates from Core.

        Args:
            data: Progress update data dictionary
        """
        progress_type = data.get("type", "unknown")
        message = data.get("message", "")

        if progress_type == "task_progress":
            # Update progress message
            if self.streaming_display.is_active:
                self.streaming_display.set_status(message)
        elif progress_type == "task_complete":
            # Task completed, stop progress
            self.safely_stop_progress()
        elif progress_type == "task_error":
            # Task error, stop progress and show error
            self.safely_stop_progress()

    def get_streaming_state(self) -> dict:
        """Get current streaming state.

        Returns:
            Dictionary with streaming state information
        """
        return {
            "is_streaming": self.is_streaming,
            "active_stream_id": self._active_stream_id,
            "streaming_role": self.streaming_role,
            "buffer_length": len(self.streaming_buffer),
            "reasoning_buffer_length": len(self.streaming_reasoning_buffer),
        }
