import React from 'react';
import { motion } from 'framer-motion';
import { 
  BsMicFill, 
  BsMicMuteFill, 
  BsGearFill, 
  BsCameraVideoFill,
  BsCameraVideoOffFill,
  BsFillGrid3X3GapFill,
  BsHandIndexThumbFill,
  BsHandIndexThumb,
  BsArrowLeftRight
} from 'react-icons/bs';

const ControlDeck = ({ 
  isListening, 
  toggleMic, 
  toggleSettings, 
  isVideoOn,
  toggleCamera,
  isCameraFlipped,
  toggleFlip,
  isHandTrackingEnabled,
  toggleHandTracking,
  activeModules = []
}) => {
  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 w-fit z-50">
      <motion.div 
        initial={{ y: 100, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="flex items-center gap-6 px-8 py-4 bg-black/60 backdrop-blur-2xl border border-cyan-500/30 rounded-full shadow-[0_0_40px_rgba(0,0,0,0.8)]"
      >
        {/* Module Indicator Dots */}
        <div className="flex gap-1.5 mr-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className={`w-1.5 h-1.5 rounded-full ${activeModules.includes(i) ? 'bg-cyan-400' : 'bg-cyan-900 border border-cyan-500/30'}`} />
          ))}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-4">
          {/* Audio Core */}
          <ControlButton 
            icon={isListening ? <BsMicFill /> : <BsMicMuteFill />} 
            onClick={toggleMic}
            active={isListening}
            glow={isListening}
            label="Audio Core"
          />
          
          <div className="h-6 w-[1px] bg-cyan-500/10 mx-1" />

          {/* Vision Core (Camera) */}
          <div className="flex items-center gap-1">
            <ControlButton 
              icon={isVideoOn ? <BsCameraVideoFill /> : <BsCameraVideoOffFill />} 
              onClick={toggleCamera}
              active={isVideoOn}
              glow={isVideoOn}
              label="Vision Core"
            />
            {isVideoOn && (
              <ControlButton 
                icon={<BsArrowLeftRight />} 
                onClick={toggleFlip}
                active={isCameraFlipped}
                label="Flip Optical Axis"
                small
              />
            )}
          </div>

          {/* Gesture Core (Hand Tracking) */}
          <ControlButton 
            icon={isHandTrackingEnabled ? <BsHandIndexThumbFill /> : <BsHandIndexThumb />} 
            onClick={toggleHandTracking}
            active={isHandTrackingEnabled}
            glow={isHandTrackingEnabled}
            label="Gesture Input"
          />

          <div className="h-8 w-[1px] bg-cyan-500/20 mx-2" />
          
          <ControlButton 
            icon={<BsFillGrid3X3GapFill />} 
            onClick={() => {}} 
            label="Grid view"
          />
          <ControlButton 
            icon={<BsGearFill />} 
            onClick={toggleSettings}
            label="Settings"
          />
        </div>

        {/* Status Text */}
        <div className="ml-4 font-mono text-[10px] text-cyan-400/60 uppercase tracking-[0.2em] hidden md:block">
          System <span className="text-cyan-400">Autonomous</span>
        </div>
      </motion.div>
    </div>
  );
};

const ControlButton = ({ icon, onClick, active, glow, label, small }) => (
  <motion.button
    whileHover={{ scale: 1.1 }}
    whileTap={{ scale: 0.95 }}
    onClick={onClick}
    className={`rounded-full transition-all duration-300 relative group flex items-center justify-center
      ${small ? 'p-1.5 text-sm' : 'p-3 text-xl'}
      ${active ? 'bg-cyan-500/20 text-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.3)]' : 'bg-transparent text-cyan-700 hover:text-cyan-400'}`}
  >
    {glow && (
      <div className="absolute inset-0 rounded-full bg-cyan-400/20 blur animate-pulse" />
    )}
    <span className="relative z-10">{icon}</span>
    
    {/* Label / Tooltip */}
    <div className="absolute -top-12 left-1/2 -translate-x-1/2 px-3 py-1 bg-black/90 border border-cyan-500/30 rounded text-[9px] opacity-0 group-hover:opacity-100 transition-opacity uppercase tracking-widest pointer-events-none whitespace-nowrap z-50">
      {label}
    </div>
  </motion.button>
);

export default ControlDeck;
