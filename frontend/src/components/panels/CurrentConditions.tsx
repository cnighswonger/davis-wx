/**
 * Compact grid panel showing derived weather values:
 * Feels Like, Heat Index, Dew Point, Wind Chill, Theta-E.
 */
import { useWeatherData } from "../../context/WeatherDataContext.tsx";
import type { ValueWithUnit } from "../../api/types.ts";

interface DerivedItem {
  label: string;
  data: ValueWithUnit | null | undefined;
}

function formatValue(item: ValueWithUnit | null | undefined): string {
  if (!item) return "--";
  return `${item.value.toFixed(1)} ${item.unit}`;
}

export default function CurrentConditions() {
  const { currentConditions } = useWeatherData();

  const derived = currentConditions?.derived;

  const items: DerivedItem[] = [
    { label: "Feels Like", data: derived?.feels_like },
    { label: "Heat Index", data: derived?.heat_index },
    { label: "Dew Point", data: derived?.dew_point },
    { label: "Wind Chill", data: derived?.wind_chill },
    { label: "Theta-E", data: derived?.theta_e },
  ];

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
        minWidth: "160px",
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
        Derived Conditions
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "12px 16px",
        }}
      >
        {items.map((item) => (
          <div key={item.label} style={{ textAlign: "center" }}>
            <div
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-body)",
                color: "var(--color-text-muted)",
                textTransform: "uppercase",
                marginBottom: "2px",
              }}
            >
              {item.label}
            </div>
            <div
              style={{
                fontSize: "16px",
                fontFamily: "var(--font-gauge)",
                fontWeight: "bold",
                color: item.data
                  ? "var(--color-text)"
                  : "var(--color-text-muted)",
              }}
            >
              {formatValue(item.data)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
