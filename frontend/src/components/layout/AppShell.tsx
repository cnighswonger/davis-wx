import { useState, useEffect, type ReactNode } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Footer from './Footer';
import WeatherBackground from '../WeatherBackground';
import { useWeatherBackground } from '../../context/WeatherBackgroundContext';
import { useWeatherData } from '../../context/WeatherDataContext';

interface AppShellProps {
  children: ReactNode;
  connected?: boolean;
  lastUpdate?: Date | null;
}

export default function AppShell({
  children,
  connected = false,
  lastUpdate = null,
}: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('sidebar-collapsed') === 'true'; }
    catch { return false; }
  });
  const { enabled } = useWeatherBackground();
  const { nowcastWarning, dismissNowcastWarning } = useWeatherData();

  // Auto-dismiss warning after 30 seconds.
  useEffect(() => {
    if (!nowcastWarning) return;
    const timer = setTimeout(dismissNowcastWarning, 30_000);
    return () => clearTimeout(timer);
  }, [nowcastWarning, dismissNowcastWarning]);

  const toggleCollapse = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem('sidebar-collapsed', String(next)); } catch {}
      return next;
    });
  };

  const sidebarWidth = sidebarCollapsed ? '56px' : '220px';

  return (
    <>
      <WeatherBackground />
      <div
        style={{
          display: 'grid',
          gridTemplateRows: '56px 1fr',
          gridTemplateColumns: `${sidebarWidth} 1fr`,
          gridTemplateAreas: `
            "header header"
            "sidebar main"
          `,
          minHeight: '100vh',
          background: enabled ? 'transparent' : 'var(--color-bg)',
          position: 'relative',
          zIndex: 3,
          transition: 'background-color 0.3s ease, grid-template-columns 0.2s ease',
        }}
        className="app-shell"
      >
        <div style={{ gridArea: 'header' }}>
          <Header
            connected={connected}
            onMenuToggle={() => setSidebarOpen((prev) => !prev)}
            sidebarOpen={sidebarOpen}
          />
        </div>

        <div style={{ gridArea: 'sidebar' }}>
          <Sidebar
            open={sidebarOpen}
            onClose={() => setSidebarOpen(false)}
            collapsed={sidebarCollapsed}
            onToggleCollapse={toggleCollapse}
          />
        </div>

        <main
          style={{
            gridArea: 'main',
            marginTop: '56px',
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
            overflow: 'hidden',
          }}
        >
          <div
            className="app-main-content"
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '24px',
            }}
          >
            {nowcastWarning && (
              <div
                role="alert"
                onClick={dismissNowcastWarning}
                style={{
                  padding: '10px 16px',
                  marginBottom: 16,
                  background: 'var(--color-warning-bg, #664d03)',
                  color: 'var(--color-warning-text, #fff3cd)',
                  border: '1px solid var(--color-warning-border, #997404)',
                  borderRadius: 8,
                  fontSize: 13,
                  fontFamily: 'var(--font-body)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <span style={{ flexShrink: 0 }}>{'\u26A0'}</span>
                <span style={{ flex: 1 }}>{nowcastWarning}</span>
                <span style={{ flexShrink: 0, opacity: 0.7, fontSize: 11 }}>click to dismiss</span>
              </div>
            )}
            {children}
          </div>
          <Footer lastUpdate={lastUpdate} />
        </main>
      </div>
    </>
  );
}
