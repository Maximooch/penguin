/**
 * Hook for tracking progress during multi-step execution
 * Manages iteration count and progress messages
 */

import { useState, useCallback } from 'react';

export interface ProgressState {
  iteration: number;
  maxIterations: number;
  message?: string;
  isActive: boolean;
}

export interface UseProgressReturn {
  progress: ProgressState;
  updateProgress: (iteration: number, maxIterations: number, message?: string) => void;
  startProgress: (maxIterations: number) => void;
  completeProgress: () => void;
  resetProgress: () => void;
}

const initialState: ProgressState = {
  iteration: 0,
  maxIterations: 0,
  message: undefined,
  isActive: false,
};

export function useProgress(): UseProgressReturn {
  const [progress, setProgress] = useState<ProgressState>(initialState);

  const updateProgress = useCallback(
    (iteration: number, maxIterations: number, message?: string) => {
      setProgress({
        iteration,
        maxIterations,
        message,
        isActive: true,
      });
    },
    []
  );

  const startProgress = useCallback((maxIterations: number) => {
    setProgress({
      iteration: 1,
      maxIterations,
      message: 'Starting...',
      isActive: true,
    });
  }, []);

  const completeProgress = useCallback(() => {
    setProgress((prev) => ({
      ...prev,
      isActive: false,
      message: 'Complete',
    }));
  }, []);

  const resetProgress = useCallback(() => {
    setProgress(initialState);
  }, []);

  return {
    progress,
    updateProgress,
    startProgress,
    completeProgress,
    resetProgress,
  };
}
