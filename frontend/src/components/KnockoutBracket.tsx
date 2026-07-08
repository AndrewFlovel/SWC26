import { useEffect, useMemo, useState } from 'react';
import {
  fetchBracketProjection,
  fetchKnockoutSim,
  triggerScrape,
} from '../api/client';
import { useI18n, type TranslationKey } from '../i18n';
import type {
  BracketRound,
  BracketTie,
  Fixture,
  KnockoutSimRow,
  Team,
} from '../types';
import { flag } from '../types';
import MatchAnalysis from './MatchAnalysis';

const ROUND_ORDER: BracketRound[] = ['R32', 'R16', 'QF', 'SF', 'F'];

// Refresh the played results once per browser session: the bracket must be
// projected from everything played up to now, but a language switch or a
// remount should not re-hit the external source.
let scrapedThisSession = false;

const ROUND_LABEL: Record<BracketRound, TranslationKey> = {
  R32: 'roundOf32',
  R16: 'roundOf16',
  QF: 'quarterfinal',
  SF: 'semifinal',
  F: 'finalRound',
  '3P': 'thirdPlace',
};

/** Synthesize a neutral-venue fixture so a tie can reuse the prediction modal. */
function neutralFixture(
  match: number,
  home: string,
  away: string,
  roundName: string,
): Fixture {
  return {
    id: `m${match}`,
    group: roundName,
    matchday: 0,
    date: '',
    home,
    away,
    home_team_host: null,
    venue: {
      id: 'neutral',
      stadium: roundName,
      city: 'Neutral venue',
      country: '',
      altitude_m: 0,
      heat_index: 0,
      wbgt_score: 0,
      notes: '',
    },
  };
}

/** A side's cell value: real score (with penalties) when final, else win %. */
function sideScore(goals: number | null, pens: number | null, pct: number): string {
  if (goals === null) return `${pct}%`;
  return pens === null ? `${goals}` : `${goals} (${pens})`;
}

function TieCard({ tie, onClick }: { tie: BracketTie; onClick: () => void }) {
  const { t } = useI18n();

  // Pending: the R32 slot (or an upstream tie) has not been scraped yet.
  if (tie.status === 'pending') {
    return (
      <div className="bracket-tie bracket-tie-pending">
        <span className="bt-side">
          <span className="bt-team">{t('bracketPending')}</span>
        </span>
        <span className="bt-side">
          <span className="bt-team">{t('bracketPending')}</span>
        </span>
      </div>
    );
  }

  const homeWins = tie.winner === tie.home;
  const isFinal = tie.status === 'final';
  const pHome = Math.round((tie.p_home ?? 0) * 100);
  const pAway = Math.round((tie.p_away ?? 0) * 100);
  const homeCell = isFinal
    ? sideScore(tie.goals_home, tie.pens_home, pHome)
    : `${pHome}%`;
  const awayCell = isFinal
    ? sideScore(tie.goals_away, tie.pens_away, pAway)
    : `${pAway}%`;
  return (
    <button
      type="button"
      className={`bracket-tie ${tie.source === 'scraped' ? 'bracket-tie-real' : ''}`}
      onClick={onClick}
    >
      {tie.source === 'scraped' && (
        <span className="bt-badge">{t(isFinal ? 'bracketFinal' : 'bracketDrawn')}</span>
      )}
      <span className={`bt-side ${homeWins ? 'bt-win' : ''}`}>
        <span className="bt-team">
          {flag(tie.home ?? '')} {tie.home}
        </span>
        <span className="bt-pct">{homeCell}</span>
      </span>
      <span className={`bt-side ${!homeWins ? 'bt-win' : ''}`}>
        <span className="bt-team">
          {flag(tie.away ?? '')} {tie.away}
        </span>
        <span className="bt-pct">{awayCell}</span>
      </span>
    </button>
  );
}

export default function KnockoutBracket({ teams }: { teams: Record<string, Team> }) {
  const { t } = useI18n();
  const [ties, setTies] = useState<BracketTie[] | null>(null);
  const [odds, setOdds] = useState<KnockoutSimRow[] | null>(null);
  const [nSims, setNSims] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<BracketTie | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // Scrape everything played up to now FIRST, so the projection and the
      // simulation below start from the freshest real results. Best-effort:
      // a failed scrape must never block the predictions.
      if (!scrapedThisSession) {
        setRefreshing(true);
        try {
          await triggerScrape();
        } catch {
          /* offline / gated source — predict from what is stored */
        }
        scrapedThisSession = true;
        if (!cancelled) setRefreshing(false);
      }
      if (cancelled) return;
      fetchBracketProjection()
        .then((r) => !cancelled && setTies(r.ties))
        .catch((e: unknown) =>
          !cancelled && setError(e instanceof Error ? e.message : t('knockoutFailed')),
        );
      fetchKnockoutSim()
        .then((r) => {
          if (!cancelled) {
            setOdds(r.table);
            setNSims(r.n_sims);
          }
        })
        .catch((e: unknown) =>
          !cancelled && setError(e instanceof Error ? e.message : t('knockoutFailed')),
        );
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const byRound = useMemo(() => {
    const map: Record<string, BracketTie[]> = {};
    for (const tie of ties ?? []) (map[tie.round] ??= []).push(tie);
    return map;
  }, [ties]);

  const oddsRows = (odds ?? []).filter((r) => r.reach_r16 > 0);

  if (error) return <div className="error-box">{error}</div>;

  // A tie is openable only when both real teams are known and loaded.
  const openable = (tie: BracketTie) =>
    tie.status !== 'pending' && !!tie.home && !!tie.away &&
    !!teams[tie.home] && !!teams[tie.away];

  return (
    <>
      <h2 className="section-title">{t('bracketTitle')}</h2>
      <div className="panel" style={{ marginBottom: 22 }}>
        <p className="bracket-desc">{t('bracketDesc')}</p>
        {refreshing && (
          <div className="bracket-refresh">
            {t('bracketRefreshing')} <span className="loading-pulse" />
          </div>
        )}
        {!ties ? (
          <span className="loading-pulse" />
        ) : (
          <div className="bracket">
            {ROUND_ORDER.map((round) => (
              <div className="bracket-col" key={round}>
                <div className="bracket-round-label">{t(ROUND_LABEL[round])}</div>
                {(byRound[round] ?? []).map((tie) => (
                  <TieCard
                    key={tie.match}
                    tie={tie}
                    onClick={() => openable(tie) && setSelected(tie)}
                  />
                ))}
                {round === 'F' &&
                  (byRound['3P'] ?? []).map((tie) => (
                    <div key={tie.match} className="bracket-third">
                      <div className="bracket-round-label">{t('thirdPlace')}</div>
                      <TieCard
                        tie={tie}
                        onClick={() => openable(tie) && setSelected(tie)}
                      />
                    </div>
                  ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <h2 className="section-title">{t('deepRunTitle', { n: nSims })}</h2>
      <div className="panel">
        {!odds ? (
          <span className="loading-pulse" />
        ) : oddsRows.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
            {t('awaitingDraw')}
          </div>
        ) : (
          <table className="sim-table">
            <thead>
              <tr>
                <th>{t('team')}</th>
                <th>{t('reachR16')}</th>
                <th>{t('reachQf')}</th>
                <th>{t('reachSf')}</th>
                <th>{t('reachFinal')}</th>
                <th>{t('champion')}</th>
              </tr>
            </thead>
            <tbody>
              {oddsRows.map((r) => (
                <tr key={r.team}>
                  <td>
                    {flag(r.team)} {r.team}
                  </td>
                  <td>{r.reach_r16.toFixed(1)}%</td>
                  <td>{r.reach_qf.toFixed(1)}%</td>
                  <td>{r.reach_sf.toFixed(1)}%</td>
                  <td>{r.reach_final.toFixed(1)}%</td>
                  <td style={{ color: 'var(--gold)', fontWeight: 600 }}>
                    {r.champion.toFixed(1)}%
                    <span className="qual-bar">
                      <i style={{ width: `${r.champion}%` }} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && selected.home && selected.away &&
        teams[selected.home] && teams[selected.away] && (
        <MatchAnalysis
          fixture={neutralFixture(
            selected.match,
            selected.home,
            selected.away,
            t(ROUND_LABEL[selected.round]),
          )}
          teams={teams}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
