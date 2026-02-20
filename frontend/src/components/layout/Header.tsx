import { useTheme } from '../../context/ThemeContext';
import { useWeatherData } from '../../context/WeatherDataContext';
import { themes } from '../../themes';

// --- Inline SVG weather icons (20x20, currentColor) ---

const iconProps = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function IconSun() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function IconSunCloud() {
  return (
    <svg {...iconProps}>
      <path d="M12 2v2" />
      <path d="M4.93 4.93l1.41 1.41" />
      <path d="M20 12h2" />
      <path d="M19.07 4.93l-1.41 1.41" />
      <circle cx="12" cy="10" r="4" />
      <path d="M8 16h8a4 4 0 0 0 0-8H7a5 5 0 0 0 0 10z" fill="currentColor" opacity="0.15" stroke="currentColor" />
    </svg>
  );
}

function IconCloud() {
  return (
    <svg {...iconProps}>
      <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
    </svg>
  );
}

function IconCloudDrizzle() {
  return (
    <svg {...iconProps}>
      <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
      <line x1="8" y1="19" x2="8" y2="21" />
      <line x1="12" y1="19" x2="12" y2="21" />
      <line x1="16" y1="19" x2="16" y2="21" />
    </svg>
  );
}

function IconRain() {
  return (
    <svg {...iconProps}>
      <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
      <line x1="8" y1="19" x2="7" y2="22" />
      <line x1="12" y1="19" x2="11" y2="22" />
      <line x1="16" y1="19" x2="15" y2="22" />
    </svg>
  );
}

function IconStorm() {
  return (
    <svg {...iconProps}>
      <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
      <polyline points="13 16 11 20 15 20 13 24" />
    </svg>
  );
}

function mapForecastIcon(text: string): React.ReactNode {
  const t = text.toLowerCase();
  if (t.includes("stormy")) return <IconStorm />;
  if (t.includes("rain") || t.includes("very unsettled")) return <IconRain />;
  if (t.includes("shower")) return <IconCloudDrizzle />;
  if (t.includes("changeable") || t.includes("unsettled") || t.includes("less settled")) return <IconCloud />;
  if (t.includes("fairly fine") || t.includes("becoming fine") || t.includes("improving")) return <IconSunCloud />;
  return <IconSun />;
}

function trendArrow(trend: string | null): { symbol: string; color: string } {
  if (trend === "rising") return { symbol: "\u25B2", color: "var(--color-success)" };
  if (trend === "falling") return { symbol: "\u25BC", color: "var(--color-warning)" };
  return { symbol: "\u25B6", color: "var(--color-text-muted)" };
}

// --- Header component ---

interface HeaderProps {
  connected: boolean;
  onMenuToggle: () => void;
  sidebarOpen: boolean;
}

export default function Header({ connected, onMenuToggle, sidebarOpen }: HeaderProps) {
  const { themeName, setThemeName } = useTheme();
  const { currentConditions, forecast } = useWeatherData();
  const extremes = currentConditions?.daily_extremes;
  const hi = extremes?.outside_temp_hi?.value;
  const lo = extremes?.outside_temp_lo?.value;
  const local = forecast?.local ?? null;

  return (
    <header
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: '56px',
        background: 'var(--color-header-bg)',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        zIndex: 100,
        fontFamily: 'var(--font-body)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          onClick={onMenuToggle}
          aria-label={sidebarOpen ? 'Close menu' : 'Open menu'}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--color-text)',
            fontSize: '20px',
            cursor: 'pointer',
            padding: '4px 8px',
            borderRadius: '4px',
            display: 'none',
            lineHeight: 1,
          }}
          className="header-menu-btn"
        >
          {sidebarOpen ? '\u2715' : '\u2630'}
        </button>
        <h1
          style={{
            margin: 0,
            fontSize: '18px',
            fontWeight: 600,
            color: 'var(--color-text)',
            fontFamily: 'var(--font-heading)',
            letterSpacing: '-0.01em',
          }}
        >
          Davis Weather Station
        </h1>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {local && (
          <div
            className="header-forecast"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '13px',
              color: 'var(--color-text-secondary)',
              whiteSpace: 'nowrap',
            }}
          >
            <span style={{ display: 'flex', color: 'var(--color-text)' }}>
              {mapForecastIcon(local.text)}
            </span>
            <span>{local.text}</span>
            <span style={{ color: trendArrow(local.trend).color, fontSize: '10px' }}>
              {trendArrow(local.trend).symbol}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--color-text-muted)' }}>
              {local.confidence}%
            </span>
          </div>
        )}

        <div
          className="header-hilo"
          style={{
            fontSize: '13px',
            fontFamily: 'var(--font-gauge)',
            color: 'var(--color-text-secondary)',
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ color: 'var(--color-temp-hot, #ef4444)' }}>
            H {hi != null ? `${hi.toFixed(1)}°` : '--'}
          </span>
          {' / '}
          <span style={{ color: 'var(--color-temp-cold, #3b82f6)' }}>
            L {lo != null ? `${lo.toFixed(1)}°` : '--'}
          </span>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '13px',
            color: 'var(--color-text-secondary)',
          }}
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: connected ? 'var(--color-success)' : 'var(--color-danger)',
              display: 'inline-block',
              boxShadow: connected
                ? '0 0 6px var(--color-success)'
                : '0 0 6px var(--color-danger)',
            }}
          />
          <span>{connected ? 'Connected' : 'Disconnected'}</span>
        </div>

        <select
          value={themeName}
          onChange={(e) => setThemeName(e.target.value)}
          style={{
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            padding: '6px 10px',
            fontSize: '13px',
            fontFamily: 'var(--font-body)',
            cursor: 'pointer',
            outline: 'none',
          }}
        >
          {Object.values(themes).map((t) => (
            <option key={t.name} value={t.name}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}
