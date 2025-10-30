import React, { createContext, useContext, useMemo, useState } from 'react';
import { tokens as defaultTokens, type PenguinTheme } from './tokens.js';

type ThemeName = 'default' | 'light';

const lightTokens: PenguinTheme = {
  ...defaultTokens,
  text: { primary: 'black', secondary: 'gray', muted: 'gray' },
  brand: { primary: 'blue', accent: 'cyan' },
  border: { default: 'gray', focused: 'blue' },
};

const THEMES: Record<ThemeName, PenguinTheme> = {
  default: defaultTokens,
  light: lightTokens,
};

interface ThemeContextValue {
  theme: PenguinTheme;
  name: ThemeName;
  setTheme: (name: ThemeName) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children, initial }: { children: React.ReactNode; initial?: ThemeName }) {
  const [name, setName] = useState<ThemeName>(initial || 'default');
  const value = useMemo(() => ({ theme: THEMES[name], name, setTheme: setName }), [name]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}

