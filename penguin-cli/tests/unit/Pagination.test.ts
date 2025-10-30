import { describe, it, expect } from 'vitest';
import { computeWindow } from '../../src/ui/utils/pagination';

describe('computeWindow', () => {
  it('returns last page by default', () => {
    const { start, end, pages } = computeWindow(100, 50, 0);
    expect({ start, end, pages }).toEqual({ start: 50, end: 100, pages: 2 });
  });

  it('supports older page offset', () => {
    const { start, end } = computeWindow(100, 50, 1);
    expect(start).toBe(0);
    expect(end).toBe(50);
  });

  it('clamps offset within bounds', () => {
    const { start, end } = computeWindow(10, 50, 10);
    expect(start).toBe(0);
    expect(end).toBe(10);
  });
});

