export function computeWindow(total: number, pageSize: number, pageOffset: number) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const clampedOffset = Math.max(0, Math.min(pageOffset, pages - 1));
  const start = Math.max(0, total - pageSize * (clampedOffset + 1));
  const end = total - pageSize * clampedOffset;
  const hiddenOlder = start;
  return { start, end, hiddenOlder, pages, clampedOffset };
}

