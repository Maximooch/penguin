import { useCallback, useRef, useState } from 'react';

/**
 * A custom hook that keeps a React state and ref in sync.
 * Useful when you need immediate access to state values in async callbacks
 * that may close over stale state. The ref is updated synchronously before
 * the state, ensuring reliable checks in async operations.
 *
 * @param initialValue - The initial state value
 * @returns A tuple of [state, setState, ref]
 *
 * @example
 * const [streaming, setStreaming, streamingRef] = useSyncedState(false);
 *
 * // In async callback, check ref.current instead of state
 * const handleStreamEnd = async () => {
 *   if (streamingRef.current) {
 *     // This is guaranteed to be current, even in stale closures
 *     await cleanup();
 *   }
 * };
 */
export function useSyncedState<T>(
  initialValue: T,
): [T, (value: T) => void, React.MutableRefObject<T>] {
  const [state, setState] = useState(initialValue);
  const ref = useRef(initialValue);

  const setSyncedState = useCallback((value: T) => {
    ref.current = value;
    setState(value);
  }, []);

  return [state, setSyncedState, ref];
}
