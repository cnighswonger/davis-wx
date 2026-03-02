import { useRegisterSW } from 'virtual:pwa-register/react';

export default function PWAUpdatePrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      // Check for updates every 60 minutes (for users who leave the dashboard open).
      if (registration) {
        setInterval(() => registration.update(), 60 * 60 * 1000);
      }
    },
  });

  if (!needRefresh) return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '1rem',
        right: '1rem',
        zIndex: 9999,
        background: 'var(--color-card, #1e2030)',
        border: '1px solid var(--color-accent, #3b82f6)',
        borderRadius: '8px',
        padding: '0.75rem 1rem',
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        fontFamily: 'Inter, sans-serif',
        fontSize: '0.875rem',
        color: 'var(--color-text, #e2e8f0)',
      }}
    >
      <span>Update available</span>
      <button
        onClick={() => updateServiceWorker(true)}
        style={{
          background: 'var(--color-accent, #3b82f6)',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          padding: '0.35rem 0.75rem',
          cursor: 'pointer',
          fontSize: '0.8125rem',
          fontWeight: 500,
        }}
      >
        Update
      </button>
      <button
        onClick={() => setNeedRefresh(false)}
        style={{
          background: 'transparent',
          color: 'var(--color-text-muted, #94a3b8)',
          border: '1px solid var(--color-border, #2d3348)',
          borderRadius: '4px',
          padding: '0.35rem 0.75rem',
          cursor: 'pointer',
          fontSize: '0.8125rem',
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
