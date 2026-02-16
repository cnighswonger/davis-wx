/**
 * Context for weather background settings with localStorage persistence.
 *
 * Manages: enabled (on/off), intensity (0-100), and custom images per scene.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { API_BASE } from "../utils/constants.ts";

interface WeatherBackgroundContextValue {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  intensity: number;
  setIntensity: (v: number) => void;
  transparency: number;
  setTransparency: (v: number) => void;
  customImages: Record<string, string>;
  refreshCustomImages: () => void;
}

const WeatherBackgroundContext =
  createContext<WeatherBackgroundContextValue | null>(null);

const STORAGE_ENABLED = "davis-wx-weather-bg";
const STORAGE_INTENSITY = "davis-wx-weather-bg-intensity";
const STORAGE_TRANSPARENCY = "davis-wx-weather-bg-transparency";

function loadEnabled(): boolean {
  try {
    const v = localStorage.getItem(STORAGE_ENABLED);
    return v !== "off";
  } catch {
    return true;
  }
}

function loadIntensity(): number {
  try {
    const v = localStorage.getItem(STORAGE_INTENSITY);
    if (v !== null) {
      const n = parseInt(v, 10);
      if (!isNaN(n) && n >= 0 && n <= 100) return n;
    }
  } catch {
    /* ignore */
  }
  return 30;
}

function loadTransparency(): number {
  try {
    const v = localStorage.getItem(STORAGE_TRANSPARENCY);
    if (v !== null) {
      const n = parseInt(v, 10);
      if (!isNaN(n) && n >= 0 && n <= 100) return n;
    }
  } catch {
    /* ignore */
  }
  return 15;
}

export function WeatherBackgroundProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [enabled, setEnabledState] = useState(loadEnabled);
  const [intensity, setIntensityState] = useState(loadIntensity);
  const [transparency, setTransparencyState] = useState(loadTransparency);
  const [customImages, setCustomImages] = useState<Record<string, string>>({});

  const setEnabled = useCallback((v: boolean) => {
    setEnabledState(v);
    try {
      localStorage.setItem(STORAGE_ENABLED, v ? "on" : "off");
    } catch {
      /* ignore */
    }
  }, []);

  const setIntensity = useCallback((v: number) => {
    const clamped = Math.max(0, Math.min(100, v));
    setIntensityState(clamped);
    try {
      localStorage.setItem(STORAGE_INTENSITY, String(clamped));
    } catch {
      /* ignore */
    }
  }, []);

  const setTransparency = useCallback((v: number) => {
    const clamped = Math.max(0, Math.min(100, v));
    setTransparencyState(clamped);
    try {
      localStorage.setItem(STORAGE_TRANSPARENCY, String(clamped));
    } catch {
      /* ignore */
    }
  }, []);

  const refreshCustomImages = useCallback(() => {
    fetch(`${API_BASE}/api/backgrounds`)
      .then((r) => (r.ok ? r.json() : { scenes: {} }))
      .then((data: { scenes: Record<string, string> }) => {
        // Convert scene names to full URLs
        const images: Record<string, string> = {};
        for (const [scene, filename] of Object.entries(data.scenes)) {
          images[scene] = `${API_BASE}/backgrounds/${filename}`;
        }
        setCustomImages(images);
      })
      .catch(() => {
        /* ignore — backgrounds endpoint may not exist yet */
      });
  }, []);

  // Load custom images on mount
  useEffect(() => {
    refreshCustomImages();
  }, [refreshCustomImages]);

  return (
    <WeatherBackgroundContext.Provider
      value={{
        enabled,
        setEnabled,
        intensity,
        setIntensity,
        transparency,
        setTransparency,
        customImages,
        refreshCustomImages,
      }}
    >
      {children}
    </WeatherBackgroundContext.Provider>
  );
}

export function useWeatherBackground(): WeatherBackgroundContextValue {
  const ctx = useContext(WeatherBackgroundContext);
  if (ctx === null) {
    throw new Error(
      "useWeatherBackground must be used within a WeatherBackgroundProvider",
    );
  }
  return ctx;
}
