/**
 * Main dashboard page composing all weather gauges, derived conditions,
 * and station status into a responsive CSS grid layout.
 *
 * Each gauge tile is wrapped in FlipTile — click to flip and see a
 * 1-hour historical chart for that sensor.
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
import FlipTile from "../components/common/FlipTile.tsx";

export default function Dashboard() {
  const { currentConditions } = useWeatherData();

  const cc = currentConditions;

  // Extract scalar values from ValueWithUnit objects for each gauge.
  // Every nested access must use optional chaining — when running in
  // demo mode (no serial connection), the API returns sparse/empty data.
  const tempOutside = cc?.temperature?.outside?.value ?? null;
  const tempOutsideUnit = cc?.temperature?.outside?.unit ?? "F";
  const tempInside = cc?.temperature?.inside?.value ?? null;
  const tempInsideUnit = cc?.temperature?.inside?.unit ?? "F";

  const baroValue = cc?.barometer?.value ?? null;
  const baroUnit = cc?.barometer?.unit ?? "inHg";
  const baroTrend = cc?.barometer?.trend as
    | "rising"
    | "falling"
    | "steady"
    | null
    | undefined;
  const baroTrendRate = cc?.barometer?.trend_rate ?? null;

  const windDirection = cc?.wind?.direction?.value ?? null;
  const windSpeed = cc?.wind?.speed?.value ?? null;
  const windGust = cc?.wind?.gust?.value ?? null;
  const windUnit = cc?.wind?.speed?.unit ?? "mph";
  const windCardinal = cc?.wind?.cardinal ?? null;

  const humidityOutside = cc?.humidity?.outside?.value ?? null;
  const humidityInside = cc?.humidity?.inside?.value ?? null;

  const rainRate = cc?.rain?.rate?.value ?? null;
  const rainDaily = cc?.rain?.daily?.value ?? null;
  const rainYearly = cc?.rain?.yearly?.value ?? null;
  const rainUnit = cc?.rain?.daily?.unit ?? "in";

  const solarRadiation = cc?.solar_radiation?.value ?? null;
  const uvIndex = cc?.uv_index?.value ?? null;
  const hasSolar = cc?.solar_radiation != null;
  const hasUV = cc?.uv_index != null;
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
        <FlipTile sensor="outside_temp" label="Outside Temperature" unit="°F">
          <TemperatureGauge
            value={tempOutside}
            unit={tempOutsideUnit}
            label="Outside"
          />
        </FlipTile>
        <FlipTile sensor="inside_temp" label="Inside Temperature" unit="°F">
          <TemperatureGauge
            value={tempInside}
            unit={tempInsideUnit}
            label="Inside"
          />
        </FlipTile>
        <FlipTile sensor="barometer" label="Barometer" unit="inHg">
          <BarometerDial
            value={baroValue}
            unit={baroUnit}
            trend={baroTrend}
            trendRate={baroTrendRate}
          />
        </FlipTile>
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
        <FlipTile sensor="wind_speed" label="Wind Speed" unit="mph">
          <WindCompass
            direction={windDirection}
            speed={windSpeed}
            gust={windGust}
            unit={windUnit}
            cardinal={windCardinal}
          />
        </FlipTile>
        <FlipTile sensor="outside_humidity" label="Outside Humidity" unit="%">
          <HumidityGauge value={humidityOutside} label="Outside" />
        </FlipTile>
        <FlipTile sensor="inside_humidity" label="Inside Humidity" unit="%">
          <HumidityGauge value={humidityInside} label="Inside" />
        </FlipTile>
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
        <FlipTile sensor="rain_total" label="Rain" unit="clicks">
          <RainGauge
            rate={rainRate}
            daily={rainDaily}
            yearly={rainYearly}
            unit={rainUnit}
          />
        </FlipTile>
        {showSolarUV && (
          <FlipTile sensor="solar_radiation" label="Solar Radiation" unit="W/m²">
            <SolarUVGauge
              solarRadiation={solarRadiation}
              uvIndex={uvIndex}
            />
          </FlipTile>
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
