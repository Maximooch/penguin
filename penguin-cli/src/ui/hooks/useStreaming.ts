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
  onComplete?: (finalText: string) => void;
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
  const textRef = useRef(''); // Keep track of accumulated text

  useEffect(() => {
    const config: StreamConfig = { batchSize, batchDelay };

    processorRef.current = new StreamProcessor(config, {
      onBatch: (batch) => {
        textRef.current += batch;
        setStreamingText(textRef.current);
      },
      onComplete: () => {
        setIsStreaming(false);
        onComplete?.(textRef.current); // Pass final text to callback
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
    console.log(`[useStreaming] complete() called. textRef.current length: ${textRef.current.length}`);
    processorRef.current?.complete();
  }, []);

  const reset = useCallback(() => {
    textRef.current = ''; // Clear the ref too
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
