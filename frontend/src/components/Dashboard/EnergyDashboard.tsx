import { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Zap, Activity, Thermometer, Hash, Gauge } from 'lucide-react';
import { fetchEnergy, fetchTelemetry } from '../../lib/api';
import { useAppStore } from '../../lib/store';

interface EnergySample {
  timestamp: string;
  power_w: number;
  energy_j: number;
}

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  samples?: EnergySample[];
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

interface ChartPoint {
  time: string;
  power: number;
}

function StatCard({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="hud-panel p-4 relative overflow-hidden">
      <div className="absolute top-0 left-0 w-2 h-[1px] bg-cyan-400/40" />
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={11} className="text-cyan-400" />
        <span className="text-[9px] font-mono uppercase tracking-wider text-zinc-400">{label}</span>
      </div>
      <div className="hud-mono text-xl font-bold truncate text-cyan-300" style={{ textShadow: '0 0 6px rgba(34,211,238,0.25)' }}>
        {value}
        {unit && (
          <span className="font-mono text-zinc-500 ml-1 text-xs uppercase tracking-widest">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

export function EnergyDashboard() {
  const savings = useAppStore((s) => s.savings);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [energyRes, telRes] = await Promise.allSettled([
        fetchEnergy().catch(() => null),
        fetchTelemetry().catch(() => null),
      ]);

      if (energyRes.status === 'fulfilled' && energyRes.value) {
        const data = energyRes.value as EnergyData;
        setEnergy(data);
        if (data.samples) {
          setChartData(
            data.samples.map((s) => ({
              time: new Date(s.timestamp).toLocaleTimeString(),
              power: Math.round(s.power_w * 10) / 10,
            })),
          );
        }
        setError(null);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
    } catch {
      setError('Cannot connect to server');
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const thermalStatus = (energy?.avg_power_w ?? 0) < 50
    ? { label: 'Cool', color: 'var(--color-success)' }
    : (energy?.avg_power_w ?? 0) < 150
    ? { label: 'Warm', color: 'var(--color-warning)' }
    : { label: 'Hot', color: 'var(--color-error)' };

  if (error || !energy) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <Zap size={12} style={{ color: 'var(--color-accent)' }} />
          Energy Monitoring
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">{error || 'awaiting telemetry stream…'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-4">
        <Zap size={12} style={{ color: 'var(--color-accent)' }} />
        Energy Monitoring
      </h3>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatCard
          icon={Zap}
          label="Total Energy"
          value={((energy.total_energy_j ?? 0) / 1000).toFixed(1)}
          unit="kJ"
        />
        <StatCard
          icon={Activity}
          label="Energy / Token"
          value={(energy.energy_per_token_j ?? 0).toFixed(3)}
          unit="J"
        />
        <StatCard
          icon={Thermometer}
          label="Avg Power"
          value={(energy.avg_power_w ?? 0).toFixed(1)}
          unit="W"
        />
        <StatCard
          icon={Hash}
          label="Total Requests"
          value={String(savings?.total_calls ?? telemetry?.total_requests ?? 0)}
        />
        <StatCard
          icon={Gauge}
          label="Thermal"
          value={thermalStatus.label}
        />
        <StatCard
          icon={Hash}
          label="Tokens Processed"
          value={formatNumber(savings?.total_tokens ?? telemetry?.total_tokens ?? 0)}
        />
      </div>

      {/* Chart */}
      {chartData.length > 1 && (
        <div className="h-48 mt-6">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(34, 211, 238, 0.08)" />
              <XAxis dataKey="time" tick={{ fontSize: 9, fontFamily: 'monospace', fill: 'var(--color-text-tertiary)' }} />
              <YAxis tick={{ fontSize: 9, fontFamily: 'monospace', fill: 'var(--color-text-tertiary)' }} unit="W" />
              <Tooltip
                contentStyle={{
                  background: 'rgba(10, 10, 11, 0.85)',
                  border: '1px solid rgba(34, 211, 238, 0.25)',
                  borderRadius: 'var(--radius-md)',
                  fontFamily: 'monospace',
                  fontSize: 11,
                  color: '#22d3ee',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                }}
              />
              <Line 
                type="monotone" 
                dataKey="power" 
                stroke="rgba(34, 211, 238, 0.85)" 
                strokeWidth={2.5} 
                dot={false} 
                activeDot={{ r: 4, stroke: '#22d3ee', strokeWidth: 1.5, fill: '#0a0a0b' }} 
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
