import { describe, it, expect } from 'vitest';
import { shouldEmitUpdate } from '../../src/ui/utils/throttle';

describe('shouldEmitUpdate', () => {
  it('emits when no last timestamp', () => {
    expect(shouldEmitUpdate(undefined, 100, 50)).toBe(true);
  });
  it('drops updates under threshold', () => {
    expect(shouldEmitUpdate(100, 120, 50)).toBe(false);
  });
  it('emits at threshold', () => {
    expect(shouldEmitUpdate(100, 150, 50)).toBe(true);
  });
});

