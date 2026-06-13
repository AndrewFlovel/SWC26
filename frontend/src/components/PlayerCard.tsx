import { useI18n } from '../i18n';
import type { Player } from '../types';
import { POSITION_GROUP_COLOR, ppsColor } from '../types';

export default function PlayerCard({ player }: { player: Player }) {
  const { t } = useI18n();
  const groupColor = POSITION_GROUP_COLOR[player.position_group] ?? 'var(--text-dim)';
  return (
    <div className="player-card">
      <div className="player-card-head">
        <span
          className="pos-chip"
          style={{ borderColor: groupColor, color: groupColor }}
        >
          {player.position}
        </span>
        <span className="player-name" title={player.name}>
          {player.name}
        </span>
        {player.injury_flag && <span className="injury-dot" title="injury" />}
      </div>
      <div className="player-meta">
        {t('age')} {player.age} · {player.club}
      </div>
      <div className="pps-bar-row">
        <span className="pps-label">{t('pps')}</span>
        <div className="pps-track">
          <div
            className="pps-fill"
            style={{ width: `${player.pps * 100}%`, background: ppsColor(player.pps) }}
          />
        </div>
        <span className="pps-val" style={{ color: ppsColor(player.pps) }}>
          {player.pps.toFixed(2)}
        </span>
      </div>
    </div>
  );
}
