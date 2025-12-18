/**
 * Stream Processing - Drain streams with accumulator updates
 *
 * Handles streaming responses from the backend, updating buffers
 * and triggering UI refreshes.
 */

import type { Buffers, PenguinStreamEvent, DrainResult } from './types.js';
import { onChunk, markIncompleteToolsAsCancelled } from './accumulator.js';

/**
 * Drain a stream, processing each chunk through the accumulator
 *
 * @param stream - Async iterable of stream events
 * @param buffers - Buffers to update with stream data
 * @param refresh - Callback to trigger UI refresh
 * @param abortSignal - Optional signal to cancel processing
 * @returns DrainResult with stop reason and stats
 */
export async function drainStream(
  stream: AsyncIterable<PenguinStreamEvent>,
  buffers: Buffers,
  refresh: () => void,
  abortSignal?: AbortSignal,
): Promise<DrainResult> {
  const startTime = performance.now();
  let stopReason: DrainResult['stopReason'] = 'complete';

  try {
    for await (const event of stream) {
      // Check for cancellation
      if (abortSignal?.aborted) {
        stopReason = 'cancelled';
        markIncompleteToolsAsCancelled(buffers);
        queueMicrotask(refresh);
        break;
      }

      // Process the chunk
      onChunk(buffers, event);

      // Trigger refresh (throttled via queueMicrotask)
      queueMicrotask(refresh);

      // Check for completion or error events
      if (event.event === 'complete') {
        stopReason = 'complete';
      } else if (event.event === 'error') {
        stopReason = 'error';
      }
    }
  } catch (error) {
    stopReason = 'error';
    // Add error to transcript if it's a real error
    if (error instanceof Error) {
      onChunk(buffers, {
        event: 'error',
        data: { error: error.message },
      });
    }
  }

  // Final refresh
  queueMicrotask(refresh);

  return {
    stopReason,
    apiDurationMs: performance.now() - startTime,
    usage: { ...buffers.usage },
  };
}

/**
 * Create a throttled refresh function
 * Limits refresh calls to ~60fps to prevent UI thrashing
 *
 * @param actualRefresh - The actual refresh function to call
 * @param delayMs - Minimum delay between refreshes (default: 16ms for ~60fps)
 */
export function createThrottledRefresh(
  actualRefresh: () => void,
  delayMs: number = 16,
): () => void {
  let pending = false;

  return () => {
    if (pending) return;
    pending = true;
    setTimeout(() => {
      pending = false;
      actualRefresh();
    }, delayMs);
  };
}

/**
 * WebSocket event adapter - converts WebSocket messages to PenguinStreamEvent
 *
 * Use this to bridge between WebSocket events and the accumulator
 */
export function parseWebSocketMessage(data: unknown): PenguinStreamEvent | null {
  if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data);

      // Handle different message formats from the backend
      if (parsed.event && parsed.data) {
        return parsed as PenguinStreamEvent;
      }

      // Legacy format: { type: 'token', content: '...' }
      if (parsed.type) {
        return {
          event: mapLegacyEventType(parsed.type),
          data: parsed,
        };
      }

      return null;
    } catch {
      return null;
    }
  }

  return null;
}

/**
 * Map legacy event types to new format
 */
function mapLegacyEventType(
  type: string,
): PenguinStreamEvent['event'] {
  const mapping: Record<string, PenguinStreamEvent['event']> = {
    start: 'start',
    token: 'token',
    reasoning: 'reasoning',
    thinking: 'reasoning',
    tool_call: 'tool_call',
    tool_start: 'tool_call',
    tool_result: 'tool_result',
    tool_end: 'tool_result',
    progress: 'progress',
    complete: 'complete',
    done: 'complete',
    error: 'error',
  };

  return mapping[type] || 'token';
}

/**
 * Create an async iterable from WebSocket events
 * Useful for bridging WebSocket to the drainStream function
 */
export function createWebSocketStream(
  ws: WebSocket,
  abortSignal?: AbortSignal,
): AsyncIterable<PenguinStreamEvent> {
  return {
    [Symbol.asyncIterator]() {
      const queue: PenguinStreamEvent[] = [];
      let resolve: ((value: IteratorResult<PenguinStreamEvent>) => void) | null = null;
      let done = false;

      const handleMessage = (event: MessageEvent) => {
        const parsed = parseWebSocketMessage(event.data);
        if (parsed) {
          if (resolve) {
            resolve({ value: parsed, done: false });
            resolve = null;
          } else {
            queue.push(parsed);
          }
        }
      };

      const handleClose = () => {
        done = true;
        if (resolve) {
          resolve({ value: undefined as any, done: true });
          resolve = null;
        }
      };

      const handleError = () => {
        done = true;
        if (resolve) {
          resolve({ value: undefined as any, done: true });
          resolve = null;
        }
      };

      const handleAbort = () => {
        done = true;
        if (resolve) {
          resolve({ value: undefined as any, done: true });
          resolve = null;
        }
      };

      ws.addEventListener('message', handleMessage);
      ws.addEventListener('close', handleClose);
      ws.addEventListener('error', handleError);
      abortSignal?.addEventListener('abort', handleAbort);

      return {
        next(): Promise<IteratorResult<PenguinStreamEvent>> {
          if (queue.length > 0) {
            return Promise.resolve({ value: queue.shift()!, done: false });
          }

          if (done) {
            return Promise.resolve({ value: undefined as any, done: true });
          }

          return new Promise((r) => {
            resolve = r;
          });
        },

        return(): Promise<IteratorResult<PenguinStreamEvent>> {
          done = true;
          ws.removeEventListener('message', handleMessage);
          ws.removeEventListener('close', handleClose);
          ws.removeEventListener('error', handleError);
          abortSignal?.removeEventListener('abort', handleAbort);
          return Promise.resolve({ value: undefined as any, done: true });
        },
      };
    },
  };
}
