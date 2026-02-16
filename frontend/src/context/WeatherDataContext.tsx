// ============================================================
// React context that provides live weather data to the entire
// application. Combines WebSocket streaming with REST fallback
// for data that updates less frequently.
// ============================================================

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import type { ReactNode } from "react";
import type {
  CurrentConditions,
  ForecastResponse,
  AstronomyResponse,
  StationStatus,
} from "../api/types.ts";
import { WebSocketManager } from "../api/websocket.ts";
import {
  fetchCurrentConditions,
  fetchForecast,
  fetchAstronomy,
  fetchStationStatus,
} from "../api/client.ts";
import { ASTRONOMY_REFRESH_INTERVAL, FORECAST_REFRESH_INTERVAL } from "../utils/constants.ts";

// --- Context value shape ---

interface WeatherDataContextValue {
  currentConditions: CurrentConditions | null;
  forecast: ForecastResponse | null;
  astronomy: AstronomyResponse | null;
  stationStatus: StationStatus | null;
  /** Whether the backend reports the serial connection to the station is up. */
  connected: boolean;
  /** Whether our browser WebSocket to the backend is open. */
  wsConnected: boolean;
  /** Manually refresh forecast data. */
  refreshForecast: () => void;
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
  const [connected, setConnected] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const wsRef = useRef<WebSocketManager | null>(null);

  // Refresh forecast data from REST endpoint.
  const refreshForecast = useCallback(() => {
    fetchForecast()
      .then(setForecast)
      .catch(() => {
        /* ignore -- will retry on next interval */
      });
  }, []);

  // Fetch slow-changing data (astronomy + station status).
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
  }, []);

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
    const ws = new WebSocketManager();
    wsRef.current = ws;

    // Track WS connection state by polling the manager (the manager
    // itself does not emit events for its own connection state, so we use
    // a short poll that is cheap and avoids adding an event to the manager
    // just for this).
    const wsStateTimer = setInterval(() => {
      setWsConnected(ws.isConnected);
    }, 1000);

    ws.onMessage("sensor_update", (data) => {
      setCurrentConditions(data as CurrentConditions);
    });

    ws.onMessage("forecast_update", (data) => {
      setForecast(data as ForecastResponse);
    });

    ws.onMessage("connection_status", (data) => {
      setConnected(data as boolean);
    });

    ws.connect();

    return () => {
      clearInterval(slowTimer);
      clearInterval(forecastTimer);
      clearInterval(wsStateTimer);
      ws.disconnect();
      wsRef.current = null;
    };
  }, [refreshSlowData, refreshForecast]);

  const value: WeatherDataContextValue = {
    currentConditions,
    forecast,
    astronomy,
    stationStatus,
    connected,
    wsConnected,
    refreshForecast,
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
