import { useCallback, useState } from 'react';
import type { ActionResult, ToolEventNormalized } from '../../core/types';
import { shouldEmitUpdate } from '../utils/throttle.js';

function deriveId(action: string, ts: number): string {
  // Stable-enough id when backend doesn't provide one
  return `${action}-${ts}`;
}

export function useToolEvents() {
  const [events, setEvents] = useState<ToolEventNormalized[]>([]);
  const lastUpdateById = new Map<string, number>();

  const addEvent = useCallback((event: ToolEventNormalized) => {
    // Throttle 'update' events to ~20fps (50ms)
    if (event.phase === 'update') {
      const last = lastUpdateById.get(event.id);
      if (!shouldEmitUpdate(last, event.ts, 50)) return;
      lastUpdateById.set(event.id, event.ts);
    }
    setEvents((prev) => {
      // de-dup by id+phase
      const key = `${event.id}:${event.phase}`;
      const existing = prev.find((e) => `${e.id}:${e.phase}` === key);
      if (existing) return prev;
      return [...prev, event].sort((a, b) => a.ts - b.ts);
    });
  }, []);

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
    setEvents((prev) => [...prev, ...mapped].sort((a, b) => a.ts - b.ts));
  }, []);

  const clear = useCallback(() => setEvents([]), []);

  return { events, addEvent, addFromActionResults, clear };
}
