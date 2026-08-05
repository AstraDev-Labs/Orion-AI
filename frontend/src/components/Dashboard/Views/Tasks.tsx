import { useState, useEffect } from 'react';
import { CheckCircle2, Circle, Clock, Plus } from 'lucide-react';
import { fetchTasks } from '../../../lib/api';

export function Tasks() {
  const [tasks, setTasks] = useState<any[]>([]);

  useEffect(() => {
    let mounted = true;
    fetchTasks().then(data => {
      if (mounted && data.tasks) {
        setTasks(data.tasks);
      }
    });
    return () => { mounted = false; };
  }, []);

  return (
    <div className="w-full h-full flex flex-col p-8 overflow-y-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-light text-white mb-2">Active Tasks</h2>
          <p className="text-white/50 text-sm">2 pending objectives for today.</p>
        </div>
        <button className="flex items-center justify-center w-10 h-10 rounded-full bg-purple-500/20 text-purple-400 hover:bg-purple-500/40 transition-colors">
          <Plus size={20} />
        </button>
      </div>

      <div className="flex flex-col gap-3">
        {tasks.map(task => (
          <div 
            key={task.id} 
            className={`flex items-center gap-4 p-4 rounded-xl border transition-all ${
              task.status === 'done' 
                ? 'bg-transparent border-transparent opacity-50' 
                : 'bg-white/5 border-white/10 hover:border-purple-500/30'
            }`}
          >
            <button className="text-white/40 hover:text-purple-400 transition-colors">
              {task.status === 'done' ? <CheckCircle2 size={20} className="text-emerald-500" /> : <Circle size={20} />}
            </button>
            
            <div className="flex-1">
              <p className={`text-sm font-medium ${task.status === 'done' ? 'text-white/40 line-through' : 'text-white/90'}`}>
                {task.title}
              </p>
              <div className="flex items-center gap-3 mt-1">
                <span className="text-[10px] uppercase tracking-wider text-white/30">{task.context}</span>
                {task.priority === 'high' && (
                  <span className="text-[10px] uppercase tracking-wider text-purple-400 font-bold flex items-center gap-1">
                    <div className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse"></div> High Priority
                  </span>
                )}
              </div>
            </div>
            
            <div className="flex items-center gap-2 text-white/30 text-xs">
              <Clock size={12} />
              {task.time}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
