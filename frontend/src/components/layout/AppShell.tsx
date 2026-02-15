import { useState, type ReactNode } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Footer from './Footer';

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

  return (
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
        background: 'var(--color-bg)',
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
  );
}
