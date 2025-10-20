/**
 * Token stream processor with batching
 * Batches tokens for smooth rendering without overwhelming React
 */

import type { StreamConfig } from '../types';

export interface StreamProcessorCallbacks {
  onBatch: (batch: string) => void;
  onComplete?: () => void;
}

export class StreamProcessor {
  private buffer: string = '';
  private flushTimeout: NodeJS.Timeout | null = null;
  private config: StreamConfig;
  private callbacks: StreamProcessorCallbacks;

  constructor(config: StreamConfig, callbacks: StreamProcessorCallbacks) {
    this.config = config;
    this.callbacks = callbacks;
  }

  /**
   * Process a single token from the stream
   * Automatically batches based on config
   */
  processToken(token: string): void {
    this.buffer += token;

    // Debug: Log first few tokens
    if (this.buffer.length < 200) {
      console.error(`[StreamProcessor] token: "${token}", buffer: "${this.buffer}"`);
    }

    // Flush if buffer reaches batch size
    if (this.buffer.length >= this.config.batchSize) {
      this.flush();
    } else {
      // Schedule flush after delay
      this.scheduleFlush();
    }
  }

  /**
   * Flush the current buffer immediately
   */
  private flush(): void {
    if (this.buffer) {
      this.callbacks.onBatch(this.buffer);
      this.buffer = '';
    }
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
      this.flushTimeout = null;
    }
  }

  /**
   * Schedule a delayed flush
   */
  private scheduleFlush(): void {
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
    }
    this.flushTimeout = setTimeout(() => {
      this.flush();
    }, this.config.batchDelay);
  }

  /**
   * Complete the stream and flush any remaining tokens
   */
  complete(): void {
    console.log(`[StreamProcessor] complete() called. Buffer size: ${this.buffer.length}, content: "${this.buffer.substring(0, 50)}..."`);
    this.flush();
    console.log('[StreamProcessor] flush() completed, scheduling onComplete callback in 100ms');
    // Delay to ensure flush state update completes and all tokens are processed
    setTimeout(() => {
      console.log('[StreamProcessor] Calling onComplete callback');
      this.callbacks.onComplete?.();
    }, 100);
  }

  /**
   * Clean up timers
   */
  cleanup(): void {
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
      this.flushTimeout = null;
    }
    this.buffer = '';
  }

  /**
   * Get current buffer size (for debugging)
   */
  getBufferSize(): number {
    return this.buffer.length;
  }
}
