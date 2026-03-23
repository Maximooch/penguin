export function shouldEmitUpdate(lastTs: number | undefined, nextTs: number, minIntervalMs = 50): boolean {
  if (!lastTs) return true;
  return nextTs - lastTs >= minIntervalMs;
}

