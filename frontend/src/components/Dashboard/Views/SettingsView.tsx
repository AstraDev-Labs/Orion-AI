import { useEffect, useRef, useState } from 'react';
import { Sliders, Volume2, Database } from 'lucide-react';
import { fetchSettings, updateSettings, type OrionSettings } from '../../../lib/api';

const modelKey = (engine: string, id: string) => `${engine}::${id}`;

export function SettingsView() {
  const [settings, setSettings] = useState<OrionSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');

  // Local, in-flight edits — kept separate from `settings` so a slider drag
  // or keystroke doesn't wait on a round-trip before the UI reflects it.
  const [temperature, setTemperature] = useState(70);
  const [obsidianDir, setObsidianDir] = useState('');
  const savedStatusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSettings()
      .then((data) => {
        if (cancelled) return;
        setSettings(data);
        setTemperature(Math.round(data.temperature * 100));
        setObsidianDir(data.obsidian_dir);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err?.message || 'Failed to load settings');
      });
    return () => {
      cancelled = true;
      if (savedStatusTimer.current) clearTimeout(savedStatusTimer.current);
    };
  }, []);

  const flashSaved = () => {
    setSaveStatus('saved');
    if (savedStatusTimer.current) clearTimeout(savedStatusTimer.current);
    savedStatusTimer.current = setTimeout(() => setSaveStatus('idle'), 1500);
  };

  const persist = async (update: Parameters<typeof updateSettings>[0]) => {
    setSaveStatus('saving');
    setSaveError(null);
    try {
      await updateSettings(update);
      setSettings((prev) => (prev ? { ...prev, ...update } : prev));
      flashSaved();
    } catch (err: any) {
      setSaveStatus('idle');
      setSaveError(err?.message || 'Failed to save setting');
    }
  };

  const handleModelChange = (value: string) => {
    const [engine, ...rest] = value.split('::');
    const model = rest.join('::');
    if (!engine || !model) return;
    persist({ engine, model });
  };

  const handleTemperatureCommit = (value: number) => {
    persist({ temperature: value / 100 });
  };

  const handleObsidianSave = () => {
    if (!settings || obsidianDir === settings.obsidian_dir) return;
    persist({ obsidian_dir: obsidianDir });
  };

  const currentModelKey = settings ? modelKey(settings.engine, settings.model) : '';
  const modelOptions = settings?.available_models ?? [];
  const hasCurrentModelOption = modelOptions.some(
    (m) => modelKey(m.engine, m.id) === currentModelKey,
  );

  return (
    <div className="w-full h-full flex flex-col p-8 overflow-y-auto">
      <div className="mb-10 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-light text-white mb-2">System Configuration</h2>
          <p className="text-white/50 text-sm">Manage Orion's core parameters and connectivity.</p>
        </div>
        <div className="text-xs text-white/40 h-4">
          {saveStatus === 'saving' && 'Saving…'}
          {saveStatus === 'saved' && <span className="text-purple-400">Saved</span>}
          {saveError && <span className="text-red-400">{saveError}</span>}
        </div>
      </div>

      {loadError && (
        <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-300 text-sm p-4 rounded-xl">
          Failed to load settings: {loadError}
        </div>
      )}

      <div className="flex flex-col gap-8">

        {/* Core Parameters */}
        <section>
          <h3 className="text-white/70 font-medium mb-4 flex items-center gap-2">
            <Sliders size={16} /> Core Parameters
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl">
              <label className="text-xs font-medium uppercase tracking-wider text-white/40 block mb-3">Language Model</label>
              <select
                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-white/90 text-sm focus:outline-none focus:border-purple-500/50 disabled:opacity-50"
                value={currentModelKey}
                disabled={!settings}
                onChange={(e) => handleModelChange(e.target.value)}
              >
                {!hasCurrentModelOption && settings && (
                  <option value={currentModelKey}>{settings.model} ({settings.engine})</option>
                )}
                {modelOptions.map((m) => (
                  <option key={modelKey(m.engine, m.id)} value={modelKey(m.engine, m.id)}>
                    {m.id} ({m.engine})
                  </option>
                ))}
              </select>
            </div>
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl">
              <label className="text-xs font-medium uppercase tracking-wider text-white/40 block mb-3">Reasoning Temp</label>
              <input
                type="range"
                min="0"
                max="100"
                value={temperature}
                disabled={!settings}
                className="w-full accent-purple-500 disabled:opacity-50"
                onChange={(e) => setTemperature(Number(e.target.value))}
                onMouseUp={(e) => handleTemperatureCommit(Number((e.target as HTMLInputElement).value))}
                onTouchEnd={(e) => handleTemperatureCommit(Number((e.target as HTMLInputElement).value))}
              />
              <div className="flex justify-between text-[10px] text-white/30 mt-2">
                <span>Deterministic</span>
                <span>Creative</span>
              </div>
            </div>
          </div>
        </section>

        {/* Voice Interface */}
        <section>
          <h3 className="text-white/70 font-medium mb-4 flex items-center gap-2">
            <Volume2 size={16} /> Voice Interface
          </h3>
          <div className="bg-white/5 border border-white/10 p-5 rounded-2xl flex items-center justify-between">
            <div>
              <p className="text-white/90 font-medium text-sm">Continuous Listening</p>
              <p className="text-white/40 text-xs mt-1">Orion will always listen for the wake word.</p>
            </div>
            <div className="w-12 h-6 bg-purple-500/20 rounded-full border border-purple-500/50 relative cursor-pointer">
              <div className="w-4 h-4 bg-purple-400 rounded-full absolute right-1 top-1 shadow-[0_0_10px_rgba(168,85,247,0.8)] glow-text-purple"></div>
            </div>
          </div>
        </section>

        {/* Database & Sync */}
        <section>
          <h3 className="text-white/70 font-medium mb-4 flex items-center gap-2">
            <Database size={16} /> Obsidian Sync
          </h3>
          <div className="bg-white/5 border border-white/10 p-5 rounded-2xl">
            <label className="text-xs font-medium uppercase tracking-wider text-white/40 block mb-3">Vault Path</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={obsidianDir}
                disabled={!settings}
                onChange={(e) => setObsidianDir(e.target.value)}
                onBlur={handleObsidianSave}
                onKeyDown={(e) => e.key === 'Enter' && handleObsidianSave()}
                className="flex-1 bg-black/40 border border-white/10 rounded-lg p-2 text-white/70 text-sm focus:outline-none disabled:opacity-50"
              />
              <button
                onClick={handleObsidianSave}
                disabled={!settings || obsidianDir === settings.obsidian_dir}
                className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Save
              </button>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
