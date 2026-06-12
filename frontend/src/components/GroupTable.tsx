import { useEffect, useState } from 'react';
import { fetchGroupSim } from '../api/client';
import { useI18n } from '../i18n';
import type { GroupSimRow } from '../types';
import { flag } from '../types';

export default function GroupTable({ group }: { group: string }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<GroupSimRow[] | null>(null);
  const [played, setPlayed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    fetchGroupSim(group)
      .then((resp) => {
        if (!cancelled) {
          setRows(resp.table);
          setPlayed(resp.played ?? 0);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t('simFailed'));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [group, t]);

  if (error) return <div className="error-box">{error}</div>;

  return (
    <div className="panel">
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 13, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--blood)', marginBottom: 14 }}>
        {t('groupTableTitle', { g: group })}
        {!rows && <span className="loading-pulse" />}
      </h3>
      {played > 0 && (
        <div className="badge host" style={{ display: 'inline-block', marginBottom: 12 }}>
          ⚽ {t('oddsConditioned', { n: played })}
        </div>
      )}
      <table className="sim-table">
        <thead>
          <tr>
            <th>{t('team')}</th>
            <th>{t('winGroup')}</th>
            <th>{t('second')}</th>
            <th>{t('third')}</th>
            <th>{t('avgPts')}</th>
            <th>{t('top2')}</th>
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
          {!rows && (
            <tr>
              <td colSpan={6} style={{ color: 'var(--text-dim)' }}>
                {t('simulating')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
