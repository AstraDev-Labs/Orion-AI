import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from './components/ErrorBoundary';
import App from './App';
import { ClipboardPanel } from './pages/ClipboardPanel';
import { initApiBase } from './lib/api';
import { initAnalytics } from './lib/analytics';
import './index.css';

// The clipboard-intelligence panel is a separate small Tauri window that
// loads this same bundle with ?panel=clipboard — render it standalone,
// skipping the main app shell (setup screen, sidebar, routing, etc.).
const isClipboardPanel = new URLSearchParams(window.location.search).get('panel') === 'clipboard';

function applyTheme() {
  try {
    const raw = localStorage.getItem('orion-settings');
    const settings = raw ? JSON.parse(raw) : {};
    const theme = settings.theme || 'system';
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    } else if (theme === 'light') {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    }
  } catch { /* use system default */ }
}

applyTheme();

// Fetch the API base URL from the Tauri backend before rendering.
// This ensures ORION_PORT is defined in one place (the Rust backend).
// In non-Tauri environments this is a no-op.
initApiBase().finally(() => {
  if (isClipboardPanel) {
    // index.html's startup splash is removed by the main window's loading
    // screen, which the panel never renders: left in place it covered the
    // whole panel with the Orion logo.
    document.getElementById('boot-splash')?.remove();
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <ErrorBoundary>
          <ClipboardPanel />
        </ErrorBoundary>
      </StrictMode>,
    );
    return;
  }

  // Kick off analytics init in the background — it's never awaited so
  // a slow/failed identity fetch never delays UI render.
  void initAnalytics();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ErrorBoundary>
    </StrictMode>,
  );
});
