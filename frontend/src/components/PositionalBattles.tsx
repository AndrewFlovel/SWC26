import { useI18n } from '../i18n';
import type { LineupAnalysis } from '../types';

interface Props {
  analysis: LineupAnalysis;
  homeTeam: string;
  awayTeam: string;
}

export default function PositionalBattles({ analysis, homeTeam, awayTeam }: Props) {
  const { t } = useI18n();
  const fsiColor = analysis.fsi >= 0.5 ? '#7ddf8f' : '#ff7b5f';

  return (
    <div>
      <div className="fsi-summary">
        <div className="fsi-stat">
          <span>{t('formationStrength')}</span>
          <b style={{ color: fsiColor }}>{(analysis.fsi * 100).toFixed(1)}%</b>
        </div>
        <div className="fsi-stat">
          <span>{t('pressingIntensity')} · {homeTeam}</span>
          <b>{analysis.pis_home.toFixed(2)}</b>
        </div>
        <div className="fsi-stat">
          <span>{t('pressingIntensity')} · {awayTeam}</span>
          <b>{analysis.pis_away.toFixed(2)}</b>
        </div>
      </div>

      <table className="battle-table">
        <thead>
          <tr>
            <th>{t('battle')}</th>
            <th>{t('attacker')}</th>
            <th>{t('pms')}</th>
            <th>{t('defender')}</th>
            <th>{t('favored')}</th>
          </tr>
        </thead>
        <tbody>
          {analysis.positional_battles.map((b, i) => {
            const favColor = b.favored === 'home' ? '#7ddf8f' : '#ff7b5f';
            const teamName = b.side === 'home' ? homeTeam : awayTeam;
            return (
              <tr key={`${b.side}-${b.attacker}-${i}`}>
                <td>
                  <span className="side-chip" data-side={b.side}>
                    {b.attacker_position} ↔ {b.defender_position ?? '—'}
                  </span>
                </td>
                <td>
                  {b.attacker} <span className="muted">({b.attacker_age})</span>{' '}
                  <span className="muted">{b.attacker_pps.toFixed(2)}</span>
                  <span className="side-team">{teamName}</span>
                </td>
                <td>
                  <span className="pms-num">{(b.pms * 100).toFixed(0)}%</span>
                  <span className="qual-bar">
                    <i style={{ width: `${b.pms * 100}%` }} />
                  </span>
                </td>
                <td>
                  {b.defender ?? '—'}{' '}
                  {b.defender_age != null && (
                    <span className="muted">({b.defender_age})</span>
                  )}{' '}
                  {b.defender_pps != null && (
                    <span className="muted">{b.defender_pps.toFixed(2)}</span>
                  )}
                </td>
                <td style={{ color: favColor, fontWeight: 600 }}>
                  {b.favored === 'home' ? t('favoredHome') : t('favoredAway')}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
