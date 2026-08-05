import { Search, Compass, Share2, CheckSquare, Map, Calendar, Settings } from 'lucide-react';
import { useAppStore } from '../../lib/store';

export function LeftSidebar() {
  const { activeTab, setActiveTab } = useAppStore();

  const navItems = [
    { id: 'search', icon: Search, label: 'Universal Search' },
    { id: 'insight', icon: Calendar, label: 'Daily Insight' },
    { id: 'nodes', icon: Share2, label: 'Concept Nodes' },
    { id: 'tasks', icon: CheckSquare, label: 'Tasks' },
    { id: 'map', icon: Map, label: 'Knowledge Map' },
    { id: 'settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="w-[240px] flex-shrink-0 h-full flex flex-col p-4 border-r border-white/5 border-dashed">
      {/* Search Bar */}
      <div className="relative mb-8 mt-2 px-2">
        <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/40" />
        <input 
          type="text" 
          placeholder="Search anything..." 
          className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-10 pr-4 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:bg-white/10 transition-colors"
        />
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1.5 px-2">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          const Icon = item.icon;
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all group ${
                isActive 
                  ? 'bg-purple-500/10 text-purple-300 border border-purple-500/20 shadow-[inset_0_0_20px_rgba(168,85,247,0.1)]' 
                  : 'text-white/50 hover:bg-white/5 hover:text-white/90 border border-transparent'
              }`}
            >
              <Icon 
                size={16} 
                className={`${isActive ? 'text-purple-400' : 'text-white/40 group-hover:text-white/70'} transition-colors`} 
              />
              <span className="text-sm font-medium tracking-wide">{item.label}</span>
              {isActive && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-purple-400 shadow-[0_0_10px_rgba(168,85,247,0.8)] glow-text-purple" />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
