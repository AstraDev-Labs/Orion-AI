import { useEffect, useCallback, useRef, useState } from 'react';
import { CommandPalette } from './components/CommandPalette';
import { LoadingScreen } from './hud/LoadingScreen';
import { OptInModal } from './components/OptInModal';
import { UpdateChecker } from './components/Desktop/UpdateChecker';
import { Toaster } from 'sonner';
import { HolotableShell } from './hud/HolotableShell';
import { useAppStore } from './lib/store';
import { fetchModels, fetchServerInfo, fetchSavings, submitSavings, isTauri } from './lib/api';
import { track, hashId } from './lib/analytics';
import { useChannelNotifications } from './lib/useChannelNotifications';

export default function App() {
  useChannelNotifications();
  // Both the desktop app and the browser wait for Orion to really be up.
  const [setupDone, setSetupDone] = useState(false);
  const handleSetupReady = useCallback(() => {
    setSetupDone(true);
    track('setup_completed', { preset: 'default' });
  }, []);

  const prevModelRef = useRef<string>('');
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInAnonId = useAppStore((s) => s.optInAnonId);
  const importOverlay = useAppStore((s) => s.importOverlayConversation);

  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  useEffect(() => {
    // The backend can take a moment to come up (or the bridge/model
    // discovery boot race can 500/refuse the first request), so this
    // retries on failure instead of leaving the model list empty forever --
    // a one-shot fetch here was the root cause of "no model selected"
    // surviving well past the backend actually being ready.
    let cancelled = false;
    const load = () => {
      // Use the model the backend is running (/v1/info), not whichever model
      // Ollama happens to list first. Picking m[0] sent qwen3.5:2b while the
      // backend ran qwen3.5:4b: worse answers, plus a model swap on every turn.
      // The HUD has no model picker, so the backend is the source of truth.
      Promise.all([fetchModels(), fetchServerInfo().catch(() => null)])
        .then(([m, info]) => {
          if (cancelled) return;
          setModels(m);
          const backendModel = info?.model;
          if (backendModel && m.some((x) => x.id === backendModel)) {
            setSelectedModel(backendModel);
          } else if (!selectedModel && m.length > 0) {
            setSelectedModel(m[0].id);
          }
          setModelsLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          setTimeout(load, 2000);
        });
    };
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const refresh = () =>
      fetchSavings()
        .then((data) => {
          setSavings(data);
          if (optInEnabled && optInDisplayName && data) {
            const claudeEntry = data.per_provider.find((p) => p.provider === 'claude-opus-4.6');
            const dollarSavings = claudeEntry ? claudeEntry.total_cost : 0;
            const energySaved = data.per_provider.reduce((sum, p) => sum + (p.energy_wh || 0), 0);
            const flopsSaved = data.per_provider.reduce((sum, p) => sum + (p.flops || 0), 0);
            submitSavings({
              anon_id: optInAnonId,
              display_name: optInDisplayName,
              email: optInEmail,
              total_calls: data.total_calls,
              total_tokens: data.total_tokens,
              dollar_savings: dollarSavings,
              energy_wh_saved: energySaved,
              flops_saved: flopsSaved,
              token_counting_version: data.token_counting_version ?? 1,
            });
          }
        })
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [optInEnabled, optInDisplayName, optInAnonId, optInEmail, setSavings]);

  const prevModel = selectedModel;
  useEffect(() => {
    const prev = prevModelRef.current;
    const curr = prevModel || '';
    prevModelRef.current = curr;
    if (!prev || !curr || prev === curr) return;
    void (async () => {
      const [fromHash, toHash] = await Promise.all([hashId(prev), hashId(curr)]);
      track('model_changed', { from_model_hash: fromHash, to_model_hash: toHash });
    })();
  }, [prevModel]);

  useEffect(() => {
    const t = setTimeout(() => track('app_opened', {}), 500);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);

  if (!setupDone) {
    return <LoadingScreen onReady={handleSetupReady} />;
  }

  // The Holotable HUD is the only UI. The previous sidebar screens (/chat,
  // /agents, /memory, /insights, /settings) were removed, so every path
  // renders the HUD rather than a blank route.
  return (
    <div className="w-screen h-screen overflow-hidden">
      <UpdateChecker />
      <HolotableShell />
      <Toaster position="bottom-right" theme="dark" />
      {commandPaletteOpen && <CommandPalette />}
      <OptInModal />
    </div>
  );
}
