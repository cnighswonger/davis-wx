// ============================================================
// HTTP API client for the Davis Weather Station backend.
// Pure fetch-based -- no external dependencies.
// ============================================================

import type { ConfigItem } from "./types.ts";
import type {
  CurrentConditions,
  HistoryResponse,
  ForecastResponse,
  AstronomyResponse,
  StationStatus,
} from "./types.ts";
import { API_BASE } from "../utils/constants.ts";

// --- Helpers ---

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, init);

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(
      response.status,
      `API ${response.status}: ${body || response.statusText}`,
    );
  }

  return (await response.json()) as T;
}

// --- Public API functions ---

export function fetchCurrentConditions(): Promise<CurrentConditions> {
  return request<CurrentConditions>("/api/current");
}

export function fetchHistory(
  sensor: string,
  start: string,
  end: string,
  resolution: string = "5m",
): Promise<HistoryResponse> {
  const params = new URLSearchParams({ sensor, start, end, resolution });
  return request<HistoryResponse>(`/api/history?${params.toString()}`);
}

export function fetchForecast(): Promise<ForecastResponse> {
  return request<ForecastResponse>("/api/forecast");
}

export function fetchAstronomy(): Promise<AstronomyResponse> {
  return request<AstronomyResponse>("/api/astronomy");
}

export function fetchStationStatus(): Promise<StationStatus> {
  return request<StationStatus>("/api/station");
}

export function fetchConfig(): Promise<ConfigItem[]> {
  return request<ConfigItem[]>("/api/config");
}

export function updateConfig(items: ConfigItem[]): Promise<ConfigItem[]> {
  return request<ConfigItem[]>("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
}

export function syncStationTime(): Promise<{ status: string; synced_to?: string; message?: string }> {
  return request("/api/station/sync-time", { method: "POST" });
}

// --- Setup ---

import type {
  SetupStatus,
  SerialPortList,
  ProbeResult,
  AutoDetectResult,
  SetupConfig,
  ReconnectResult,
} from "./types.ts";

export function fetchSetupStatus(): Promise<SetupStatus> {
  return request<SetupStatus>("/api/setup/status");
}

export function fetchSerialPorts(): Promise<SerialPortList> {
  return request<SerialPortList>("/api/setup/serial-ports");
}

export function probeSerialPort(
  port: string,
  baudRate: number,
): Promise<ProbeResult> {
  return request<ProbeResult>("/api/setup/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ port, baud_rate: baudRate }),
  });
}

export function autoDetectStation(): Promise<AutoDetectResult> {
  return request<AutoDetectResult>("/api/setup/auto-detect", {
    method: "POST",
  });
}

export function completeSetup(
  config: SetupConfig,
): Promise<{ status: string; reconnect: ReconnectResult }> {
  return request("/api/setup/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export function reconnectStation(): Promise<ReconnectResult> {
  return request<ReconnectResult>("/api/setup/reconnect", {
    method: "POST",
  });
}

// --- WeatherLink Hardware Config ---

import type {
  WeatherLinkConfig,
  WeatherLinkConfigUpdate,
} from "./types.ts";

export function fetchWeatherLinkConfig(): Promise<WeatherLinkConfig> {
  return request<WeatherLinkConfig>("/api/weatherlink/config");
}

export function updateWeatherLinkConfig(
  config: WeatherLinkConfigUpdate,
): Promise<{ results: Record<string, string>; config: WeatherLinkConfig }> {
  return request("/api/weatherlink/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export function clearRainDaily(): Promise<{ success: boolean }> {
  return request("/api/weatherlink/clear-rain-daily", { method: "POST" });
}

export function clearRainYearly(): Promise<{ success: boolean }> {
  return request("/api/weatherlink/clear-rain-yearly", { method: "POST" });
}

export function forceArchive(): Promise<{ success: boolean }> {
  return request("/api/weatherlink/force-archive", { method: "POST" });
}

// --- Nowcast ---

import type { NowcastData, NowcastKnowledgeEntry } from "./types.ts";

export function fetchNowcast(): Promise<NowcastData | null> {
  return request<NowcastData | null>("/api/nowcast");
}

export function fetchNowcastHistory(
  limit: number = 20,
): Promise<NowcastData[]> {
  return request<NowcastData[]>(`/api/nowcast/history?limit=${limit}`);
}

export function fetchNowcastKnowledge(
  status?: string,
): Promise<NowcastKnowledgeEntry[]> {
  const params = status ? `?status=${status}` : "";
  return request<NowcastKnowledgeEntry[]>(`/api/nowcast/knowledge${params}`);
}

export function updateNowcastKnowledge(
  id: number,
  status: "accepted" | "rejected",
): Promise<NowcastKnowledgeEntry> {
  return request<NowcastKnowledgeEntry>(`/api/nowcast/knowledge/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function generateNowcast(): Promise<NowcastData> {
  return request<NowcastData>("/api/nowcast/generate", { method: "POST" });
}

export { ApiError };
