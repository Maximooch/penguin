/**
 * Chat Accumulator Hook - Manages transcript state with static/dynamic split
 *
 * Owns the accumulator buffers and provides:
 * - onChunk() for processing stream events
 * - staticLines for finished content (never re-renders)
 * - dynamicLines for in-flight content (updates frequently)
 * - addUserMessage() for user input
 */

import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import {
  type Buffers,
  type Line,
  type PenguinStreamEvent,
  type StaticItem,
  createBuffers,
  resetBuffers,
  onChunk as processChunk,
  addUserMessage as accumulatorAddUser,
  addError,
  addStatus,
  addWelcome,
  toLines,
  isFinished,
} from '../../core/accumulator/index.js';

export interface UseChatAccumulatorOptions {
  /** Version string for welcome message */
  version?: string;
  /** Workspace name for welcome message */
  workspace?: string;
}

export interface UseChatAccumulatorReturn {
  // Lines for rendering
  staticLines: StaticItem[];
  dynamicLines: Line[];

  // Token count for display
  tokenCount: number;

  // Actions
  onChunk: (event: PenguinStreamEvent) => void;
  addUserMessage: (text: string) => void;
  addErrorMessage: (text: string) => void;
  addStatusMessage: (lines: string[]) => void;
  reset: () => void;

  // For advanced usage
  buffers: Buffers;
}

export function useChatAccumulator(options: UseChatAccumulatorOptions = {}): UseChatAccumulatorReturn {
  const { version = '0.1.0', workspace } = options;
  // Buffers ref - mutable, doesn't trigger re-renders directly
  const buffersRef = useRef<Buffers>(createBuffers());

  // Static lines - committed, never change
  const [staticLines, setStaticLines] = useState<StaticItem[]>([]);

  // Dynamic lines - in-flight, update frequently
  const [dynamicLines, setDynamicLines] = useState<Line[]>([]);

  // Token count for display
  const [tokenCount, setTokenCount] = useState(0);

  // Track which IDs have been committed to static
  const committedIdsRef = useRef<Set<string>>(new Set());

  // Track if welcome has been added
  const welcomeAddedRef = useRef(false);

  /**
   * Commit eligible lines from buffers to static
   * Lines are eligible when they're "finished" and not already committed
   */
  const commitEligibleLines = useCallback(() => {
    const b = buffersRef.current;
    const newlyCommitted: StaticItem[] = [];

    for (const id of b.order) {
      // Skip already committed
      if (committedIdsRef.current.has(id)) continue;

      const line = b.byId.get(id);
      if (!line) continue;

      // Welcome, user messages, errors, status, separators are immediately committable
      if (
        line.kind === 'welcome' ||
        line.kind === 'user' ||
        line.kind === 'error' ||
        line.kind === 'status' ||
        line.kind === 'separator'
      ) {
        committedIdsRef.current.add(id);
        newlyCommitted.push({ ...line }); // Immutable copy
        continue;
      }

      // For lines with phase, only commit when finished
      if (isFinished(line)) {
        committedIdsRef.current.add(id);
        newlyCommitted.push({ ...line }); // Immutable copy
      }
    }

    // Batch update static lines
    if (newlyCommitted.length > 0) {
      setStaticLines((prev) => [...prev, ...newlyCommitted]);
    }
  }, []);

  /**
   * Refresh dynamic lines from buffers
   * Only includes lines that haven't been committed to static
   */
  const refreshDynamicLines = useCallback(() => {
    const b = buffersRef.current;
    const dynamic: Line[] = [];

    for (const id of b.order) {
      // Skip committed lines
      if (committedIdsRef.current.has(id)) continue;

      const line = b.byId.get(id);
      if (line) {
        dynamic.push(line);
      }
    }

    setDynamicLines(dynamic);
    setTokenCount(b.tokenCount);
  }, []);

  /**
   * Full refresh - commit eligible and update dynamic
   * Called after processing chunks
   */
  const refresh = useCallback(() => {
    commitEligibleLines();
    refreshDynamicLines();
  }, [commitEligibleLines, refreshDynamicLines]);

  /**
   * Process a stream event
   */
  const onChunk = useCallback((event: PenguinStreamEvent) => {
    processChunk(buffersRef.current, event);
    // Use queueMicrotask for batching multiple rapid chunks
    queueMicrotask(refresh);
  }, [refresh]);

  /**
   * Add a user message
   */
  const addUserMessage = useCallback((text: string) => {
    accumulatorAddUser(buffersRef.current, text);
    refresh();
  }, [refresh]);

  /**
   * Add an error message
   */
  const addErrorMessage = useCallback((text: string) => {
    addError(buffersRef.current, text);
    refresh();
  }, [refresh]);

  /**
   * Add a status message
   */
  const addStatusMessage = useCallback((lines: string[]) => {
    addStatus(buffersRef.current, lines);
    refresh();
  }, [refresh]);

  /**
   * Reset all state
   */
  const reset = useCallback(() => {
    resetBuffers(buffersRef.current);
    committedIdsRef.current.clear();
    welcomeAddedRef.current = false;
    setStaticLines([]);
    setDynamicLines([]);
    setTokenCount(0);
  }, []);

  // Add welcome message on mount
  useEffect(() => {
    if (!welcomeAddedRef.current) {
      welcomeAddedRef.current = true;
      addWelcome(buffersRef.current, version, workspace);
      refresh();
    }
  }, [version, workspace, refresh]);

  return {
    staticLines,
    dynamicLines,
    tokenCount,
    onChunk,
    addUserMessage,
    addErrorMessage,
    addStatusMessage,
    reset,
    buffers: buffersRef.current,
  };
}
