// ============================================================
// TypeScript interfaces matching the Davis Weather Station
// backend Pydantic models.
// ============================================================

// --- Primitives ---

export interface ValueWithUnit {
  value: number;
  unit: string;
}

// --- Current Conditions ---

export interface TemperatureData {
  inside: ValueWithUnit | null;
  outside: ValueWithUnit | null;
}

export interface HumidityData {
  inside: ValueWithUnit | null;
  outside: ValueWithUnit | null;
}

export interface WindData {
  speed: ValueWithUnit | null;
  direction: ValueWithUnit | null;
  cardinal: string | null;
  gust: ValueWithUnit | null;
}

export interface BarometerData {
  value: number | null;
  unit: string;
  trend: string | null;
  trend_rate: number | null;
}

export interface RainData {
  daily: ValueWithUnit | null;
  yearly: ValueWithUnit | null;
  rate: ValueWithUnit | null;
}

export interface DerivedData {
  heat_index: ValueWithUnit | null;
  dew_point: ValueWithUnit | null;
  wind_chill: ValueWithUnit | null;
  feels_like: ValueWithUnit | null;
  theta_e: ValueWithUnit | null;
}

export interface DailyExtremes {
  outside_temp_hi: ValueWithUnit | null;
  outside_temp_lo: ValueWithUnit | null;
  inside_temp_hi: ValueWithUnit | null;
  inside_temp_lo: ValueWithUnit | null;
  wind_speed_hi: ValueWithUnit | null;
  barometer_hi: ValueWithUnit | null;
  barometer_lo: ValueWithUnit | null;
  humidity_hi: ValueWithUnit | null;
  humidity_lo: ValueWithUnit | null;
  rain_rate_hi: ValueWithUnit | null;
}

export interface CurrentConditions {
  timestamp: string;
  station_type: string;
  temperature: TemperatureData;
  humidity: HumidityData;
  wind: WindData;
  barometer: BarometerData;
  rain: RainData;
  derived: DerivedData;
  solar_radiation: ValueWithUnit | null;
  uv_index: ValueWithUnit | null;
  daily_extremes: DailyExtremes | null;
}

// --- Forecast ---

export interface LocalForecast {
  source: "zambretti";
  text: string;
  confidence: number;
  trend: string | null;
  updated: string;
}

export interface NWSPeriod {
  name: string;
  temperature: number;
  wind: string;
  precipitation_pct: number;
  text: string;
  icon_url: string | null;
  short_forecast: string | null;
  is_daytime: boolean | null;
}

export interface NWSForecast {
  source: "nws";
  periods: NWSPeriod[];
  updated: string;
}

export interface ForecastResponse {
  local: LocalForecast | null;
  nws: NWSForecast | null;
}

// --- Astronomy ---

export interface TwilightTimes {
  dawn: string;
  dusk: string;
}

export interface SunData {
  sunrise: string;
  sunset: string;
  solar_noon: string;
  day_length: string;
  day_change: string;
  civil_twilight: TwilightTimes;
  nautical_twilight: TwilightTimes;
  astronomical_twilight: TwilightTimes;
}

export interface MoonData {
  phase: string;
  illumination: number;
  next_full: string;
  next_new: string;
}

export interface AstronomyResponse {
  sun: SunData;
  moon: MoonData;
}

// --- Station Status ---

export interface StationStatus {
  type_code: number;
  type_name: string;
  connected: boolean;
  link_revision: string;
  poll_interval: number;
  last_poll: string | null;
  archive_records: number;
  uptime_seconds: number;
  crc_errors: number;
  timeouts: number;
  station_time: string | null;
}

// --- Configuration ---

export interface ConfigItem {
  key: string;
  value: string | number | boolean;
  label?: string;
  description?: string;
}

// --- History ---

export interface HistoryPoint {
  timestamp: string;
  value: number;
}

export interface HistoryResponse {
  sensor: string;
  start: string;
  end: string;
  resolution: string;
  points: HistoryPoint[];
}

// --- Alerts ---

export interface AlertThreshold {
  id: string;
  sensor: string;
  operator: ">=" | "<=" | ">" | "<";
  value: number;
  label: string;
  enabled: boolean;
  cooldown_min: number;
}

export interface AlertEvent {
  id: string;
  label: string;
  sensor: string;
  value: number;
  threshold: number;
  operator: string;
}

// --- WebSocket Messages ---

export interface WSSensorUpdate {
  type: "sensor_update";
  data: CurrentConditions;
}

export interface WSForecastUpdate {
  type: "forecast_update";
  data: ForecastResponse;
}

export interface WSAlertTriggered {
  type: "alert_triggered";
  data: AlertEvent;
}

export interface WSAlertCleared {
  type: "alert_cleared";
  data: { id: string; label: string };
}

export interface WSConnectionStatus {
  type: "connection_status";
  connected: boolean;
}

export type WSMessage = WSSensorUpdate | WSForecastUpdate | WSConnectionStatus | WSAlertTriggered | WSAlertCleared;

// --- Setup Wizard ---

export interface SetupStatus {
  setup_complete: boolean;
}

export interface SerialPortList {
  ports: string[];
}

export interface ProbeResult {
  success: boolean;
  station_type: string | null;
  station_code: number | null;
  error: string | null;
}

export interface AutoDetectResult {
  found: boolean;
  port: string | null;
  baud_rate: number | null;
  station_type: string | null;
  station_code: number | null;
  attempts: Array<{ port: string; baud: number; error?: string }>;
}

export interface SetupConfig {
  serial_port: string;
  baud_rate: number;
  latitude: number;
  longitude: number;
  elevation: number;
  temp_unit: string;
  pressure_unit: string;
  wind_unit: string;
  rain_unit: string;
  metar_enabled: boolean;
  metar_station: string;
  nws_enabled: boolean;
}

export interface ReconnectResult {
  success: boolean;
  station_type?: string;
  error?: string;
}

// --- WeatherLink Hardware Config ---

export interface WeatherLinkCalibration {
  inside_temp: number;
  outside_temp: number;
  barometer: number;
  outside_humidity: number;
  rain_cal: number;
}

export interface WeatherLinkConfig {
  archive_period: number | null;
  sample_period: number | null;
  calibration: WeatherLinkCalibration;
}

export interface WeatherLinkConfigUpdate {
  archive_period?: number;
  sample_period?: number;
  calibration?: WeatherLinkCalibration;
}
