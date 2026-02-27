import { useState, useEffect } from "react";
import { useIsMobile } from "../hooks/useIsMobile.ts";
import { fetchStationStatus } from "../api/client.ts";
import type { StationStatus } from "../api/types.ts";

// --- Shared styles ---

const cardStyle: React.CSSProperties = {
  background: "var(--color-bg-card)",
  borderRadius: "var(--gauge-border-radius)",
  border: "1px solid var(--color-border)",
  padding: "20px",
  marginBottom: "16px",
};

const sectionTitle: React.CSSProperties = {
  margin: "0 0 12px 0",
  fontSize: "18px",
  fontFamily: "var(--font-heading)",
  color: "var(--color-text)",
};

const bodyText: React.CSSProperties = {
  color: "var(--color-text-secondary)",
  fontSize: "14px",
  fontFamily: "var(--font-body)",
  lineHeight: "1.6",
  margin: 0,
};

const labelStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "12px",
  fontFamily: "var(--font-body)",
  textTransform: "uppercase",
  letterSpacing: "0.5px",
  marginBottom: "2px",
};

const valueStyle: React.CSSProperties = {
  color: "var(--color-text)",
  fontSize: "14px",
  fontFamily: "var(--font-body)",
  fontWeight: 500,
};

// --- Helpers ---

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginBottom: "10px" }}>
      <div style={labelStyle}>{label}</div>
      <div style={valueStyle}>{value}</div>
    </div>
  );
}

// --- Buy me a Coffee ---

const BMAC_URL = "https://buymeacoffee.com/placeholder";

function SupportCard({ isMobile }: { isMobile: boolean }) {
  return (
    <div
      style={{
        ...cardStyle,
        padding: isMobile ? "16px" : "24px",
        textAlign: "center",
        background: "var(--color-bg-card)",
        border: "2px solid var(--color-accent-muted)",
      }}
    >
      <div style={{ fontSize: "28px", marginBottom: "8px" }}>{'\u2615'}</div>
      <h3
        style={{
          ...sectionTitle,
          fontSize: "16px",
          marginBottom: "8px",
        }}
      >
        Support This Project
      </h3>
      <p
        style={{
          ...bodyText,
          fontSize: "13px",
          color: "var(--color-text-muted)",
          marginBottom: "16px",
          maxWidth: "380px",
          marginLeft: "auto",
          marginRight: "auto",
        }}
      >
        This is a hobby project built for the weather station community. If you
        find it useful, consider buying me a coffee.
      </p>
      <a
        href={BMAC_URL}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: "inline-block",
          padding: "10px 24px",
          borderRadius: "8px",
          background: "var(--color-accent)",
          color: "#fff",
          fontFamily: "var(--font-body)",
          fontSize: "14px",
          fontWeight: 600,
          textDecoration: "none",
          transition: "opacity 0.15s ease",
        }}
      >
        Buy me a Coffee
      </a>
    </div>
  );
}

// --- Main ---

export default function About() {
  const isMobile = useIsMobile();
  const [station, setStation] = useState<StationStatus | null>(null);

  useEffect(() => {
    fetchStationStatus()
      .then(setStation)
      .catch(() => {});
  }, []);

  const pad = isMobile ? "12px" : "20px";

  return (
    <div style={{ maxWidth: "720px", margin: "0 auto", padding: pad }}>
      {/* Header */}
      <h2
        style={{
          fontFamily: "var(--font-heading)",
          fontSize: isMobile ? "22px" : "26px",
          color: "var(--color-text)",
          margin: "0 0 4px 0",
        }}
      >
        Davis Weather Station
      </h2>
      <p
        style={{
          ...bodyText,
          fontSize: "13px",
          color: "var(--color-text-muted)",
          marginBottom: "20px",
        }}
      >
        Web Dashboard & Logger
      </p>

      {/* Description */}
      <div style={{ ...cardStyle, padding: isMobile ? "14px" : "20px" }}>
        <p style={bodyText}>
          A self-hosted web dashboard and data logger for Davis weather
          stations (Vantage Pro 2, Weather Monitor II, and compatible models).
          Features real-time monitoring, historical charting, NWS forecasts,
          AI-powered nowcasting, and spray application advisory.
        </p>
      </div>

      {/* Station Info */}
      {station && (
        <div style={{ ...cardStyle, padding: isMobile ? "14px" : "20px" }}>
          <h3 style={sectionTitle}>Station</h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: "4px 24px",
            }}
          >
            <InfoRow label="Model" value={station.type_name || "Unknown"} />
            <InfoRow
              label="Status"
              value={station.connected ? "Connected" : "Disconnected"}
            />
            <InfoRow
              label="Firmware"
              value={station.link_revision || "Unknown"}
            />
            <InfoRow label="Uptime" value={formatUptime(station.uptime_seconds ?? 0)} />
            <InfoRow
              label="Archive Records"
              value={(station.archive_records ?? 0).toLocaleString()}
            />
            <InfoRow
              label="Poll Interval"
              value={`${station.poll_interval ?? 0}s`}
            />
          </div>
        </div>
      )}

      {/* Software Stack */}
      <div style={{ ...cardStyle, padding: isMobile ? "14px" : "20px" }}>
        <h3 style={sectionTitle}>Software</h3>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
            gap: "4px 24px",
          }}
        >
          <InfoRow label="Frontend" value="React + TypeScript + Vite" />
          <InfoRow label="Backend" value="Python FastAPI" />
          <InfoRow label="Database" value="SQLite (SQLAlchemy)" />
          <InfoRow label="Protocol" value="Davis serial protocol driver" />
        </div>
      </div>

      {/* Links */}
      <div style={{ ...cardStyle, padding: isMobile ? "14px" : "20px" }}>
        <h3 style={sectionTitle}>Links</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <a
            href="https://github.com/placeholder/davis-wx-ui"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: "var(--color-accent)",
              fontSize: "14px",
              fontFamily: "var(--font-body)",
              textDecoration: "none",
            }}
          >
            GitHub Repository {'\u2192'}
          </a>
          <a
            href="https://www.davisinstruments.com/pages/weather-702"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: "var(--color-accent)",
              fontSize: "14px",
              fontFamily: "var(--font-body)",
              textDecoration: "none",
            }}
          >
            Davis Instruments {'\u2192'}
          </a>
        </div>
      </div>

      {/* Credits */}
      <div style={{ ...cardStyle, padding: isMobile ? "14px" : "20px" }}>
        <h3 style={sectionTitle}>Credits</h3>
        <p style={{ ...bodyText, fontSize: "13px" }}>
          Built with open-source software. Weather data from the National
          Weather Service, Open-Meteo, and NOAA. AI nowcasting powered by
          Anthropic Claude.
        </p>
      </div>

      {/* Support */}
      <SupportCard isMobile={isMobile} />
    </div>
  );
}
