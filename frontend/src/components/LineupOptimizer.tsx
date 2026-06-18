import { useState } from 'react';
import { fetchOptimalXi } from '../api/client';
import { useI18n } from '../i18n';
import type { XiCandidate } from '../types';
import { FORMATION_NAMES, ppsColor } from '../types';

type Side = 'home' | 'away';

interface Props {
  homeTeam: string;
  awayTeam: string;
  homeFormation: string;
  awayFormation: string;
  homeLineup: string[];
  awayLineup: string[];
  onApply: (side: Side, formation: string, lineup: string[]) => void;
}

export default function LineupOptimizer(props: Props) {
  const { t } = useI18n();
  const [side, setSide] = useState<Side>('home');
  const [formation, setFormation] = useState(props.homeFormation);
  const [candidates, setCandidates] = useState<XiCandidate[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = () => {
    const team = side === 'home' ? props.homeTeam : props.awayTeam;
    const opponent =
      side === 'home'
        ? { team: props.awayTeam, formation: props.awayFormation, lineup: props.awayLineup }
        : { team: props.homeTeam, formation: props.homeFormation, lineup: props.homeLineup };
    setLoading(true);
    setError(null);
    fetchOptimalXi({
      team,
      formation,
      opponent_team: opponent.team,
      opponent_formation: opponent.formation,
      opponent_lineup: opponent.lineup.length === 11 ? opponent.lineup : undefined,
    })
      .then((resp) => {
        setCandidates(resp.candidates);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'failed');
        setLoading(false);
      });
  };

  const optimizeTeam = side === 'home' ? props.homeTeam : props.awayTeam;

  return (
    <div className="optimizer">
      <div className="optimizer-controls">
        <div className="seg">
          {(['home', 'away'] as const).map((s) => (
            <button
              key={s}
              type="button"
              className={side === s ? 'on' : ''}
              onClick={() => {
                setSide(s);
                setFormation(s === 'home' ? props.homeFormation : props.awayFormation);
                setCandidates(null);
              }}
            >
              {s === 'home' ? props.homeTeam : props.awayTeam}
            </button>
          ))}
        </div>
        <label className="formation-pick">
          <span>{t('formation')}</span>
          <select value={formation} onChange={(e) => setFormation(e.target.value)}>
            {FORMATION_NAMES.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        <button type="button" className="scrape-btn" disabled={loading} onClick={run}>
          {loading ? t('crunchingPlayers') : t('findBestXi')}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="xi-candidates">
        {(candidates ?? []).map((c, i) => (
          <div className="xi-candidate" key={`${c.formation}-${i}`}>
            <div className="xi-head">
              <span className="xi-rank">#{i + 1}</span>
              <span className="xi-formation">{c.formation}</span>
              <span className="xi-fsi">
                {t('formationStrength')}: <b>{(c.fsi * 100).toFixed(1)}%</b>
              </span>
              <span className="xi-pis">{t('pressingIntensity')}: {c.pis.toFixed(2)}</span>
              <button
                type="button"
                className="apply-btn"
                onClick={() => props.onApply(side, c.formation, c.lineup.map((s) => s.player))}
              >
                {t('applyXi')}
              </button>
            </div>
            <div className="xi-grid">
              {c.lineup.map((s) => (
                <span className="xi-slot" key={s.slot}>
                  <span className="xi-pos">{s.position}</span>
                  <span className="xi-player">
                    {s.player} <span className="xi-age">({s.age})</span>
                  </span>
                  <span className="xi-pps" style={{ color: ppsColor(s.pps) }}>
                    {s.pps.toFixed(2)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        ))}
        {!candidates && !loading && (
          <div className="optimizer-hint">{t('bestXi')} · {optimizeTeam}</div>
        )}
      </div>
    </div>
  );
}
