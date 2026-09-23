import { useState } from 'react';
import { useAppStore } from '../lib/store';
import { fetchModels, getBase } from '../lib/api';
import { chooseChatModel, isChatModel, MODEL_PREFERENCE_KEY } from '../lib/chatModels';

export function ChatModelSelector({ disabled = false }: { disabled?: boolean }) {
  const models = useAppStore((s) => s.models);
  const loading = useAppStore((s) => s.modelsLoading);
  const selected = useAppStore((s) => s.selectedModel);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const chat = models.filter(isChatModel);
  const specialists = models.filter((m) => !isChatModel(m));

  async function select(model: string) {
    if (!model || busy || disabled) return;
    setBusy(true);
    setError('');
    try {
      const res = await fetch(`${getBase()}/v1/config`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      });
      if (!res.ok) throw new Error('Could not save your model. Please try again.');
      useAppStore.getState().setSelectedModel(model);
      try { localStorage.setItem(MODEL_PREFERENCE_KEY, model); } catch { /* backend saved it */ }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change model.');
    } finally { setBusy(false); }
  }

  async function refresh() {
    setBusy(true);
    setError('');
    try {
      const list = await fetchModels();
      useAppStore.getState().setModels(list);
      useAppStore.getState().setSelectedModel(chooseChatModel(list, selected));
    } catch { setError('Could not refresh models. Check that Orion is connected.'); }
    finally { setBusy(false); }
  }

  return (
    <div className="holo-model-picker">
      <label htmlFor="chat-model">Chat model</label>
      <select id="chat-model" value={selected} disabled={disabled || busy || loading || !chat.length}
        onChange={(e) => void select(e.target.value)}>
        {!selected && <option value="">{loading ? 'Loading models…' : 'No chat model installed'}</option>}
        <optgroup label="Chat">
          {chat.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
        </optgroup>
        {!!specialists.length && <optgroup label="Used by tools">
          {specialists.map((m) => <option key={m.id} value={m.id} disabled>{m.id} — {m.purpose || 'specialist'}</option>)}
        </optgroup>}
      </select>
      <button className="holo-ghost-btn" disabled={disabled || busy || loading} onClick={() => void refresh()}>
        {busy ? 'Updating…' : 'Refresh'}
      </button>
      {!loading && !chat.length && <span role="status">Install a chat model in Ollama, then refresh.</span>}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
