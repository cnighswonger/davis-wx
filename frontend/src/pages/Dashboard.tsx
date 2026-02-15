/**
 * Main dashboard page composing all weather gauges, derived conditions,
 * and station status into a responsive CSS grid layout.
 */
import { useWeatherData } from "../context/WeatherDataContext.tsx";
import TemperatureGauge from "../components/gauges/TemperatureGauge.tsx";
import BarometerDial from "../components/gauges/BarometerDial.tsx";
import WindCompass from "../components/gauges/WindCompass.tsx";
import HumidityGauge from "../components/gauges/HumidityGauge.tsx";
import RainGauge from "../components/gauges/RainGauge.tsx";
import SolarUVGauge from "../components/gauges/SolarUVGauge.tsx";
import CurrentConditions from "../components/panels/CurrentConditions.tsx";
import StationStatus from "../components/panels/StationStatus.tsx";

export default function Dashboard() {
  const { currentConditions } = useWeatherData();

  const cc = currentConditions;

  // Extract scalar values from ValueWithUnit objects for each gauge.
  const tempOutside = cc?.temperature.outside?.value ?? null;
  const tempOutsideUnit = cc?.temperature.outside?.unit ?? "F";
  const tempInside = cc?.temperature.inside?.value ?? null;
  const tempInsideUnit = cc?.temperature.inside?.unit ?? "F";

  const baroValue = cc?.barometer.value ?? null;
  const baroUnit = cc?.barometer.unit ?? "inHg";
  const baroTrend = cc?.barometer.trend as
    | "rising"
    | "falling"
    | "steady"
    | null
    | undefined;
  const baroTrendRate = cc?.barometer.trend_rate ?? null;

  const windDirection = cc?.wind.direction?.value ?? null;
  const windSpeed = cc?.wind.speed?.value ?? null;
  const windGust = cc?.wind.gust?.value ?? null;
  const windUnit = cc?.wind.speed?.unit ?? "mph";
  const windCardinal = cc?.wind.cardinal ?? null;

  const humidityOutside = cc?.humidity.outside?.value ?? null;
  const humidityInside = cc?.humidity.inside?.value ?? null;

  const rainRate = cc?.rain.rate?.value ?? null;
  const rainDaily = cc?.rain.daily?.value ?? null;
  const rainYearly = cc?.rain.yearly?.value ?? null;
  const rainUnit = cc?.rain.daily?.unit ?? "in";

  const solarRadiation = cc?.solar_radiation?.value ?? null;
  const uvIndex = cc?.uv_index?.value ?? null;
  const hasSolar = cc?.solar_radiation !== null && cc?.solar_radiation !== undefined;
  const hasUV = cc?.uv_index !== null && cc?.uv_index !== undefined;
  const showSolarUV = hasSolar || hasUV;

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
        Dashboard
      </h2>

      {/* Top row: Temperatures + Barometer */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "16px",
          marginBottom: "16px",
        }}
      >
        <TemperatureGauge
          value={tempOutside}
          unit={tempOutsideUnit}
          label="Outside"
        />
        <TemperatureGauge
          value={tempInside}
          unit={tempInsideUnit}
          label="Inside"
        />
        <BarometerDial
          value={baroValue}
          unit={baroUnit}
          trend={baroTrend}
          trendRate={baroTrendRate}
        />
      </div>

      {/* Middle row: Wind + Humidity */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "16px",
          marginBottom: "16px",
        }}
      >
        <WindCompass
          direction={windDirection}
          speed={windSpeed}
          gust={windGust}
          unit={windUnit}
          cardinal={windCardinal}
        />
        <HumidityGauge value={humidityOutside} label="Outside" />
        <HumidityGauge value={humidityInside} label="Inside" />
      </div>

      {/* Third row: Rain, Solar/UV (conditional), Derived Conditions */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "16px",
          marginBottom: "16px",
        }}
      >
        <RainGauge
          rate={rainRate}
          daily={rainDaily}
          yearly={rainYearly}
          unit={rainUnit}
        />
        {showSolarUV && (
          <SolarUVGauge
            solarRadiation={solarRadiation}
            uvIndex={uvIndex}
          />
        )}
        <CurrentConditions />
      </div>

      {/* Bottom row: Station Status */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr",
          gap: "16px",
        }}
      >
        <StationStatus />
      </div>
    </div>
  );
}
