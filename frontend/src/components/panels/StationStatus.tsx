/**
 * Compact panel showing station connection and health information.
 */
import { useState } from "react";
import { useWeatherData } from "../../context/WeatherDataContext.tsx";
import { syncStationTime } from "../../api/client.ts";

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "--";
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "--";
  }
}

export default function StationStatus() {
  const { stationStatus, connected, wsConnected } = useWeatherData();
  const [syncing, setSyncing] = useState(false);

  interface StatusRow {
    label: string;
    value: string;
    highlight?: "success" | "danger" | "warning" | null;
  }

  const rows: StatusRow[] = [
    {
      label: "Station",
      value: stationStatus?.type_name ?? "--",
    },
    {
      label: "Connected",
      value: stationStatus?.connected ? "Yes" : "No",
      highlight: stationStatus?.connected ? "success" : "danger",
    },
    {
      label: "WebSocket",
      value: wsConnected ? "Open" : "Closed",
      highlight: wsConnected ? "success" : "warning",
    },
    {
      label: "Backend Link",
      value: connected ? "Up" : "Down",
      highlight: connected ? "success" : "danger",
    },
    {
      label: "Uptime",
      value: stationStatus
        ? formatUptime(stationStatus.uptime_seconds)
        : "--",
    },
    {
      label: "Poll Interval",
      value: stationStatus ? `${stationStatus.poll_interval}s` : "--",
    },
    {
      label: "CRC Errors",
      value: stationStatus ? String(stationStatus.crc_errors) : "--",
      highlight:
        stationStatus && stationStatus.crc_errors > 0 ? "warning" : null,
    },
    {
      label: "Timeouts",
      value: stationStatus ? String(stationStatus.timeouts) : "--",
      highlight:
        stationStatus && stationStatus.timeouts > 0 ? "warning" : null,
    },
    {
      label: "Archive Records",
      value: stationStatus?.archive_records != null
        ? stationStatus.archive_records.toLocaleString()
        : "--",
    },
    {
      label: "Last Poll",
      value: formatTime(stationStatus?.last_poll ?? null),
    },
  ];

  function highlightColor(hl: "success" | "danger" | "warning" | null | undefined): string {
    if (hl === "success") return "var(--color-success)";
    if (hl === "danger") return "var(--color-danger)";
    if (hl === "warning") return "var(--color-warning)";
    return "var(--color-text)";
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        padding: "16px",
        background: "var(--color-bg-card)",
        borderRadius: "var(--gauge-border-radius, 16px)",
        boxShadow: "var(--gauge-shadow, 0 4px 24px rgba(0,0,0,0.4))",
        border: "1px solid var(--color-border)",
      }}
    >
      <div
        style={{
          fontSize: "12px",
          fontFamily: "var(--font-body)",
          color: "var(--color-text-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          marginBottom: "12px",
          textAlign: "center",
        }}
      >
        Station Status
      </div>

      {/* Station Time row - full width with sync button */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "10px",
          padding: "6px 8px",
          background: "var(--color-bg, rgba(0,0,0,0.15))",
          borderRadius: "8px",
        }}
      >
        <div>
          <span
            style={{
              fontSize: "11px",
              fontFamily: "var(--font-body)",
              color: "var(--color-text-muted)",
              marginRight: "8px",
            }}
          >
            Station Clock
          </span>
          <span
            style={{
              fontSize: "12px",
              fontFamily: "var(--font-gauge)",
              fontWeight: "bold",
              color: "var(--color-text)",
            }}
          >
            {stationStatus?.station_time ?? "--"}
          </span>
        </div>
        <button
          onClick={async () => {
            setSyncing(true);
            try {
              await syncStationTime();
            } catch {
              /* ignore */
            } finally {
              setSyncing(false);
            }
          }}
          disabled={syncing || !stationStatus?.connected}
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-body)",
            padding: "2px 8px",
            background: "var(--color-bg-card)",
            color: "var(--color-text-secondary)",
            border: "1px solid var(--color-border)",
            borderRadius: "4px",
            cursor: syncing ? "wait" : "pointer",
            opacity: syncing || !stationStatus?.connected ? 0.6 : 1,
          }}
        >
          {syncing ? "Syncing..." : "Sync"}
        </button>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "8px 16px",
        }}
      >
        {rows.map((row) => (
          <div
            key={row.label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: "8px",
            }}
          >
            <span
              style={{
                fontSize: "11px",
                fontFamily: "var(--font-body)",
                color: "var(--color-text-muted)",
              }}
            >
              {row.label}
            </span>
            <span
              style={{
                fontSize: "12px",
                fontFamily: "var(--font-gauge)",
                fontWeight: "bold",
                color: highlightColor(row.highlight),
              }}
            >
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
