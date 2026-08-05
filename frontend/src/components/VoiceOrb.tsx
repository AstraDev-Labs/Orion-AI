import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error';

interface VoiceOrbProps {
  state?: VoiceState;
  className?: string;
  onClick?: () => void;
}

export function VoiceOrb({ state = 'idle', className, onClick }: VoiceOrbProps) {
  return (
    <div 
      className={twMerge('bh-overdrive-container', `state-${state}`, className)}
      onClick={onClick}
    >
      {/* Gravity wave background lines */}
      <div className="bh-gravity-grid"></div>

      {/* Distant massive nebula glow */}
      <div className="bh-ambient-glow"></div>

      {/* Organic, non-spinning volumetric halos */}
      <div className="bh-halo bh-halo-magenta"></div>
      <div className="bh-halo bh-halo-cyan"></div>

      {/* The sharp event horizon rim and absolute void */}
      <div className="bh-event-horizon-rim"></div>
      <div className="bh-void"></div>

      {/* Diagonal shooting light streaks pulling into the void */}
      <div className="bh-particle-system">
        <div className="bh-particle p1"></div>
        <div className="bh-particle p2"></div>
        <div className="bh-particle p3"></div>
        <div className="bh-particle p4"></div>
      </div>

      {/* The ultra-wide horizontal lens flare */}
      <div className="bh-lens-flare"></div>
    </div>
  );
}
