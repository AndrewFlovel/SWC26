import { motion } from 'framer-motion';
import { useI18n } from '../i18n';
import type { Fixture } from '../types';
import { flag } from '../types';

interface Props {
  fixtures: Fixture[];
  onSelect: (fixture: Fixture) => void;
}

function VenueBadges({ fixture }: { fixture: Fixture }) {
  const { t } = useI18n();
  const { venue } = fixture;
  return (
    <div className="venue-row">
      <span className="badge">
        {venue.stadium} · {venue.city}
      </span>
      <span className="badge">MD{fixture.matchday} · {fixture.date}</span>
      {venue.altitude_m >= 1000 && (
        <span className="badge altitude">⛰ {venue.altitude_m}m</span>
      )}
      {venue.heat_index >= 1.2 && (
        <span className="badge hot">🔥 WBGT {venue.wbgt_score.toFixed(0)}</span>
      )}
      {fixture.home_team_host && (
        <span className="badge host">
          {t('hostBadge', { team: fixture.home_team_host })}
        </span>
      )}
    </div>
  );
}

export default function MatchList({ fixtures, onSelect }: Props) {
  const { t } = useI18n();
  return (
    <div className="match-grid">
      {fixtures.map((f, i) => (
        <motion.button
          type="button"
          className="match-card"
          key={f.id}
          onClick={() => onSelect(f)}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
        >
          <div className="meta">
            <span>
              {t('group')} {f.group} · {t('match')} {f.id}
            </span>
            <span>{t('analyze')}</span>
          </div>
          <div className="teams">
            <span className="team-side">
              <span className="flag">{flag(f.home)}</span>
              <span className="name">{f.home}</span>
            </span>
            <span className="vs">VS</span>
            <span className="team-side" style={{ justifyContent: 'flex-end' }}>
              <span className="name">{f.away}</span>
              <span className="flag">{flag(f.away)}</span>
            </span>
          </div>
          <VenueBadges fixture={f} />
        </motion.button>
      ))}
    </div>
  );
}
