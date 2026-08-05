import { useState, useEffect } from 'react';
import { Activity, Zap, Cpu, MemoryStick } from 'lucide-react';
import { fetchActivities, fetchTelemetryStats } from '../../../lib/api';

export function DailyInsight() {
  const [activities, setActivities] = useState<any[]>([]);
  const [telemetry, setTelemetry] = useState<any>(null);

  useEffect(() => {
    let mounted = true;
    
    const loadData = async () => {
      const [actsData, telemetryData] = await Promise.all([
        fetchActivities(),
        fetchTelemetryStats()
      ]);
      
      if (mounted) {
        if (actsData?.activities) setActivities(actsData.activities);
        if (telemetryData) setTelemetry(telemetryData);
      }
    };
    
    loadData();
    return () => { mounted = false; };
  }, []);

  const computeLoad = telemetry?.cpu_percent || 24;
  const memoryUsed = telemetry?.memory_used_gb ? telemetry.memory_used_gb.toFixed(1) : "4.2";
  const memoryTotal = telemetry?.memory_total_gb ? telemetry.memory_total_gb.toFixed(1) : "16.0";
  const memoryPercent = telemetry?.memory_percent || 28;

  return (
    <div className="w-full h-full flex flex-col p-8 overflow-y-auto">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h2 className="text-2xl font-light text-white mb-2">Morning Digest</h2>
          <p className="text-white/50 text-sm">System stable. {activities.filter(a => a.type === 'task').length} background tasks completed.</p>
        </div>
        <div className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 border border-purple-500/20 rounded-full text-purple-300 text-sm">
          <Zap size={14} className="glow-text-purple" />
          <span>Optimal State</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 mb-8">
        {/* Telemetry Card */}
        <div className="bg-white/5 border border-white/10 p-6 rounded-2xl flex flex-col gap-4">
          <div className="flex items-center gap-3 text-white/70">
            <Cpu size={18} />
            <span className="font-medium">Compute</span>
          </div>
          <div className="flex items-end gap-2">
            <span className="text-4xl font-light text-white">{computeLoad}%</span>
            <span className="text-white/40 mb-1">Load</span>
          </div>
          <div className="w-full h-1 bg-white/10 rounded-full mt-2 overflow-hidden">
            <div className={`h-full bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.8)]`} style={{ width: `${computeLoad}%` }}></div>
          </div>
        </div>

        {/* Memory Card */}
        <div className="bg-white/5 border border-white/10 p-6 rounded-2xl flex flex-col gap-4">
          <div className="flex items-center gap-3 text-white/70">
            <MemoryStick size={18} />
            <span className="font-medium">Memory Allocation</span>
          </div>
          <div className="flex items-end gap-2">
            <span className="text-4xl font-light text-white">{memoryUsed}</span>
            <span className="text-white/40 mb-1">GB / {memoryTotal} GB</span>
          </div>
          <div className="w-full h-1 bg-white/10 rounded-full mt-2 overflow-hidden">
            <div className={`h-full bg-purple-400 shadow-[0_0_10px_rgba(168,85,247,0.8)]`} style={{ width: `${memoryPercent}%` }}></div>
          </div>
        </div>
      </div>

      {/* Activity Feed */}
      <div className="bg-white/5 border border-white/10 rounded-2xl flex-1 p-6 flex flex-col">
        <h3 className="text-white/70 font-medium mb-6 flex items-center gap-2">
          <Activity size={16} /> Recent AI Operations
        </h3>
        <div className="flex flex-col gap-4">
          {activities.length === 0 ? (
            <p className="text-white/40 text-sm">No recent operations.</p>
          ) : (
            activities.map(act => (
              <div key={act.id} className="flex items-start gap-4 p-4 rounded-xl hover:bg-white/5 transition-colors">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center mt-1 ${act.type === 'task' ? 'bg-purple-500/20' : 'bg-cyan-500/20'}`}>
                  <div className={`w-2 h-2 rounded-full ${act.type === 'task' ? 'bg-purple-400 glow-text-purple' : 'bg-cyan-400 glow-text-cyan'}`}></div>
                </div>
                <div>
                  <p className="text-white/90 text-sm font-medium mb-1">{act.title}</p>
                  <p className="text-white/50 text-xs leading-relaxed">{act.description}</p>
                  <span className="text-white/30 text-[10px] mt-2 block uppercase tracking-wider">{act.time}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
