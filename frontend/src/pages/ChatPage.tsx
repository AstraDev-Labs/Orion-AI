import { useState } from 'react';
import { ChatArea } from '../components/Chat/ChatArea';
import { useAppStore } from '../lib/store';
import { VoiceOrb } from '../components/VoiceOrb';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings as SettingsIcon, Maximize, Minimize } from 'lucide-react';
import { LeftSidebar } from '../components/Dashboard/LeftSidebar';
import { RightSidebar } from '../components/Dashboard/RightSidebar';

// Views
import { DailyInsight } from '../components/Dashboard/Views/DailyInsight';
import { ConceptNodes } from '../components/Dashboard/Views/ConceptNodes';
import { Tasks } from '../components/Dashboard/Views/Tasks';
import { KnowledgeMap } from '../components/Dashboard/Views/KnowledgeMap';
import { SettingsView } from '../components/Dashboard/Views/SettingsView';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatPage() {
  const { streamState, activeTab, setActiveTab } = useAppStore();
  const [isExpanded, setIsExpanded] = useState(false);

  const voiceState = streamState.isStreaming ? 'thinking' : 'idle';

  // Determine what to render in the center column
  const renderCenterView = () => {
    switch (activeTab) {
      case 'search': return <ChatArea />;
      case 'insight': return <DailyInsight />;
      case 'nodes': return <ConceptNodes />;
      case 'tasks': return <Tasks />;
      case 'map': return <KnowledgeMap />;
      case 'settings': return <SettingsView />;
      default: return <ChatArea />;
    }
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden relative bg-[#05020a]">
      {/* Background Ambience */}
      <div className="absolute inset-0 pointer-events-none z-0">
        <div className="bg-stars" />
      </div>

      {/* Top Bar */}
      <div className="absolute top-0 w-full h-16 flex items-center justify-between px-8 z-50 pointer-events-auto">
        <div className="text-white/60 font-medium tracking-widest text-sm flex items-center gap-2">
          <div className="w-4 h-4 rounded-full border border-purple-500/50 flex items-center justify-center">
            <div className="w-1.5 h-1.5 bg-purple-400 rounded-full glow-text-purple"></div>
          </div>
          ORION
        </div>
        <button 
          onClick={() => setActiveTab('settings')}
          className="text-white/40 hover:text-white transition-colors cursor-pointer p-2"
        >
          <SettingsIcon size={20} />
        </button>
      </div>

      {/* The Black Hole Horizon (Always at the bottom) */}
      <div className="absolute inset-0 z-10 pointer-events-none overflow-hidden">
        <VoiceOrb state={voiceState} />
      </div>

      {/* Main Content Area */}
      <div className="absolute inset-0 z-20 flex flex-col items-center justify-end pb-10 pt-24 px-8 pointer-events-none">
        
        {/* Hero Text (Fades out when dashboard expands) */}
        <AnimatePresence>
          {!isExpanded && (
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="flex-1 flex flex-col items-center justify-center text-center w-full max-w-4xl"
            >
              <h1 className="text-5xl font-light text-white mb-4 tracking-tight drop-shadow-2xl">
                {getGreeting()}
              </h1>
              <p className="text-lg text-white/50 font-light tracking-wide">
                Connect your core concepts with Orion. Never lose a fundamental insight.
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* The Glassmorphic Dashboard Panel */}
        <motion.div 
          layout
          initial={{ height: '50vh' }}
          animate={{ height: isExpanded ? '85vh' : '50vh' }}
          className="w-full max-w-6xl relative flex flex-row rounded-[2rem] hud-panel shadow-[0_40px_80px_rgba(0,0,0,0.8)] pointer-events-auto transition-shadow hover:shadow-[0_50px_100px_rgba(168,85,247,0.15)]"
        >
          {/* Dashboard Header / Window Controls */}
          <div className="absolute top-4 right-6 z-50">
            <button 
              onClick={() => setIsExpanded(!isExpanded)}
              className="p-2 text-white/30 hover:text-white/80 transition-colors cursor-pointer bg-white/5 rounded-md backdrop-blur-md border border-white/10"
            >
              {isExpanded ? <Minimize size={14} /> : <Maximize size={14} />}
            </button>
          </div>

          {/* 3-Column Layout */}
          <LeftSidebar />
          
          <div className="flex-1 overflow-hidden relative flex flex-col pt-4">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="w-full h-full"
              >
                {renderCenterView()}
              </motion.div>
            </AnimatePresence>
          </div>

          <RightSidebar />

        </motion.div>
      </div>
    </div>
  );
}
