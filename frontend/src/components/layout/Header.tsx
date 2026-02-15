import { useTheme } from '../../context/ThemeContext';
import { themes } from '../../themes';

interface HeaderProps {
  connected: boolean;
  onMenuToggle: () => void;
  sidebarOpen: boolean;
}

export default function Header({ connected, onMenuToggle, sidebarOpen }: HeaderProps) {
  const { themeName, setThemeName } = useTheme();

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
