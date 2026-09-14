import { useEffect, useState } from 'react';
import { fetchSavingsSummary } from '../api';

/** Right-rail "Avoided this month" — real total from /v1/savings, same source as Reckoning. */
export function AvoidedPanel() {
  const [dollars, setDollars] = useState<number | null>(null);

  useEffect(() => {
    fetchSavingsSummary()
      .then((s) => setDollars(s.per_provider.reduce((a, p) => a + p.total_cost, 0)))
      .catch(() => {});
  }, []);

  return (
    <div
      className="holo-panel"
      style={{ padding: '13px 14px', background: 'linear-gradient(180deg, rgba(90,59,10,0.3), rgba(20,18,15,0.5))' }}
    >
      <div className="holo-kicker" style={{ marginBottom: 8 }}>
        Avoided this session
      </div>
      <div style={{ fontFamily: 'var(--font-heading)', fontWeight: 300, fontSize: 32, color: 'var(--color-accent-300)' }}>
        {dollars === null ? '—' : `$${dollars.toFixed(2)}`}
      </div>
    </div>
  );
}

export default AvoidedPanel;
