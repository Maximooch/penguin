/**
 * Streaming hook - Manages token batching and streaming state
 * Uses StreamProcessor for efficient rendering
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { StreamProcessor } from '../../core/chat/StreamProcessor';
import { logger } from '../../utils/logger';
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
  const onCompleteRef = useRef(onComplete); // Store callback in ref to avoid recreating processor

  // Update the callback ref when it changes
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    const config: StreamConfig = { batchSize, batchDelay };

    processorRef.current = new StreamProcessor(config, {
      onBatch: (batch) => {
        textRef.current += batch;
        setStreamingText(textRef.current);
      },
      onComplete: () => {
        setIsStreaming(false);
        onCompleteRef.current?.(textRef.current); // Use ref to get latest callback
      },
    });

    return () => {
      processorRef.current?.cleanup();
    };
  }, [batchSize, batchDelay]); // Remove onComplete from dependencies

  const processToken = useCallback((token: string) => {
    if (!isStreaming) {
      setIsStreaming(true);
    }
    processorRef.current?.processToken(token);
  }, [isStreaming]);

  const complete = useCallback(() => {
    logger.debug('[useStreaming] complete()', { length: textRef.current.length });
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
