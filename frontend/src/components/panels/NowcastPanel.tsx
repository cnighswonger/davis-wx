/**
 * Compact dashboard tile for AI Nowcast summary.
 */
import { useWeatherData } from "../../context/WeatherDataContext.tsx";
import { useCompact } from "../../dashboard/CompactContext.tsx";

function confidenceColor(c: string): string {
  switch (c?.toUpperCase()) {
    case "HIGH":
      return "var(--color-success)";
    case "MEDIUM":
      return "var(--color-warning, #f59e0b)";
    case "LOW":
      return "var(--color-danger)";
    default:
      return "var(--color-text-muted)";
  }
}

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export default function NowcastPanel() {
  const { nowcast } = useWeatherData();
  const isCompact = useCompact();

  if (!nowcast) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          padding: "16px",
          background: "var(--color-bg-card)",
          borderRadius: "var(--gauge-border-radius, 16px)",
          boxShadow: "var(--gauge-shadow, 0 4px 24px rgba(0,0,0,0.4))",
          border: "1px solid var(--color-border)",
          boxSizing: "border-box",
        }}
      >
        <span
          style={{
            fontSize: "13px",
            fontFamily: "var(--font-body)",
            color: "var(--color-text-muted)",
            textAlign: "center",
          }}
        >
          AI Nowcast not available
        </span>
      </div>
    );
  }

  // Find the overall confidence (use precipitation if available, else first element).
  const elements = nowcast.elements || {};
  const overallConfidence =
    elements.precipitation?.confidence ||
    elements.temperature?.confidence ||
    "MEDIUM";

  // Highlight precipitation timing if present.
  const precipTiming = elements.precipitation?.timing;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: isCompact ? "12px" : "16px",
        background: "var(--color-bg-card)",
        borderRadius: "var(--gauge-border-radius, 16px)",
        boxShadow: "var(--gauge-shadow, 0 4px 24px rgba(0,0,0,0.4))",
        border: "1px solid var(--color-border)",
        height: "100%",
        boxSizing: "border-box",
        gap: "8px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontSize: "12px",
            fontFamily: "var(--font-body)",
            color: "var(--color-text-secondary)",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}
        >
          AI Nowcast
        </span>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-body)",
            color: "var(--color-text-muted)",
          }}
        >
          {timeAgo(nowcast.created_at)}
        </span>
      </div>

      {/* Summary */}
      <p
        style={{
          margin: 0,
          fontSize: isCompact ? "12px" : "13px",
          fontFamily: "var(--font-body)",
          color: "var(--color-text)",
          lineHeight: 1.5,
          flex: 1,
          overflow: "hidden",
          display: "-webkit-box",
          WebkitLineClamp: isCompact ? 3 : 4,
          WebkitBoxOrient: "vertical",
        }}
      >
        {nowcast.summary}
      </p>

      {/* Precipitation timing highlight */}
      {precipTiming && (
        <div
          style={{
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
            color: "var(--color-rain-blue, var(--color-accent))",
            padding: "4px 8px",
            background: "var(--color-bg-secondary)",
            borderRadius: "4px",
          }}
        >
          {precipTiming}
        </div>
      )}

      {/* Confidence indicator */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          fontSize: "11px",
          fontFamily: "var(--font-body)",
          color: "var(--color-text-muted)",
        }}
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: confidenceColor(overallConfidence),
            flexShrink: 0,
          }}
        />
        {overallConfidence} confidence
      </div>
    </div>
  );
}
