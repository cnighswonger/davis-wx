import { useState, useEffect, useCallback } from "react";
import { fetchConfig, updateConfig } from "../api/client.ts";
import type { ConfigItem } from "../api/types.ts";
import { useTheme } from "../context/ThemeContext.tsx";
import { themes } from "../themes/index.ts";

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

const gridTwoCol: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "16px",
};

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
  const [configItems, setConfigItems] = useState<ConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const { themeName, setThemeName } = useTheme();

  // Load config
  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchConfig()
      .then((items) => {
        setConfigItems(items);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
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
      const updated = await updateConfig(configItems);
      setConfigItems(updated);
      setSaveSuccess(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [configItems]);

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

      {/* Station section (read-only) */}
      <div style={cardStyle}>
        <h3 style={sectionTitle}>Station</h3>
        <div style={gridTwoCol}>
          <div style={fieldGroup}>
            <label style={labelStyle}>Serial Port</label>
            <input
              style={readOnlyInput}
              value={String(val("serial_port"))}
              readOnly
              tabIndex={-1}
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Baud Rate</label>
            <input
              style={readOnlyInput}
              value={String(val("baud_rate"))}
              readOnly
              tabIndex={-1}
            />
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

      {/* Location section */}
      <div style={cardStyle}>
        <h3 style={sectionTitle}>Location</h3>
        <div style={gridTwoCol}>
          <div style={fieldGroup}>
            <label style={labelStyle}>Latitude</label>
            <input
              style={inputStyle}
              type="number"
              step="0.0001"
              value={String(val("latitude"))}
              onChange={(e) =>
                updateField("latitude", parseFloat(e.target.value) || 0)
              }
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Longitude</label>
            <input
              style={inputStyle}
              type="number"
              step="0.0001"
              value={String(val("longitude"))}
              onChange={(e) =>
                updateField("longitude", parseFloat(e.target.value) || 0)
              }
            />
          </div>
          <div style={fieldGroup}>
            <label style={labelStyle}>Elevation (ft)</label>
            <input
              style={inputStyle}
              type="number"
              step="1"
              value={String(val("elevation"))}
              onChange={(e) =>
                updateField("elevation", parseFloat(e.target.value) || 0)
              }
            />
          </div>
        </div>
      </div>

      {/* Units section */}
      <div style={cardStyle}>
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
      <div style={cardStyle}>
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
      </div>

      {/* Services section */}
      <div style={cardStyle}>
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

      {/* Save button and status */}
      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        <button
          style={{
            ...btnPrimary,
            opacity: saving ? 0.6 : 1,
            cursor: saving ? "wait" : "pointer",
          }}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save Settings"}
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
