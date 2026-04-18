import React from 'react';
import { motion } from 'framer-motion';

const ArcReactor = ({ isListening, intensity = 0 }) => {
  return (
    <div className="relative w-96 h-96 flex items-center justify-center">
      {/* Outer Tech Ring - Rotating */}
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        className="absolute inset-0 border-2 border-dashed border-cyan-500/30 rounded-full"
      />
      
      {/* Secondary Pulse Ring */}
      <motion.div
        animate={{ 
          scale: isListening ? [1, 1.05 + intensity, 1] : [1, 1.02, 1],
          opacity: isListening ? [0.4, 0.8, 0.4] : [0.2, 0.4, 0.2]
        }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        className="absolute inset-4 border-4 border-cyan-400/20 rounded-full shadow-[0_0_30px_rgba(34,211,238,0.2)]"
      />

      {/* The Core */}
      <div className="relative w-48 h-48 rounded-full bg-black flex items-center justify-center border border-cyan-500/50 shadow-[0_0_50px_rgba(34,211,238,0.3)]">
        {/* Core Glow */}
        <motion.div
          animate={{ 
            opacity: isListening ? [0.3, 0.6, 0.3] : 0.2,
            scale: isListening ? [1, 1.1, 1] : 1
          }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="absolute inset-4 rounded-full bg-cyan-400/20 blur-xl"
        />
        
        {/* Inner Tech Graphics */}
        <div className="absolute inset-6 border border-cyan-500/20 rounded-full animate-pulse" />
        <div className="absolute inset-10 border-2 border-dashed border-cyan-500/10 rounded-full rotate-45" />
        
        {/* ORION Text */}
        <motion.div 
          animate={{ opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 3, repeat: Infinity }}
          className="z-10 font-mono text-2xl font-bold text-cyan-400 tracking-[0.2em] drop-shadow-[0_0_8px_rgba(34,211,238,0.8)]"
        >
          ORION
        </motion.div>
      </div>

      {/* Decorative Accents */}
      {[0, 90, 180, 270].map((angle) => (
        <div 
          key={angle}
          className="absolute w-1 h-8 bg-cyan-500/40"
          style={{ 
            transform: `rotate(${angle}deg) translateY(-200px)`,
            boxShadow: '0 0 10px rgba(34, 211, 238, 0.5)'
          }}
        />
      ))}
    </div>
  );
};

export default ArcReactor;
