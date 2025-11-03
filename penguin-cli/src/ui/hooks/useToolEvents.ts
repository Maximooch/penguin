import { useCallback, useState, useRef, useEffect } from 'react';
import type { ActionResult, ToolEventNormalized } from '../../core/types';
import { shouldEmitUpdate } from '../utils/throttle.js';

const BATCH_INTERVAL_MS = 100; // Batch updates every 100ms

function deriveId(action: string, ts: number): string {
  // Stable-enough id when backend doesn't provide one
  return `${action}-${ts}`;
}

export function useToolEvents() {
  const [events, setEvents] = useState<ToolEventNormalized[]>([]);
  const lastUpdateById = new Map<string, number>();
  const pendingEvents = useRef<ToolEventNormalized[]>([]);
  const batchTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Flush pending events to state
  const flushPendingEvents = useCallback(() => {
    if (pendingEvents.current.length > 0) {
      const toAdd = pendingEvents.current;
      pendingEvents.current = [];
      setEvents((prev) => {
        // Merge pending events with existing, de-dup by id+phase
        const merged = [...prev];
        for (const event of toAdd) {
          const key = `${event.id}:${event.phase}`;
          const existing = merged.find((e) => `${e.id}:${e.phase}` === key);
          if (!existing) {
            merged.push(event);
          }
        }
        return merged.sort((a, b) => a.ts - b.ts);
      });
    }
    if (batchTimerRef.current) {
      clearTimeout(batchTimerRef.current);
      batchTimerRef.current = null;
    }
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (batchTimerRef.current) {
        clearTimeout(batchTimerRef.current);
      }
    };
  }, []);

  const addEvent = useCallback((event: ToolEventNormalized) => {
    // Throttle 'update' events to ~20fps (50ms)
    if (event.phase === 'update') {
      const last = lastUpdateById.get(event.id);
      if (!shouldEmitUpdate(last, event.ts, 50)) return;
      lastUpdateById.set(event.id, event.ts);
    }

    // Add to pending batch instead of immediate state update
    pendingEvents.current.push(event);

    // Schedule flush if not already scheduled
    if (!batchTimerRef.current) {
      batchTimerRef.current = setTimeout(flushPendingEvents, BATCH_INTERVAL_MS);
    }
  }, [flushPendingEvents]);

  const addFromActionResults = useCallback((results: ActionResult[]) => {
    const now = Date.now();
    const mapped: ToolEventNormalized[] = results.map((r, i) => ({
      id: deriveId(r.action, r.timestamp || now + i),
      phase: 'end',
      action: r.action,
      ts: r.timestamp || now + i,
      status: r.status === 'completed' ? 'completed' : r.status === 'error' ? 'error' : 'running',
      result: r.result,
    }));
    // Batch these as well
    pendingEvents.current.push(...mapped);
    if (!batchTimerRef.current) {
      batchTimerRef.current = setTimeout(flushPendingEvents, BATCH_INTERVAL_MS);
    }
  }, [flushPendingEvents]);

  const clear = useCallback(() => {
    // Clear pending events first
    pendingEvents.current = [];
    if (batchTimerRef.current) {
      clearTimeout(batchTimerRef.current);
      batchTimerRef.current = null;
    }
    setEvents([]);
  }, []);

  return {
    events,
    addEvent,
    addFromActionResults,
    clear,
    flush: flushPendingEvents, // Expose flush for immediate updates when needed
  };
}
