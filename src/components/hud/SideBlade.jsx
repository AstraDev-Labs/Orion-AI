import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const SideBlade = ({ isOpen, side = 'left', title, children }) => {
  const isLeft = side === 'left';
  
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ x: isLeft ? -400 : 400, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: isLeft ? -400 : 400, opacity: 0 }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
          className={`fixed top-24 bottom-24 w-80 bg-black/40 backdrop-blur-xl border-y border-cyan-500/30 flex flex-col z-40
            ${isLeft ? 'left-0 border-r rounded-r-3xl' : 'right-0 border-l rounded-l-3xl'}`}
        >
          {/* Blade Header */}
          <div className={`p-4 border-b border-cyan-500/20 flex items-center justify-between
            ${isLeft ? 'flex-row' : 'flex-row-reverse'}`}>
            <h3 className="font-mono text-cyan-400 font-bold tracking-widest uppercase">
              {title}
            </h3>
            <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_5px_rgba(34,211,238,1)]" />
          </div>

          {/* Blade Content */}
          <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
            {children}
          </div>

          {/* Blade Footer Tech Detail */}
          <div className="h-2 bg-gradient-to-r from-transparent via-cyan-500/20 to-transparent" />
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default SideBlade;
