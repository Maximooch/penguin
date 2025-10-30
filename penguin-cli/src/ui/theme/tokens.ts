/**
 * Penguin CLI design tokens (minimal, semantic-first).
 * Inspired by Gemini CLI's semantic-colors.
 */

export type PenguinTheme = {
  text: { primary: string; secondary: string; muted: string };
  brand: { primary: string; accent: string };
  status: { success: string; warning: string; error: string; info: string };
  border: { default: string; focused: string };
  spacing: { xs: number; sm: number; md: number; lg: number };
  icons: { dot: string; spinner: string };
};

// Default dark-friendly palette with cyan/blue brand
export const tokens: PenguinTheme = {
  text: {
    primary: 'white',
    secondary: 'gray',
    muted: 'dim',
  },
  brand: {
    primary: 'cyan',
    accent: 'blue',
  },
  status: {
    success: 'green',
    warning: 'yellow',
    error: 'red',
    info: 'cyan',
  },
  border: {
    default: 'gray',
    focused: 'cyan',
  },
  spacing: { xs: 0, sm: 1, md: 2, lg: 3 },
  icons: { dot: '•', spinner: '…' },
};

