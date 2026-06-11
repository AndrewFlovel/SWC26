import { useEffect, useState } from 'react';
import { fetchGroupSim } from '../api/client';
import type { GroupSimRow } from '../types';
import { flag } from '../types';

export default function GroupTable({ group }: { group: string }) {
  const [rows, setRows] = useState<GroupSimRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    fetchGroupSim(group)
      .then((resp) => {
        if (!cancelled) setRows(resp.table);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Simulation failed');
      });
    return () => {
      cancelled = true;
    };
  }, [group]);

  if (error) return <div className="error-box">{error}</div>;

  return (
    <div className="panel">
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 13, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--blood)', marginBottom: 14 }}>
        Group {group} — Monte Carlo qualification odds (3,000 runs)
        {!rows && <span className="loading-pulse" />}
      </h3>
      <table className="sim-table">
        <thead>
          <tr>
            <th>Team</th>
            <th>Win group</th>
            <th>2nd</th>
            <th>3rd</th>
            <th>Avg pts</th>
            <th>Top-2 qualify</th>
          </tr>
        </thead>
        <tbody>
          {(rows ?? []).map((r) => (
            <tr key={r.team}>
              <td>
                {flag(r.team)} {r.team}
              </td>
              <td>{r.win_group_pct.toFixed(1)}%</td>
              <td>{r.second_pct.toFixed(1)}%</td>
              <td>{r.third_pct.toFixed(1)}%</td>
              <td>{r.avg_points.toFixed(2)}</td>
              <td>
                {r.top2_pct.toFixed(1)}%
                <span className="qual-bar">
                  <i style={{ width: `${r.top2_pct}%` }} />
                </span>
              </td>
            </tr>
          ))}
          {!rows &&
            Array.from({ length: 4 }, (_, i) => (
              <tr key={i}>
                <td colSpan={6} style={{ color: 'var(--text-dim)' }}>
                  Simulating…
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
