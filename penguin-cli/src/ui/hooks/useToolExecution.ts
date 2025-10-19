/**
 * Hook for tracking tool execution state
 * Manages active and completed tool calls during conversation
 */

import { useState, useCallback } from 'react';
import type { ToolCall, ActionResult } from '../../core/types';

export interface UseToolExecutionReturn {
  activeTool: ToolCall | null;
  completedTools: ToolCall[];
  startTool: (action: string) => string;
  completeTool: (id: string, result: string, status: 'completed' | 'error') => void;
  clearTools: () => void;
  addActionResults: (results: ActionResult[]) => void;
}

export function useToolExecution(): UseToolExecutionReturn {
  const [activeTool, setActiveTool] = useState<ToolCall | null>(null);
  const [completedTools, setCompletedTools] = useState<ToolCall[]>([]);

  const startTool = useCallback((action: string): string => {
    const id = `tool-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const tool: ToolCall = {
      id,
      action,
      status: 'running',
      startTime: Date.now(),
    };
    setActiveTool(tool);
    return id;
  }, []);

  const completeTool = useCallback((id: string, result: string, status: 'completed' | 'error') => {
    setActiveTool((current) => {
      if (current?.id === id) {
        const completed: ToolCall = {
          ...current,
          status,
          result: status === 'completed' ? result : undefined,
          error: status === 'error' ? result : undefined,
          endTime: Date.now(),
        };
        setCompletedTools((prev) => [...prev, completed]);
        return null;
      }
      return current;
    });
  }, []);

  const addActionResults = useCallback((results: ActionResult[]) => {
    const newTools: ToolCall[] = results.map((result) => ({
      id: `tool-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      action: result.action,
      status: result.status === 'completed' ? 'completed' : 'error',
      result: result.status === 'completed' ? result.result : undefined,
      error: result.status === 'error' ? result.result : undefined,
      startTime: result.timestamp || Date.now(),
      endTime: result.timestamp || Date.now(),
    }));
    setCompletedTools((prev) => [...prev, ...newTools]);
  }, []);

  const clearTools = useCallback(() => {
    setActiveTool(null);
    setCompletedTools([]);
  }, []);

  return {
    activeTool,
    completedTools,
    startTool,
    completeTool,
    clearTools,
    addActionResults,
  };
}
