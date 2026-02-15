import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { themes, defaultTheme, type Theme } from '../themes';

interface ThemeContextValue {
  theme: Theme;
  themeName: string;
  setThemeName: (name: string) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = 'davis-wx-theme';

function applyThemeToDOM(theme: Theme) {
  const root = document.documentElement;

  // Apply color CSS custom properties
  for (const [key, value] of Object.entries(theme.colors)) {
    const cssVar = `--color-${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`;
    root.style.setProperty(cssVar, value);
  }

  // Apply font CSS custom properties
  root.style.setProperty('--font-body', theme.fonts.body);
  root.style.setProperty('--font-heading', theme.fonts.heading);
  root.style.setProperty('--font-mono', theme.fonts.mono);
  root.style.setProperty('--font-gauge', theme.fonts.gauge);

  // Apply gauge CSS custom properties
  root.style.setProperty('--gauge-stroke-width', String(theme.gauge.strokeWidth));
  root.style.setProperty('--gauge-bg-opacity', String(theme.gauge.bgOpacity));
  root.style.setProperty('--gauge-shadow', theme.gauge.shadow);
  root.style.setProperty('--gauge-border-radius', theme.gauge.borderRadius);
}

function getInitialThemeName(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && stored in themes) {
      return stored;
    }
  } catch {
    // localStorage may be unavailable
  }
  return defaultTheme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [themeName, setThemeNameState] = useState<string>(getInitialThemeName);

  const theme = themes[themeName] ?? themes[defaultTheme];

  const setThemeName = useCallback((name: string) => {
    if (name in themes) {
      setThemeNameState(name);
      try {
        localStorage.setItem(STORAGE_KEY, name);
      } catch {
        // localStorage may be unavailable
      }
    }
  }, []);

  useEffect(() => {
    applyThemeToDOM(theme);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, themeName, setThemeName }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
