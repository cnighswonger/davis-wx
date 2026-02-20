import { useState, type ReactNode } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Footer from './Footer';
import WeatherBackground from '../WeatherBackground';
import { useWeatherBackground } from '../../context/WeatherBackgroundContext';

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
  const { enabled } = useWeatherBackground();

  return (
    <>
      <WeatherBackground />
      <div
        style={{
          display: 'grid',
          gridTemplateRows: '56px 1fr',
          gridTemplateColumns: '220px 1fr',
          gridTemplateAreas: `
            "header header"
            "sidebar main"
          `,
          minHeight: '100vh',
          background: enabled ? 'transparent' : 'var(--color-bg)',
          position: 'relative',
          zIndex: 3,
          transition: 'background-color 0.3s ease',
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
          <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
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
            {children}
          </div>
          <Footer lastUpdate={lastUpdate} />
        </main>
      </div>
    </>
  );
}
