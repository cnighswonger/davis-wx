import { useState, useEffect, useCallback } from "react";
import { fetchConfig, updateConfig, fetchSerialPorts, reconnectStation, fetchWeatherLinkConfig, updateWeatherLinkConfig, clearRainDaily, clearRainYearly, forceArchive } from "../api/client.ts";
import type { ConfigItem, WeatherLinkConfig, WeatherLinkCalibration, AlertThreshold } from "../api/types.ts";
import { useTheme } from "../context/ThemeContext.tsx";
import { useWeatherBackground } from "../context/WeatherBackgroundContext.tsx";
import { themes } from "../themes/index.ts";
import { ALL_SCENES, SCENE_LABELS, SCENE_GRADIENTS } from "../components/WeatherBackground.tsx";
import { API_BASE } from "../utils/constants.ts";
import { getTimezone, setTimezone as storeTimezone, resolveTimezone, getTimezoneOptions } from "../utils/timezone.ts";
import { useIsMobile } from "../hooks/useIsMobile.ts";
import StepLocation from "../components/setup/StepLocation.tsx";

// --- Shared styles ---

const cardStyle: React.CSSProperties = {
  background: "var(--color-bg-card)",
  borderRadius: "var(--gauge-border-radius)",
  border: "1px solid var(--color-border)",
  padding: "20px",
  marginBottom: "16px",
};

const sectionTitle: React.CSSProperties = {
  margin: "0 0 16px 0",
  fontSize: "18px",
  fontFamily: "var(--font-heading)",
  color: "var(--color-text)",
};

const labelStyle: React.CSSProperties = {
  fontSize: "13px",
  fontFamily: "var(--font-body)",
  color: "var(--color-text-secondary)",
  marginBottom: "6px",
  display: "block",
};

const inputStyle: React.CSSProperties = {
  fontFamily: "var(--font-body)",
  fontSize: "14px",
  padding: "8px 12px",
  borderRadius: "6px",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-secondary)",
  color: "var(--color-text)",
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const readOnlyInput: React.CSSProperties = {
  ...inputStyle,
  opacity: 0.6,
  cursor: "not-allowed",
};

const selectStyle: React.CSSProperties = {
  fontFamily: "var(--font-body)",
  fontSize: "14px",
  padding: "8px 12px",
  borderRadius: "6px",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-secondary)",
  color: "var(--color-text)",
  outline: "none",
  cursor: "pointer",
  width: "100%",
  boxSizing: "border-box",
};

const fieldGroup: React.CSSProperties = {
  marginBottom: "16px",
};

const radioGroup: React.CSSProperties = {
  display: "flex",
  gap: "16px",
  flexWrap: "wrap",
};

const radioLabel: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "6px",
  fontSize: "14px",
  fontFamily: "var(--font-body)",
  color: "var(--color-text)",
  cursor: "pointer",
};

const checkboxLabel: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  fontSize: "14px",
  fontFamily: "var(--font-body)",
  color: "var(--color-text)",
  cursor: "pointer",
};

const btnPrimary: React.CSSProperties = {
  fontFamily: "var(--font-body)",
  fontSize: "14px",
  padding: "10px 24px",
  borderRadius: "6px",
  border: "none",
  background: "var(--color-accent)",
  color: "#fff",
  cursor: "pointer",
  fontWeight: 600,
  transition: "background 0.15s",
};

function gridTwoCol(mobile?: boolean): React.CSSProperties {
  return {
    display: "grid",
    gridTemplateColumns: mobile ? "1fr" : "repeat(auto-fit, minmax(240px, 1fr))",
    gap: mobile ? "12px" : "16px",
  };
}

// --- Config key helpers ---

function getConfigValue(
  items: ConfigItem[],
  key: string,
): string | number | boolean {
  const item = items.find((i) => i.key === key);
  return item?.value ?? "";
}

function setConfigValue(
  items: ConfigItem[],
  key: string,
  value: string | number | boolean,
  label?: string,
  description?: string,
): ConfigItem[] {
  const idx = items.findIndex((i) => i.key === key);
  if (idx >= 0) {
    const updated = [...items];
    updated[idx] = { ...updated[idx], value };
    return updated;
  }
  return [...items, { key, value, label, description }];
}

// --- Component ---

export default function Settings() {
  const isMobile = useIsMobile();
  const [configItems, setConfigItems] = useState<ConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [reconnectMsg, setReconnectMsg] = useState<string | null>(null);
  const [ports, setPorts] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<"station" | "display" | "services" | "alerts" | "nowcast">("station");

  const { themeName, setThemeName } = useTheme();
  const [timezone, setTimezoneState] = useState(getTimezone);
  const {
    enabled: bgEnabled,
    setEnabled: setBgEnabled,
    intensity: bgIntensity,
    setIntensity: setBgIntensity,
    transparency: bgTransparency,
    setTransparency: setBgTransparency,
    customImages: bgCustomImages,
    refreshCustomImages: refreshBgImages,
  } = useWeatherBackground();
  const [scenesExpanded, setScenesExpanded] = useState(false);

  // --- Alert thresholds ---
  const [alertThresholds, setAlertThresholds] = useState<AlertThreshold[]>([]);
  const [alertSaving, setAlertSaving] = useState(false);
  const [alertSuccess, setAlertSuccess] = useState(false);
  const [showAddAlert, setShowAddAlert] = useState(false);
  const [newAlert, setNewAlert] = useState<Partial<AlertThreshold>>({
    sensor: "outside_temp",
    operator: "<=",
    value: 32,
    label: "",
    cooldown_min: 15,
    enabled: true,
  });

  const handleBgUpload = useCallback(async (scene: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    try {
      const resp = await fetch(`${API_BASE}/api/backgrounds/${scene}`, {
        method: "POST",
        body: form,
      });
      if (resp.ok) {
        refreshBgImages();
      }
    } catch {
      /* ignore */
    }
  }, [refreshBgImages]);

  const handleBgDelete = useCallback(async (scene: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/backgrounds/${scene}`, {
        method: "DELETE",
      });
      if (resp.ok) {
        refreshBgImages();
      }
    } catch {
      /* ignore */
    }
  }, [refreshBgImages]);

  // WeatherLink hardware config state
  const [wlConfig, setWlConfig] = useState<WeatherLinkConfig | null>(null);
  const [wlArchivePeriod, setWlArchivePeriod] = useState<number>(30);
  const [wlSamplePeriod, setWlSamplePeriod] = useState<number>(60);
  const [wlCal, setWlCal] = useState<WeatherLinkCalibration>({
    inside_temp: 0, outside_temp: 0, barometer: 0, outside_humidity: 0, rain_cal: 100,
  });
  const [wlSaving, setWlSaving] = useState(false);
  const [wlMsg, setWlMsg] = useState<string | null>(null);
  const [wlError, setWlError] = useState<string | null>(null);

  // Load config + serial ports (fast), then weatherlink config (slow, non-blocking)
  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchConfig(),
      fetchSerialPorts().catch(() => ({ ports: [] })),
    ])
      .then(([items, portResult]) => {
        setConfigItems(items);
        setPorts(portResult.ports);
        setLoading(false);
        // Load alert thresholds from config
        const atItem = items.find((i: ConfigItem) => i.key === "alert_thresholds");
        if (atItem && typeof atItem.value === "string") {
          try { setAlertThresholds(JSON.parse(atItem.value)); } catch { /* ignore */ }
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });

    // Load WeatherLink hardware config in background (serial I/O is slow)
    fetchWeatherLinkConfig()
      .then((wl) => {
        if (wl && !("error" in wl)) {
          setWlConfig(wl);
          if (wl.archive_period != null) setWlArchivePeriod(wl.archive_period);
          if (wl.sample_period != null) setWlSamplePeriod(wl.sample_period);
          setWlCal(wl.calibration);
        }
      })
      .catch(() => {});
  }, []);

  const updateField = useCallback(
    (key: string, value: string | number | boolean) => {
      setConfigItems((prev) => setConfigValue(prev, key, value));
      setSaveSuccess(false);
    },
    [],
  );

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    try {
      // Ensure station_timezone is always populated for backend services.
      let items = configItems;
      const tzVal = getConfigValue(items, "station_timezone");
      if (!tzVal) {
        items = setConfigValue(items, "station_timezone", resolveTimezone());
      }
      const updated = await updateConfig(items);
      setConfigItems(updated);
      setSaveSuccess(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [configItems]);

  const handleSaveAndReconnect = useCallback(async () => {
    setSaving(true);
    setReconnecting(true);
    setError(null);
    setSaveSuccess(false);
    setReconnectMsg(null);
    try {
      let items = configItems;
      const tzVal = getConfigValue(items, "station_timezone");
      if (!tzVal) {
        items = setConfigValue(items, "station_timezone", resolveTimezone());
      }
      const updated = await updateConfig(items);
      setConfigItems(updated);
      const result = await reconnectStation();
      if (result.success) {
        setReconnectMsg(
          `Reconnected: ${result.station_type ?? "station"} detected`,
        );
      } else {
        setError(result.error ?? "Reconnect failed");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
      setReconnecting(false);
    }
  }, [configItems]);

  const refreshPorts = useCallback(() => {
    fetchSerialPorts()
      .then((result) => setPorts(result.ports))
      .catch(() => {});
  }, []);

  const handleWlSave = useCallback(async () => {
    setWlSaving(true);
    setWlMsg(null);
    setWlError(null);
    try {
      const update: Record<string, unknown> = {};
      if (wlConfig === null || wlArchivePeriod !== wlConfig.archive_period) {
        update.archive_period = wlArchivePeriod;
      }
      if (wlConfig === null || wlSamplePeriod !== wlConfig.sample_period) {
        update.sample_period = wlSamplePeriod;
      }
      const calChanged = wlConfig === null ||
        wlCal.inside_temp !== wlConfig.calibration.inside_temp ||
        wlCal.outside_temp !== wlConfig.calibration.outside_temp ||
        wlCal.barometer !== wlConfig.calibration.barometer ||
        wlCal.outside_humidity !== wlConfig.calibration.outside_humidity ||
        wlCal.rain_cal !== wlConfig.calibration.rain_cal;
      if (calChanged) {
        update.calibration = wlCal;
      }
      if (Object.keys(update).length === 0) {
        setWlMsg("No changes to save");
        setWlSaving(false);
        return;
      }
      const resp = await updateWeatherLinkConfig(update);
      if ("error" in resp) {
        setWlError(String((resp as Record<string, unknown>).error));
        return;
      }
      if (resp.config) {
        setWlConfig(resp.config);
        setWlCal(resp.config.calibration);
        if (resp.config.archive_period != null) setWlArchivePeriod(resp.config.archive_period);
        if (resp.config.sample_period != null) setWlSamplePeriod(resp.config.sample_period);
      }
      const failures = Object.entries(resp.results).filter(([, v]) => v !== "ok");
      if (failures.length > 0) {
        setWlError("Partial failure: " + failures.map(([k, v]) => `${k}: ${v}`).join(", "));
      } else {
        setWlMsg("Saved to WeatherLink");
      }
    } catch (err: unknown) {
      setWlError(err instanceof Error ? err.message : String(err));
    } finally {
      setWlSaving(false);
    }
  }, [wlConfig, wlArchivePeriod, wlSamplePeriod, wlCal]);

  const handleClearRainDaily = useCallback(async () => {
    if (!confirm("Clear the daily rain accumulator? This cannot be undone.")) return;
    setWlMsg(null);
    setWlError(null);
    try {
      const resp = await clearRainDaily();
      setWlMsg(resp.success ? "Daily rain cleared" : "Failed to clear daily rain");
    } catch (err: unknown) {
      setWlError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const handleClearRainYearly = useCallback(async () => {
    if (!confirm("Clear the yearly rain accumulator? This cannot be undone.")) return;
    setWlMsg(null);
    setWlError(null);
    try {
      const resp = await clearRainYearly();
      setWlMsg(resp.success ? "Yearly rain cleared" : "Failed to clear yearly rain");
    } catch (err: unknown) {
      setWlError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const handleForceArchive = useCallback(async () => {
    setWlMsg(null);
    setWlError(null);
    try {
      const resp = await forceArchive();
      setWlMsg(resp.success ? "Archive record written" : "Failed to write archive");
    } catch (err: unknown) {
      setWlError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  // Convenience getters
  const val = (key: string) => getConfigValue(configItems, key);

  if (loading) {
    return (
      <div>
        <h2
          style={{
            margin: "0 0 16px 0",
            fontSize: "24px",
            fontFamily: "var(--font-heading)",
            color: "var(--color-text)",
          }}
        >
          Settings
        </h2>
        <div
          style={{
            ...cardStyle,
            display: "flex",
            justifyContent: "center",
            padding: "48px",
          }}
        >
          <div
            style={{
              width: "36px",
              height: "36px",
              border: "3px solid var(--color-border)",
              borderTopColor: "var(--color-accent)",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
            }}
          />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h2
        style={{
          margin: "0 0 16px 0",
          fontSize: "24px",
          fontFamily: "var(--font-heading)",
          color: "var(--color-text)",
        }}
      >
        Settings
      </h2>

      {/* Tab bar */}
      <div style={{
        display: "flex",
        gap: "6px",
        marginBottom: "20px",
        flexWrap: "wrap",
      }}>
        {([
          ["station", "Station"],
          ["display", "Display"],
          ["services", "Services"],
          ["alerts", "Alerts"],
          ["nowcast", "Nowcast"],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              fontFamily: "var(--font-body)",
              fontSize: "14px",
              padding: isMobile ? "8px 14px" : "8px 20px",
              borderRadius: "6px",
              border: "1px solid var(--color-border)",
              background: activeTab === key ? "var(--color-accent)" : "var(--color-bg-secondary)",
              color: activeTab === key ? "#fff" : "var(--color-text-secondary)",
              cursor: "pointer",
              transition: "background 0.15s ease, color 0.15s ease",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "station" && (<>
      {/* Station section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Station</h3>
        <div style={gridTwoCol(isMobile)}>
          <div style={fieldGroup}>
            <label style={labelStyle}>
              Serial Port
              <button
                style={{
                  fontSize: "11px",
                  padding: "2px 8px",
                  marginLeft: "8px",
                  borderRadius: "4px",
                  border: "1px solid var(--color-border)",
                  background: "var(--color-bg-secondary)",
                  color: "var(--color-text)",
                  cursor: "pointer",
                  fontFamily: "var(--font-body)",
                }}
                onClick={refreshPorts}
              >
                Refresh
              </button>
            </label>
            <select
              style={selectStyle}
              value={String(val("serial_port"))}
              onChange={(e) => updateField("serial_port", e.target.value)}
            >
              {ports.length === 0 && (
                <option value="">No ports detected</option>
              )}
              {ports.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
              {/* Keep current value visible even if not in detected list */}
              {val("serial_port") &&
                !ports.includes(String(val("serial_port"))) && (
                  <option value={String(val("serial_port"))}>
                    {String(val("serial_port"))}
                  </option>
                )}
            </select>
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Baud Rate</label>
            <select
              style={selectStyle}
              value={String(val("baud_rate"))}
              onChange={(e) =>
                updateField("baud_rate", parseInt(e.target.value))
              }
            >
              <option value="2400">2400 (default)</option>
              <option value="1200">1200</option>
            </select>
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Poll Interval (seconds)</label>
            <input
              style={readOnlyInput}
              value={String(val("poll_interval"))}
              readOnly
              tabIndex={-1}
            />
          </div>
        </div>
      </div>

      {/* WeatherLink section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>WeatherLink</h3>

        {/* Timing row */}
        <div style={gridTwoCol(isMobile)}>
          <div style={fieldGroup}>
            <label style={labelStyle} title="How often the WeatherLink saves a summary record to its internal memory. Shorter intervals give finer history but fill the buffer faster.">
              Archive Period (minutes)
            </label>
            <select
              style={selectStyle}
              value={wlArchivePeriod}
              onChange={(e) => setWlArchivePeriod(parseInt(e.target.value))}
            >
              {[1, 5, 10, 15, 30, 60, 120].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle} title="How often the WeatherLink reads sensors. Lower values give fresher LOOP data but increase processing load.">
              Sample Period (seconds)
            </label>
            <input
              style={inputStyle}
              type="number"
              min={1}
              max={255}
              value={wlSamplePeriod}
              onChange={(e) => {
                const v = parseInt(e.target.value);
                if (!isNaN(v) && v >= 1 && v <= 255) setWlSamplePeriod(v);
              }}
            />
          </div>
        </div>

        {/* Calibration row */}
        <div style={gridTwoCol(isMobile)}>
          <div style={fieldGroup}>
            <label style={labelStyle} title="Added to raw inside temperature reading (tenths of °F). Use to correct a known sensor bias.">
              Inside Temp Offset (tenths °F)
            </label>
            <input
              style={inputStyle}
              type="number"
              value={wlCal.inside_temp}
              onChange={(e) => setWlCal({ ...wlCal, inside_temp: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle} title="Added to raw outside temperature reading (tenths of °F).">
              Outside Temp Offset (tenths °F)
            </label>
            <input
              style={inputStyle}
              type="number"
              value={wlCal.outside_temp}
              onChange={(e) => setWlCal({ ...wlCal, outside_temp: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle} title="Subtracted from raw barometer reading (thousandths inHg). Adjust to match a known reference.">
              Barometer Offset (thousandths inHg)
            </label>
            <input
              style={inputStyle}
              type="number"
              value={wlCal.barometer}
              onChange={(e) => setWlCal({ ...wlCal, barometer: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle} title="Added to raw outside humidity reading (%). Result is clamped to 1-100%.">
              Humidity Offset (%)
            </label>
            <input
              style={inputStyle}
              type="number"
              value={wlCal.outside_humidity}
              onChange={(e) => setWlCal({ ...wlCal, outside_humidity: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle} title="Rain collector clicks per inch. Standard: 100 (0.01&quot;/click). Metric: 127. Do not change unless you have a non-standard collector.">
              Rain Calibration (clicks/inch)
            </label>
            <input
              style={inputStyle}
              type="number"
              value={wlCal.rain_cal}
              onChange={(e) => setWlCal({ ...wlCal, rain_cal: parseInt(e.target.value) || 100 })}
            />
          </div>
        </div>

        {/* Actions row */}
        <div style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr 1fr" : "auto auto auto auto",
          gap: isMobile ? "8px" : "12px",
          marginTop: "8px",
          alignItems: "center",
        }}>
          <button
            style={{
              ...btnPrimary,
              opacity: wlSaving ? 0.6 : 1,
              cursor: wlSaving ? "wait" : "pointer",
              ...(isMobile ? { gridColumn: "1 / -1", fontSize: "13px", padding: "8px 12px" } : {}),
            }}
            onClick={handleWlSave}
            disabled={wlSaving}
            title="Write the above settings to the WeatherLink hardware"
          >
            {wlSaving ? "Saving..." : "Save to WeatherLink"}
          </button>

          <button
            style={{
              ...btnPrimary,
              background: "var(--color-bg-secondary)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              ...(isMobile ? { fontSize: "13px", padding: "8px 12px" } : {}),
            }}
            onClick={handleForceArchive}
            title="Immediately write current conditions to the archive buffer, regardless of the archive timer"
          >
            Force Archive
          </button>

          <button
            style={{
              ...btnPrimary,
              background: "var(--color-bg-secondary)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              ...(isMobile ? { fontSize: "13px", padding: "8px 12px" } : {}),
            }}
            onClick={handleClearRainDaily}
            title="Reset the daily rain accumulator to zero"
          >
            Clear Daily Rain
          </button>

          <button
            style={{
              ...btnPrimary,
              background: "var(--color-bg-secondary)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              ...(isMobile ? { fontSize: "13px", padding: "8px 12px" } : {}),
            }}
            onClick={handleClearRainYearly}
            title="Reset the yearly rain accumulator to zero"
          >
            Clear Yearly Rain
          </button>

          {wlMsg && (
            <span style={{ color: "var(--color-success)", fontSize: "14px", fontFamily: "var(--font-body)", gridColumn: "1 / -1" }}>
              {wlMsg}
            </span>
          )}
          {wlError && (
            <span style={{ color: "var(--color-danger)", fontSize: "14px", fontFamily: "var(--font-body)", gridColumn: "1 / -1" }}>
              Error: {wlError}
            </span>
          )}
        </div>
      </div>

      {/* Location section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Location</h3>
        <StepLocation
          latitude={Number(val("latitude")) || 0}
          longitude={Number(val("longitude")) || 0}
          elevation={Number(val("elevation")) || 0}
          onChange={(partial) => {
            if (partial.latitude !== undefined) updateField("latitude", partial.latitude);
            if (partial.longitude !== undefined) updateField("longitude", partial.longitude);
            if (partial.elevation !== undefined) updateField("elevation", partial.elevation);
          }}
        />
      </div>
      </>)}

      {activeTab === "display" && (<>
      {/* Units section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Units</h3>

        <div style={fieldGroup}>
          <label style={labelStyle}>Temperature</label>
          <div style={radioGroup}>
            {["F", "C"].map((u) => (
              <label key={u} style={radioLabel}>
                <input
                  type="radio"
                  name="temp_unit"
                  checked={val("temp_unit") === u}
                  onChange={() => updateField("temp_unit", u)}
                />
                {u === "F" ? "Fahrenheit (\u00B0F)" : "Celsius (\u00B0C)"}
              </label>
            ))}
          </div>
        </div>

        <div style={fieldGroup}>
          <label style={labelStyle}>Pressure</label>
          <div style={radioGroup}>
            {["inHg", "hPa"].map((u) => (
              <label key={u} style={radioLabel}>
                <input
                  type="radio"
                  name="pressure_unit"
                  checked={val("pressure_unit") === u}
                  onChange={() => updateField("pressure_unit", u)}
                />
                {u === "inHg" ? "Inches of Mercury (inHg)" : "Hectopascals (hPa)"}
              </label>
            ))}
          </div>
        </div>

        <div style={fieldGroup}>
          <label style={labelStyle}>Wind Speed</label>
          <div style={radioGroup}>
            {["mph", "kph", "knots"].map((u) => (
              <label key={u} style={radioLabel}>
                <input
                  type="radio"
                  name="wind_unit"
                  checked={val("wind_unit") === u}
                  onChange={() => updateField("wind_unit", u)}
                />
                {u === "mph" ? "Miles per hour" : u === "kph" ? "Kilometers per hour" : "Knots"}
              </label>
            ))}
          </div>
        </div>

        <div style={fieldGroup}>
          <label style={labelStyle}>Rain</label>
          <div style={radioGroup}>
            {["in", "mm"].map((u) => (
              <label key={u} style={radioLabel}>
                <input
                  type="radio"
                  name="rain_unit"
                  checked={val("rain_unit") === u}
                  onChange={() => updateField("rain_unit", u)}
                />
                {u === "in" ? "Inches" : "Millimeters"}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Display section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Display</h3>
        <div style={fieldGroup}>
          <label style={labelStyle}>Theme</label>
          <select
            style={selectStyle}
            value={themeName}
            onChange={(e) => setThemeName(e.target.value)}
          >
            {Object.entries(themes).map(([key, t]) => (
              <option key={key} value={key}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div style={fieldGroup}>
          <label style={labelStyle}>Timezone</label>
          <select
            style={selectStyle}
            value={timezone}
            onChange={(e) => {
              const tz = e.target.value;
              setTimezoneState(tz);
              storeTimezone(tz);
              // Also save resolved IANA name to backend for nowcast service
              const resolved = tz === "auto"
                ? Intl.DateTimeFormat().resolvedOptions().timeZone
                : tz;
              updateField("station_timezone", resolved);
            }}
          >
            <option value="auto">Auto ({resolveTimezone()})</option>
            {getTimezoneOptions().map((tz) => (
              <option key={tz} value={tz}>{tz.replace(/_/g, " ")}</option>
            ))}
          </select>
        </div>

        <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "16px", marginTop: "8px" }}>
          <div style={fieldGroup}>
            <label style={checkboxLabel}>
              <input
                type="checkbox"
                checked={bgEnabled}
                onChange={(e) => setBgEnabled(e.target.checked)}
              />
              Weather Background
            </label>
          </div>

          {bgEnabled && (
            <>
              <div style={fieldGroup}>
                <label style={labelStyle} title="How visible the weather background is. Higher values show more of the gradient/image.">
                  Intensity: {bgIntensity}%
                </label>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={bgIntensity}
                  onChange={(e) => setBgIntensity(parseInt(e.target.value))}
                  style={{ width: "100%", cursor: "pointer" }}
                />
              </div>

              <div style={fieldGroup}>
                <label style={labelStyle} title="How transparent tiles, cards, header, and sidebar are. Higher values let more of the background show through.">
                  Tile Transparency: {bgTransparency}%
                </label>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={bgTransparency}
                  onChange={(e) => setBgTransparency(parseInt(e.target.value))}
                  style={{ width: "100%", cursor: "pointer" }}
                />
              </div>

              <div style={fieldGroup}>
                <label
                  style={{ ...labelStyle, cursor: "pointer", userSelect: "none" }}
                  onClick={() => setScenesExpanded((v) => !v)}
                >
                  Custom Scene Images {scenesExpanded ? "\u25B2" : "\u25BC"}
                </label>

                {scenesExpanded && (
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(auto-fill, minmax(200px, 1fr))",
                    gap: isMobile ? "8px" : "12px",
                    marginTop: "8px",
                  }}>
                    {ALL_SCENES.map((scene) => {
                      const customUrl = bgCustomImages[scene];
                      return (
                        <div key={scene} style={{
                          border: "1px solid var(--color-border)",
                          borderRadius: "8px",
                          overflow: "hidden",
                          background: "var(--color-bg-secondary)",
                        }}>
                          {/* Preview swatch */}
                          <div style={{
                            height: "60px",
                            background: customUrl
                              ? `url(${customUrl}) center/cover`
                              : SCENE_GRADIENTS[scene],
                          }} />
                          <div style={{ padding: "8px" }}>
                            <div style={{
                              fontSize: "13px",
                              fontFamily: "var(--font-body)",
                              color: "var(--color-text)",
                              marginBottom: "6px",
                              fontWeight: 500,
                            }}>
                              {SCENE_LABELS[scene]}
                            </div>
                            <div style={{ display: "flex", gap: "6px" }}>
                              <label style={{
                                fontSize: "11px",
                                padding: "3px 8px",
                                borderRadius: "4px",
                                border: "1px solid var(--color-border)",
                                background: "var(--color-bg-card)",
                                color: "var(--color-text-secondary)",
                                cursor: "pointer",
                                fontFamily: "var(--font-body)",
                              }}>
                                Upload
                                <input
                                  type="file"
                                  accept="image/jpeg,image/png,image/webp"
                                  style={{ display: "none" }}
                                  onChange={(e) => {
                                    const file = e.target.files?.[0];
                                    if (file) handleBgUpload(scene, file);
                                    e.target.value = "";
                                  }}
                                />
                              </label>
                              {customUrl && (
                                <button
                                  style={{
                                    fontSize: "11px",
                                    padding: "3px 8px",
                                    borderRadius: "4px",
                                    border: "1px solid var(--color-border)",
                                    background: "var(--color-bg-card)",
                                    color: "var(--color-danger)",
                                    cursor: "pointer",
                                    fontFamily: "var(--font-body)",
                                  }}
                                  onClick={() => handleBgDelete(scene)}
                                >
                                  Remove
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
      </>)}

      {activeTab === "services" && (<>
      {/* Services section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Services</h3>
        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("metar_enabled") === true}
              onChange={(e) => updateField("metar_enabled", e.target.checked)}
            />
            Enable METAR data
          </label>
        </div>
        <div style={fieldGroup}>
          <label style={labelStyle}>METAR Station ID</label>
          <input
            style={inputStyle}
            type="text"
            placeholder="e.g. KJFK"
            value={String(val("metar_station") || "")}
            onChange={(e) => updateField("metar_station", e.target.value)}
          />
        </div>
        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("nws_enabled") === true}
              onChange={(e) => updateField("nws_enabled", e.target.checked)}
            />
            Enable NWS forecast data
          </label>
        </div>
      </div>

      {/* Weather Underground section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Weather Underground</h3>
        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("wu_enabled") === true}
              onChange={(e) => updateField("wu_enabled", e.target.checked)}
            />
            Enable Weather Underground uploads
          </label>
        </div>
        <div style={gridTwoCol(isMobile)}>
          <div style={fieldGroup}>
            <label style={labelStyle}>Station ID</label>
            <input
              style={inputStyle}
              type="text"
              placeholder="e.g. KNCDUNN12"
              value={String(val("wu_station_id") || "")}
              onChange={(e) => updateField("wu_station_id", e.target.value)}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Station Key</label>
            <input
              style={inputStyle}
              type="password"
              placeholder="Your WU station key"
              value={String(val("wu_station_key") || "")}
              onChange={(e) => updateField("wu_station_key", e.target.value)}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Upload Interval</label>
            <select
              style={selectStyle}
              value={String(val("wu_upload_interval") || "60")}
              onChange={(e) => updateField("wu_upload_interval", parseInt(e.target.value))}
            >
              <option value="10">10 seconds</option>
              <option value="15">15 seconds</option>
              <option value="30">30 seconds</option>
              <option value="60">60 seconds</option>
              <option value="120">2 minutes</option>
              <option value="300">5 minutes</option>
            </select>
          </div>
        </div>
      </div>

      {/* CWOP / APRS section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>CWOP / APRS</h3>
        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("cwop_enabled") === true}
              onChange={(e) => updateField("cwop_enabled", e.target.checked)}
            />
            Enable CWOP uploads
          </label>
        </div>
        <div style={gridTwoCol(isMobile)}>
          <div style={fieldGroup}>
            <label style={labelStyle}>Callsign</label>
            <input
              style={inputStyle}
              type="text"
              placeholder="e.g. CW1234 or N0CALL"
              value={String(val("cwop_callsign") || "")}
              onChange={(e) => updateField("cwop_callsign", e.target.value)}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Passcode</label>
            <input
              style={inputStyle}
              type="text"
              placeholder="-1 for CWOP, computed for HAM"
              value={String(val("cwop_passcode") ?? "-1")}
              onChange={(e) => updateField("cwop_passcode", e.target.value)}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Upload Interval</label>
            <select
              style={selectStyle}
              value={String(val("cwop_upload_interval") || "300")}
              onChange={(e) => updateField("cwop_upload_interval", parseInt(e.target.value))}
            >
              <option value="300">5 minutes</option>
              <option value="600">10 minutes</option>
              <option value="900">15 minutes</option>
            </select>
          </div>
        </div>
      </div>
      </>)}

      {activeTab === "alerts" && (<>
      {/* ==================== Alerts ==================== */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>Alerts</h3>

        {alertThresholds.length > 0 && (
          <div style={{ marginBottom: "12px" }}>
            {alertThresholds.map((t, idx) => (
              <div
                key={t.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: isMobile ? "8px" : "12px",
                  padding: "8px 0",
                  borderBottom: idx < alertThresholds.length - 1 ? "1px solid var(--color-border)" : "none",
                  flexWrap: isMobile ? "wrap" : "nowrap",
                }}
              >
                <input
                  type="checkbox"
                  checked={t.enabled}
                  onChange={() => {
                    const updated = [...alertThresholds];
                    updated[idx] = { ...t, enabled: !t.enabled };
                    setAlertThresholds(updated);
                    setAlertSuccess(false);
                  }}
                />
                <span style={{ flex: 1, minWidth: 0, fontSize: isMobile ? "13px" : "14px", fontFamily: "var(--font-body)", color: t.enabled ? "var(--color-text)" : "var(--color-text-muted)" }}>
                  <strong>{t.label}</strong> — {t.sensor} {t.operator} {t.value}
                </span>
                <span style={{ fontSize: "12px", color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                  {t.cooldown_min}m cooldown
                </span>
                <button
                  onClick={() => {
                    setAlertThresholds(alertThresholds.filter((_, i) => i !== idx));
                    setAlertSuccess(false);
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--color-danger)",
                    cursor: "pointer",
                    fontSize: "16px",
                    padding: "4px 8px",
                    flexShrink: 0,
                  }}
                  title="Delete"
                >
                  &#x2715;
                </button>
              </div>
            ))}
          </div>
        )}

        {alertThresholds.length === 0 && !showAddAlert && (
          <p style={{ fontSize: "14px", color: "var(--color-text-muted)", marginBottom: "12px", fontFamily: "var(--font-body)" }}>
            No alerts configured. Add one to get notified when conditions exceed a threshold.
          </p>
        )}

        {showAddAlert && (
          <div style={{ ...cardStyle, background: "var(--color-bg-secondary)", marginBottom: "12px", padding: isMobile ? "12px" : "20px" }}>
            <div style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr 1fr" : "180px 160px 70px 90px 80px",
              gap: isMobile ? "10px" : "12px",
              alignItems: "end",
            }}>
              <div style={isMobile ? { gridColumn: "1 / -1" } : undefined}>
                <label style={labelStyle}>Label</label>
                <input
                  style={inputStyle}
                  placeholder="e.g. Freeze Warning"
                  value={newAlert.label ?? ""}
                  onChange={(e) => setNewAlert({ ...newAlert, label: e.target.value })}
                />
              </div>
              <div style={isMobile ? { gridColumn: "1 / -1" } : undefined}>
                <label style={labelStyle}>Sensor</label>
                <select
                  style={selectStyle}
                  value={newAlert.sensor ?? "outside_temp"}
                  onChange={(e) => setNewAlert({ ...newAlert, sensor: e.target.value })}
                >
                  <option value="outside_temp">Outside Temp</option>
                  <option value="inside_temp">Inside Temp</option>
                  <option value="wind_speed">Wind Speed</option>
                  <option value="barometer">Barometer</option>
                  <option value="outside_humidity">Humidity</option>
                  <option value="rain_rate">Rain Rate</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Condition</label>
                <select
                  style={selectStyle}
                  value={newAlert.operator ?? "<="}
                  onChange={(e) => setNewAlert({ ...newAlert, operator: e.target.value as AlertThreshold["operator"] })}
                >
                  <option value=">=">&#8805;</option>
                  <option value="<=">&#8804;</option>
                  <option value=">">&gt;</option>
                  <option value="<">&lt;</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Value</label>
                <input
                  type="number"
                  style={inputStyle}
                  value={newAlert.value ?? 0}
                  onChange={(e) => setNewAlert({ ...newAlert, value: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div style={isMobile ? { gridColumn: "1 / -1" } : undefined}>
                <label style={labelStyle}>Cooldown (min)</label>
                <input
                  type="number"
                  style={inputStyle}
                  value={newAlert.cooldown_min ?? 15}
                  onChange={(e) => setNewAlert({ ...newAlert, cooldown_min: parseInt(e.target.value) || 15 })}
                />
              </div>
            </div>

            <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
              <button
                style={btnPrimary}
                onClick={() => {
                  if (!newAlert.label?.trim()) return;
                  const id = `alert-${Date.now()}`;
                  setAlertThresholds([...alertThresholds, {
                    id,
                    sensor: newAlert.sensor ?? "outside_temp",
                    operator: (newAlert.operator ?? "<=") as AlertThreshold["operator"],
                    value: newAlert.value ?? 0,
                    label: newAlert.label?.trim() ?? "",
                    enabled: true,
                    cooldown_min: newAlert.cooldown_min ?? 15,
                  }]);
                  setShowAddAlert(false);
                  setNewAlert({ sensor: "outside_temp", operator: "<=", value: 32, label: "", cooldown_min: 15, enabled: true });
                  setAlertSuccess(false);
                }}
              >
                Add
              </button>
              <button
                style={{ ...btnPrimary, background: "var(--color-bg-secondary)", color: "var(--color-text)", border: "1px solid var(--color-border)" }}
                onClick={() => setShowAddAlert(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          {!showAddAlert && (
            <button style={btnPrimary} onClick={() => setShowAddAlert(true)}>
              Add Alert
            </button>
          )}
          <button
            style={{
              ...btnPrimary,
              opacity: alertSaving ? 0.6 : 1,
            }}
            onClick={async () => {
              setAlertSaving(true);
              setAlertSuccess(false);
              try {
                await updateConfig([{ key: "alert_thresholds", value: JSON.stringify(alertThresholds) }]);
                setAlertSuccess(true);
              } catch {
                setError("Failed to save alerts");
              } finally {
                setAlertSaving(false);
              }
            }}
            disabled={alertSaving}
          >
            {alertSaving ? "Saving..." : "Save Alerts"}
          </button>

          {alertSuccess && (
            <span style={{ color: "var(--color-success)", fontSize: "14px", fontFamily: "var(--font-body)" }}>
              Alerts saved.
            </span>
          )}
        </div>
      </div>
      </>)}

      {activeTab === "nowcast" && (<>
      {/* AI Nowcast section */}
      <div style={{ ...cardStyle, padding: isMobile ? "12px" : "20px" }}>
        <h3 style={sectionTitle}>AI Nowcast</h3>

        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("nowcast_enabled") === true}
              onChange={(e) => updateField("nowcast_enabled", e.target.checked)}
            />
            Enable AI Nowcast
          </label>
        </div>

        <div style={fieldGroup}>
          <label style={checkboxLabel}>
            <input
              type="checkbox"
              checked={val("nowcast_radar_enabled") !== false}
              onChange={(e) => updateField("nowcast_radar_enabled", e.target.checked)}
            />
            Include NEXRAD radar imagery
            <span style={{ fontSize: "11px", color: "var(--color-text-muted)", display: "block", marginTop: "2px", marginLeft: "24px" }}>
              Sends radar image to Claude for precipitation analysis (~250 extra tokens/call)
            </span>
          </label>
        </div>

        {/* API Key — full width */}
        <div style={fieldGroup}>
          <label style={labelStyle}>
            Anthropic API Key
            <span style={{ fontSize: "11px", color: "var(--color-text-muted)", display: "block", marginTop: "2px" }}>
              Or set ANTHROPIC_API_KEY environment variable
            </span>
          </label>
          <input
            style={{ ...inputStyle, maxWidth: "480px" }}
            type="password"
            placeholder="sk-ant-..."
            value={String(val("nowcast_api_key") || "")}
            onChange={(e) => updateField("nowcast_api_key", e.target.value)}
          />
        </div>

        <div style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
          gap: isMobile ? "12px" : "16px",
        }}>
          <div style={fieldGroup}>
            <label style={labelStyle}>Model</label>
            <select
              style={selectStyle}
              value={String(val("nowcast_model") || "claude-haiku-4-5-20251001")}
              onChange={(e) => updateField("nowcast_model", e.target.value)}
            >
              <option value="claude-haiku-4-5-20251001">Haiku 4.5 (fastest, lowest cost)</option>
              <option value="claude-sonnet-4-5-20250929">Sonnet 4.5 (better reasoning)</option>
            </select>
          </div>

          <div style={fieldGroup}>
            <label style={labelStyle}>Update Interval</label>
            <select
              style={selectStyle}
              value={String(val("nowcast_interval") || "900")}
              onChange={(e) => updateField("nowcast_interval", parseInt(e.target.value))}
            >
              <option value="300">5 minutes</option>
              <option value="600">10 minutes</option>
              <option value="900">15 minutes</option>
              <option value="1800">30 minutes</option>
              <option value="3600">1 hour</option>
            </select>
          </div>

          <div style={fieldGroup}>
            <label style={labelStyle}>Forecast Horizon</label>
            <select
              style={selectStyle}
              value={String(val("nowcast_horizon") || "2")}
              onChange={(e) => updateField("nowcast_horizon", parseInt(e.target.value))}
            >
              <option value="2">2 hours</option>
              <option value="4">4 hours</option>
              <option value="6">6 hours</option>
              <option value="8">8 hours</option>
              <option value="12">12 hours</option>
            </select>
          </div>

          <div style={fieldGroup}>
            <label style={labelStyle}>Nearby Station Radius (miles)</label>
            <input
              style={inputStyle}
              type="number"
              min="5"
              max="100"
              step="5"
              value={String(val("nowcast_radius") || "25")}
              onChange={(e) => updateField("nowcast_radius", parseInt(e.target.value) || 25)}
            />
          </div>

          <div style={fieldGroup}>
            <label style={labelStyle}>
              Knowledge Auto-Accept (hours)
              <span style={{ fontSize: "11px", color: "var(--color-text-muted)", display: "block", marginTop: "2px" }}>
                0 = manual approval only
              </span>
            </label>
            <input
              style={inputStyle}
              type="number"
              min="0"
              max="720"
              step="1"
              value={val("nowcast_knowledge_auto_accept_hours") !== "" ? String(val("nowcast_knowledge_auto_accept_hours")) : "48"}
              onChange={(e) => updateField("nowcast_knowledge_auto_accept_hours", parseInt(e.target.value) || 0)}
            />
          </div>
        </div>
      </div>
      </>)}

      {/* Save buttons and status */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: isMobile ? "8px" : "12px",
        flexWrap: "wrap",
        ...(isMobile ? { flexDirection: "column", alignItems: "stretch" } : {}),
      }}>
        <button
          style={{
            ...btnPrimary,
            opacity: saving ? 0.6 : 1,
            cursor: saving ? "wait" : "pointer",
            ...(isMobile ? { fontSize: "13px", padding: "10px 16px" } : {}),
          }}
          onClick={handleSave}
          disabled={saving || reconnecting}
        >
          {saving && !reconnecting ? "Saving..." : "Save Settings"}
        </button>

        <button
          style={{
            ...btnPrimary,
            background: "var(--color-bg-secondary)",
            color: "var(--color-text)",
            border: "1px solid var(--color-border)",
            opacity: reconnecting ? 0.6 : 1,
            cursor: reconnecting ? "wait" : "pointer",
            ...(isMobile ? { fontSize: "13px", padding: "10px 16px" } : {}),
          }}
          onClick={handleSaveAndReconnect}
          disabled={saving || reconnecting}
        >
          {reconnecting ? "Reconnecting..." : "Save & Reconnect"}
        </button>

        {saveSuccess && (
          <span
            style={{
              color: "var(--color-success)",
              fontSize: "14px",
              fontFamily: "var(--font-body)",
            }}
          >
            Settings saved successfully.
          </span>
        )}

        {reconnectMsg && (
          <span
            style={{
              color: "var(--color-success)",
              fontSize: "14px",
              fontFamily: "var(--font-body)",
            }}
          >
            {reconnectMsg}
          </span>
        )}

        {error && (
          <span
            style={{
              color: "var(--color-danger)",
              fontSize: "14px",
              fontFamily: "var(--font-body)",
            }}
          >
            Error: {error}
          </span>
        )}
      </div>
    </div>
  );
}
