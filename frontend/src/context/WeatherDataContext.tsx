// ============================================================
// React context that provides live weather data to the entire
// application. Combines WebSocket streaming with REST fallback
// for data that updates less frequently.
// ============================================================

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import type { ReactNode } from "react";
import type {
  CurrentConditions,
  ForecastResponse,
  AstronomyResponse,
  StationStatus,
  NowcastData,
} from "../api/types.ts";
import { WebSocketManager } from "../api/websocket.ts";
import {
  fetchCurrentConditions,
  fetchForecast,
  fetchAstronomy,
  fetchStationStatus,
  fetchNowcast,
  generateNowcast,
} from "../api/client.ts";
import { ASTRONOMY_REFRESH_INTERVAL, FORECAST_REFRESH_INTERVAL } from "../utils/constants.ts";

// --- Context value shape ---

interface WeatherDataContextValue {
  currentConditions: CurrentConditions | null;
  forecast: ForecastResponse | null;
  astronomy: AstronomyResponse | null;
  stationStatus: StationStatus | null;
  nowcast: NowcastData | null;
  /** Whether the backend reports the serial connection to the station is up. */
  connected: boolean;
  /** Whether our browser WebSocket to the backend is open. */
  wsConnected: boolean;
  /** Manually refresh forecast data. */
  refreshForecast: () => void;
  /** Manually refresh nowcast data. */
  refreshNowcast: () => void;
  /** WebSocket manager for alert subscriptions (null until connected). */
  ws: WebSocketManager | null;
}

const WeatherDataContext = createContext<WeatherDataContextValue | null>(null);

// --- Provider component ---

interface WeatherDataProviderProps {
  children: ReactNode;
}

export function WeatherDataProvider({ children }: WeatherDataProviderProps) {
  const [currentConditions, setCurrentConditions] =
    useState<CurrentConditions | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [astronomy, setAstronomy] = useState<AstronomyResponse | null>(null);
  const [stationStatus, setStationStatus] = useState<StationStatus | null>(
    null,
  );
  const [nowcast, setNowcast] = useState<NowcastData | null>(null);
  const [connected, setConnected] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const [ws, setWs] = useState<WebSocketManager | null>(null);

  // Refresh forecast data from REST endpoint.
  const refreshForecast = useCallback(() => {
    fetchForecast()
      .then(setForecast)
      .catch(() => {
        /* ignore -- will retry on next interval */
      });
  }, []);

  // Refresh nowcast data. When called explicitly (e.g. Refresh button),
  // triggers a new generation via POST then updates state with the result.
  const refreshNowcast = useCallback(() => {
    generateNowcast()
      .then(setNowcast)
      .catch(() => {
        // Generation failed or disabled — fall back to fetching latest.
        fetchNowcast().then(setNowcast).catch(() => {});
      });
  }, []);

  // Fetch slow-changing data (astronomy + station status + nowcast).
  const refreshSlowData = useCallback(() => {
    fetchAstronomy()
      .then(setAstronomy)
      .catch(() => {
        /* ignore -- will retry on next interval */
      });
    fetchStationStatus()
      .then(setStationStatus)
      .catch(() => {
        /* ignore */
      });
    refreshNowcast();
  }, [refreshNowcast]);

  useEffect(() => {
    // --- Initial REST fetches ---
    fetchCurrentConditions()
      .then(setCurrentConditions)
      .catch(() => {
        /* ignore */
      });
    fetchForecast()
      .then(setForecast)
      .catch(() => {
        /* ignore */
      });
    refreshSlowData();

    // Periodically refresh astronomy and station status.
    const slowTimer = setInterval(refreshSlowData, ASTRONOMY_REFRESH_INTERVAL);

    // Periodically refresh forecast data.
    const forecastTimer = setInterval(refreshForecast, FORECAST_REFRESH_INTERVAL);

    // --- WebSocket setup ---
    const manager = new WebSocketManager();
    setWs(manager);

    // Track WS connection state by polling the manager (the manager
    // itself does not emit events for its own connection state, so we use
    // a short poll that is cheap and avoids adding an event to the manager
    // just for this).
    const wsStateTimer = setInterval(() => {
      setWsConnected(manager.isConnected);
    }, 1000);

    manager.onMessage("sensor_update", (data) => {
      setCurrentConditions(data as CurrentConditions);
    });

    manager.onMessage("forecast_update", (data) => {
      setForecast(data as ForecastResponse);
    });

    manager.onMessage("connection_status", (data) => {
      setConnected(data as boolean);
    });

    manager.connect();

    return () => {
      clearInterval(slowTimer);
      clearInterval(forecastTimer);
      clearInterval(wsStateTimer);
      manager.disconnect();
      setWs(null);
    };
  }, [refreshSlowData, refreshForecast]);

  const value: WeatherDataContextValue = {
    currentConditions,
    forecast,
    astronomy,
    stationStatus,
    nowcast,
    connected,
    wsConnected,
    refreshForecast,
    refreshNowcast,
    ws,
  };

  return (
    <WeatherDataContext.Provider value={value}>
      {children}
    </WeatherDataContext.Provider>
  );
}

// --- Convenience hook ---

export function useWeatherData(): WeatherDataContextValue {
  const ctx = useContext(WeatherDataContext);
  if (ctx === null) {
    throw new Error("useWeatherData must be used within a WeatherDataProvider");
  }
  return ctx;
}
