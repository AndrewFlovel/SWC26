import { useI18n } from '../i18n';
import type { AdjustedTeam } from '../types';
import { flag } from '../types';

const signed = (v: number, digits: number) =>
  `${v > 0 ? '+' : ''}${v.toFixed(digits)}`;

const deltaColor = (v: number) =>
  v > 0 ? '#7ddf8f' : v < 0 ? '#ff9d9d' : 'var(--text-dim)';

export default function MetricsPanel({ metrics }: { metrics: AdjustedTeam[] }) {
  const { t } = useI18n();
  const rows = metrics.filter((m) => m.matches_played > 0);

  return (
    <div className="panel" style={{ marginTop: 22 }}>
      <h3 className="panel-title">{t('metricsTitle')}</h3>
      {rows.length === 0 ? (
        <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          {t('noAdjustments')}
        </div>
      ) : (
        <table className="sim-table">
          <thead>
            <tr>
              <th>{t('team')}</th>
              <th>{t('group')}</th>
              <th>{t('matchesPlayed')}</th>
              <th>{t('baseElo')}</th>
              <th>{t('adjustedElo')}</th>
              <th>{t('eloDelta')}</th>
              <th>{t('formDelta')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.team}>
                <td>
                  {flag(m.team)} {m.team}
                </td>
                <td>{m.group}</td>
                <td>{m.matches_played}</td>
                <td>{m.base_elo.toFixed(0)}</td>
                <td>{m.adjusted_elo.toFixed(0)}</td>
                <td style={{ color: deltaColor(m.elo_delta), fontWeight: 600 }}>
                  {signed(m.elo_delta, 1)}
                </td>
                <td style={{ color: deltaColor(m.form_delta) }}>
                  {signed(m.form_delta, 3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
