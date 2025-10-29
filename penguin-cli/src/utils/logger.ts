/**
 * Minimal logger with runtime-configurable levels.
 * Defaults to 'error' to avoid interfering with Ink rendering.
 */

type Level = 'debug' | 'info' | 'warn' | 'error' | 'silent';

const levelOrder: Record<Level, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  silent: 50,
};

const envLevel = (process.env.PENGUIN_CLI_LOG_LEVEL || 'error').toLowerCase() as Level;
const currentLevel: Level = envLevel in levelOrder ? envLevel : 'error';

function shouldLog(target: Level): boolean {
  return levelOrder[target] >= levelOrder[currentLevel] && currentLevel !== 'silent';
}

export const logger = {
  debug: (...args: unknown[]) => {
    if (shouldLog('debug')) {
      // Write to stderr to avoid mixing with Ink stdout
      // Intentionally keep compact to minimize TTY interference
      // eslint-disable-next-line no-console
      console.error('[debug]', ...args);
    }
  },
  info: (...args: unknown[]) => {
    if (shouldLog('info')) {
      // eslint-disable-next-line no-console
      console.error('[info]', ...args);
    }
  },
  warn: (...args: unknown[]) => {
    if (shouldLog('warn')) {
      // eslint-disable-next-line no-console
      console.error('[warn]', ...args);
    }
  },
  error: (...args: unknown[]) => {
    if (shouldLog('error')) {
      // eslint-disable-next-line no-console
      console.error('[error]', ...args);
    }
  },
} as const;

