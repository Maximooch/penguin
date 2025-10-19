/**
 * StreamProcessor Tests
 * Validates token batching logic
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StreamProcessor } from '../../src/core/chat/StreamProcessor';

describe('StreamProcessor', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('batches tokens up to batch size', () => {
    const onBatch = vi.fn();
    const processor = new StreamProcessor(
      { batchSize: 5, batchDelay: 50 },
      { onBatch }
    );

    processor.processToken('Hello');
    expect(onBatch).toHaveBeenCalledWith('Hello');

    processor.cleanup();
  });

  it('flushes on complete', () => {
    const onBatch = vi.fn();
    const onComplete = vi.fn();
    const processor = new StreamProcessor(
      { batchSize: 100, batchDelay: 50 },
      { onBatch, onComplete }
    );

    processor.processToken('Hi');
    processor.complete();

    expect(onBatch).toHaveBeenCalledWith('Hi');
    expect(onComplete).toHaveBeenCalled();
  });
});
