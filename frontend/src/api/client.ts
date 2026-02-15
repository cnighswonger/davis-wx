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
  return request<StationStatus>("/api/station/status");
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

export { ApiError };
