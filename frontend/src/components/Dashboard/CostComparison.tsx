import { DollarSign, TrendingDown, Cloud, HardDrive } from 'lucide-react';
import { useAppStore } from '../../lib/store';

const CLOUD_PRICING = [
  { name: 'GPT-5.3', input: 2.00, output: 10.00 },
  { name: 'Claude Opus 4.6', input: 5.00, output: 25.00 },
  { name: 'Gemini 3.1 Pro', input: 2.00, output: 12.00 },
];

export function CostComparison() {
  const savings = useAppStore((s) => s.savings);

  if (!savings || savings.total_tokens === 0) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <DollarSign size={12} style={{ color: 'var(--color-success)' }} />
          Cost Comparison
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">awaiting first inference…</span>
        </div>
      </div>
    );
  }

  const promptK = savings.total_prompt_tokens / 1000;
  const completionK = savings.total_completion_tokens / 1000;

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-4">
        <DollarSign size={12} style={{ color: 'var(--color-success)' }} />
        Cost Comparison*
      </h3>

      {/* Local stats */}
      <div
        className="flex items-center gap-3 p-3 rounded-lg mb-3 relative overflow-hidden"
        style={{ background: 'rgba(34, 211, 238, 0.08)', border: '1px solid rgba(34, 211, 238, 0.35)' }}
      >
        <div className="absolute top-0 left-0 w-1.5 h-[1px] bg-cyan-400" />
        <HardDrive size={18} className="text-cyan-400" />
        <div className="flex-1">
          <div className="text-sm font-semibold text-cyan-300 font-mono">
            LOCAL_COMPUTE_ENGINE
          </div>
          <div className="text-xs font-mono text-zinc-400">
            {savings.total_calls} queries &middot; {savings.total_tokens.toLocaleString()} tokens
          </div>
        </div>
        <div className="text-right">
          <div className="text-lg font-bold font-mono text-cyan-300" style={{ textShadow: '0 0 6px rgba(34,211,238,0.3)' }}>
            ${savings.local_cost.toFixed(4)}
          </div>
          <div className="text-[9px] font-mono text-zinc-500 uppercase tracking-wider">
            electricity draw
          </div>
        </div>
      </div>

      {/* Cloud comparisons */}
      <div className="flex flex-col gap-2">
        {CLOUD_PRICING.map((provider) => {
          const cost = (promptK * provider.input / 1000) + (completionK * provider.output / 1000);
          const saved = cost - savings.local_cost;
          return (
            <div
              key={provider.name}
              className="flex items-center gap-3 p-3 rounded-lg border"
              style={{ background: 'rgba(255, 255, 255, 0.02)', borderColor: 'rgba(255, 255, 255, 0.05)' }}
            >
              <Cloud size={16} className="text-zinc-500" />
              <div className="flex-1">
                <div className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                  {provider.name}
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs font-mono text-zinc-200">
                  ${cost.toFixed(4)}
                </div>
                {saved > 0 && (
                  <div className="text-[10px] font-mono flex items-center gap-0.5 justify-end text-cyan-400" style={{ textShadow: '0 0 4px rgba(34,211,238,0.2)' }}>
                    <TrendingDown size={10} />
                    -${saved.toFixed(4)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
        <p className="text-[10px] leading-relaxed" style={{ color: 'var(--color-text-tertiary)' }}>
          *Savings estimates assume local models (e.g. Qwen, Nemotron, Kimi) produce roughly the same number of tokens per request, on average, as closed-source cloud models.
        </p>
      </div>
    </div>
  );
}
