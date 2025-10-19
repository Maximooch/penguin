/**
 * Streaming hook - Manages token batching and streaming state
 * Uses StreamProcessor for efficient rendering
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { StreamProcessor } from '../../core/chat/StreamProcessor';
import type { StreamConfig } from '../../core/types';

export interface UseStreamingOptions {
  batchSize?: number;
  batchDelay?: number;
  onComplete?: () => void;
}

export function useStreaming(options: UseStreamingOptions = {}) {
  const {
    batchSize = 50,
    batchDelay = 50,
    onComplete,
  } = options;

  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const processorRef = useRef<StreamProcessor | null>(null);

  useEffect(() => {
    const config: StreamConfig = { batchSize, batchDelay };

    processorRef.current = new StreamProcessor(config, {
      onBatch: (batch) => setStreamingText((prev) => prev + batch),
      onComplete: () => {
        setIsStreaming(false);
        onComplete?.();
      },
    });

    return () => {
      processorRef.current?.cleanup();
    };
  }, [batchSize, batchDelay, onComplete]);

  const processToken = useCallback((token: string) => {
    if (!isStreaming) {
      setIsStreaming(true);
    }
    processorRef.current?.processToken(token);
  }, [isStreaming]);

  const complete = useCallback(() => {
    processorRef.current?.complete();
  }, []);

  const reset = useCallback(() => {
    setStreamingText('');
    setIsStreaming(false);
  }, []);

  return {
    streamingText,
    isStreaming,
    processToken,
    complete,
    reset,
  };
}
