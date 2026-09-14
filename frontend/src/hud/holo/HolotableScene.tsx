import { useEffect, useRef } from 'react';
import './holo-stage.js';

export type HolotableActivity = 'idle' | 'listening' | 'thinking' | 'speaking';
export type HolotableLink = 'offline' | 'dialing' | 'handshake' | 'loading' | 'live' | 'lost';
export type AffectLabel = 'alert' | 'focused' | 'cautious' | 'warm' | 'confident' | 'steady';

// A CSS filter tint per real affect label (see core/affect.py) -- layered
// on top of the literal ported holo-stage.js rather than touching its own
// color logic, so the design source stays byte-for-byte unmodified. Subtle
// on purpose: this colors an existing real state, it doesn't repaint the
// scene into something new.
const AFFECT_FILTER: Record<AffectLabel, string> = {
  alert: 'saturate(1.35) hue-rotate(-8deg) brightness(1.05)',
  focused: 'saturate(1.15) brightness(1.02)',
  cautious: 'saturate(0.75) brightness(0.92)',
  warm: 'saturate(1.1) hue-rotate(6deg)',
  confident: 'saturate(1.1) brightness(1.05)',
  steady: 'none',
};

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'holo-stage': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>;
    }
  }
}

/**
 * Thin React wrapper around the design's own `holo-stage.js` custom element
 * -- the literal source file (fogged chamber, gyro cage, dust, bloom, pulse
 * animation), copied in unmodified rather than reimplemented, and driven by
 * real `activity`/`link` state instead of the design's mock enum.
 */
export function HolotableScene({
  activity,
  link = 'live',
  affect = 'steady',
}: {
  activity: HolotableActivity;
  link?: HolotableLink;
  affect?: AffectLabel;
}) {
  const elRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    elRef.current?.setAttribute('activity', activity);
  }, [activity]);

  useEffect(() => {
    elRef.current?.setAttribute('link', link);
  }, [link]);

  return (
    <holo-stage
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ref={elRef as any}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        filter: AFFECT_FILTER[affect],
        transition: 'filter 1.2s ease-out',
      }}
    />
  );
}

export default HolotableScene;
