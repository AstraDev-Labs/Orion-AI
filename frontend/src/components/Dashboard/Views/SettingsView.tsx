import { Sliders, Volume2, Key, Database, Monitor } from 'lucide-react';

export function SettingsView() {
  return (
    <div className="w-full h-full flex flex-col p-8 overflow-y-auto">
      <div className="mb-10">
        <h2 className="text-2xl font-light text-white mb-2">System Configuration</h2>
        <p className="text-white/50 text-sm">Manage Orion's core parameters and connectivity.</p>
      </div>

      <div className="flex flex-col gap-8">
        
        {/* Core Parameters */}
        <section>
          <h3 className="text-white/70 font-medium mb-4 flex items-center gap-2">
            <Sliders size={16} /> Core Parameters
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl">
              <label className="text-xs font-medium uppercase tracking-wider text-white/40 block mb-3">Language Model</label>
              <select className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-white/90 text-sm focus:outline-none focus:border-purple-500/50">
                <option>GPT-4o (OpenAI)</option>
                <option>Claude 3.5 Sonnet (Anthropic)</option>
                <option>Llama 3 70B (Local)</option>
              </select>
            </div>
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl">
              <label className="text-xs font-medium uppercase tracking-wider text-white/40 block mb-3">Reasoning Temp</label>
              <input type="range" min="0" max="100" defaultValue="70" className="w-full accent-purple-500" />
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
              <input type="text" defaultValue="/Users/Shared/ObsidianVault" className="flex-1 bg-black/40 border border-white/10 rounded-lg p-2 text-white/70 text-sm focus:outline-none" readOnly />
              <button className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm transition-colors">Browse</button>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
