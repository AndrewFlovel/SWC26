import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  analyzeLineup,
  fetchFormations,
  fetchOptimalXi,
  scrapePlayers,
} from '../api/client';
import { useI18n } from '../i18n';
import type {
  Fixture,
  FormationMap,
  LineupAnalysis,
  PlayerSquadResponse,
  TeamSquad,
} from '../types';
import { flag } from '../types';
import FormationView from './FormationView';
import LineupOptimizer from './LineupOptimizer';
import PlayerCard from './PlayerCard';
import PositionalBattles from './PositionalBattles';

type Tab = 'squad' | 'formation' | 'battles' | 'optimizer';
const DEFAULT_FORMATION = '4-3-3';

function SquadColumn({ squad }: { squad: TeamSquad }) {
  const { t } = useI18n();
  const sourceKey = `src${squad.source.charAt(0).toUpperCase()}${squad.source.slice(1)}` as
    | 'srcScraped'
    | 'srcCached'
    | 'srcSeed'
    | 'srcUnavailable';
  const sorted = [...squad.players].sort((a, b) => b.pps - a.pps);
  return (
    <div className="squad-col">
      <div className="squad-col-head">
        <h4>
          {flag(squad.team)} {squad.team}
        </h4>
        <span className={`badge src-${squad.source}`}>{t(sourceKey)}</span>
      </div>
      {sorted.map((p) => (
        <PlayerCard key={p.name} player={p} />
      ))}
    </div>
  );
}

export default function PlayerAnalysis({
  fixture,
  onClose,
}: {
  fixture: Fixture;
  onClose: () => void;
}) {
  const { t } = useI18n();

  const [live, setLive] = useState(true);
  const [squads, setSquads] = useState<PlayerSquadResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formations, setFormations] = useState<FormationMap | null>(null);
  const [tab, setTab] = useState<Tab>('squad');

  const [homeFormation, setHomeFormation] = useState(DEFAULT_FORMATION);
  const [awayFormation, setAwayFormation] = useState(DEFAULT_FORMATION);
  const [homeLineup, setHomeLineup] = useState<string[]>([]);
  const [awayLineup, setAwayLineup] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<LineupAnalysis | null>(null);

  const fetchedKey = useRef<string | null>(null);

  const bothValid =
    !!squads &&
    squads.home.players.length >= 11 &&
    squads.away.players.length >= 11;

  // Fetch the formation templates once.
  useEffect(() => {
    fetchFormations()
      .then(setFormations)
      .catch(() => setFormations(null));
  }, []);

  // Scrape both squads on open (and whenever the live toggle flips). The ref
  // dedupe survives React StrictMode's mount/unmount/remount without dropping
  // the in-flight request (no cleanup-cancel, which would strand it).
  useEffect(() => {
    const key = `${fixture.id}:${live}`;
    if (fetchedKey.current === key) return;
    fetchedKey.current = key;
    setLoading(true);
    setError(null);
    setSquads(null);
    setAnalysis(null);
    scrapePlayers(fixture.id, live)
      .then((resp) => {
        setSquads(resp);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'scrape failed');
        setLoading(false);
      });
  }, [fixture.id, live]);

  // Replace one side's lineup with its optimal XI for the given formation.
  const applyOptimal = useCallback(
    (side: 'home' | 'away', formation: string) => {
      if (!squads) return;
      const team = side === 'home' ? squads.home.team : squads.away.team;
      fetchOptimalXi({ team, formation })
        .then((resp) => {
          const names = resp.candidates[0]?.lineup.map((s) => s.player) ?? [];
          if (side === 'home') {
            setHomeFormation(formation);
            setHomeLineup(names);
          } else {
            setAwayFormation(formation);
            setAwayLineup(names);
          }
        })
        .catch(() => {
          /* keep current lineup on failure */
        });
    },
    [squads],
  );

  // Seed both sides with their optimal XI once squads are available.
  useEffect(() => {
    if (!bothValid) return;
    applyOptimal('home', DEFAULT_FORMATION);
    applyOptimal('away', DEFAULT_FORMATION);
  }, [bothValid, applyOptimal]);

  // Recompute the matchup whenever either lineup or formation changes.
  useEffect(() => {
    if (!bothValid || homeLineup.length !== 11 || awayLineup.length !== 11) return;
    let cancelled = false;
    analyzeLineup({
      home_team: squads!.home.team,
      away_team: squads!.away.team,
      home_formation: homeFormation,
      away_formation: awayFormation,
      home_lineup: homeLineup,
      away_lineup: awayLineup,
    })
      .then((a) => {
        if (!cancelled) setAnalysis(a);
      })
      .catch(() => {
        if (!cancelled) setAnalysis(null);
      });
    return () => {
      cancelled = true;
    };
  }, [squads, bothValid, homeFormation, awayFormation, homeLineup, awayLineup]);

  const applyCandidate = useCallback(
    (side: 'home' | 'away', formation: string, lineup: string[]) => {
      if (side === 'home') {
        setHomeFormation(formation);
        setHomeLineup(lineup);
      } else {
        setAwayFormation(formation);
        setAwayLineup(lineup);
      }
      setTab('formation');
    },
    [],
  );

  const unavailable = useMemo(() => {
    if (!squads) return [];
    const out: string[] = [];
    if (squads.home.players.length < 11) out.push(squads.home.team);
    if (squads.away.players.length < 11) out.push(squads.away.team);
    return out;
  }, [squads]);

  const tabs: { id: Tab; label: string; needsData: boolean }[] = [
    { id: 'squad', label: t('tabSquad'), needsData: false },
    { id: 'formation', label: t('tabFormation'), needsData: true },
    { id: 'battles', label: t('tabBattles'), needsData: true },
    { id: 'optimizer', label: t('tabOptimizer'), needsData: true },
  ];

  const analysisReady = bothValid && formations && analysis;

  return (
    <AnimatePresence>
      <motion.div
        className="analysis-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <motion.div
          className="analysis-modal"
          initial={{ opacity: 0, y: 30, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 30, scale: 0.97 }}
          transition={{ type: 'spring', stiffness: 220, damping: 26 }}
        >
          <div className="analysis-head">
            <h2>
              {flag(fixture.home)} {fixture.home}
              <span className="vs">VS</span>
              {flag(fixture.away)} {fixture.away}
              {loading && <span className="loading-pulse" />}
            </h2>
            <div className="analysis-head-actions">
              <button
                type="button"
                className={`heat-toggle ${live ? 'on' : ''}`}
                onClick={() => setLive((v) => !v)}
                title={t('liveScrape')}
              >
                {t('liveScrape')}
              </button>
              <button
                type="button"
                className="close"
                onClick={onClose}
                aria-label={t('close')}
              >
                ✕
              </button>
            </div>
          </div>
          <div className="analysis-sub">
            {t('playerAnalysisTitle')} · {fixture.venue.stadium}, {fixture.venue.city}
          </div>

          {loading && (
            <div className="player-loading">
              <span className="loading-pulse" /> {t('runningScraper')}
            </div>
          )}
          {error && <div className="error-box">{error}</div>}

          {squads && (
            <>
              <div className="player-tabs">
                {tabs.map((tb) => (
                  <button
                    key={tb.id}
                    type="button"
                    className={tab === tb.id ? 'on' : ''}
                    disabled={tb.needsData && !bothValid}
                    onClick={() => setTab(tb.id)}
                  >
                    {tb.label}
                  </button>
                ))}
              </div>

              {unavailable.length > 0 && (
                <div className="scrape-banner fallback">
                  {unavailable.map((team) => t('noSquadData', { team })).join(' ')}
                </div>
              )}

              {tab === 'squad' && (
                <div className="squad-cols">
                  <SquadColumn squad={squads.home} />
                  <SquadColumn squad={squads.away} />
                </div>
              )}

              {tab === 'formation' &&
                (analysisReady ? (
                  <FormationView
                    formations={formations}
                    home={squads.home}
                    away={squads.away}
                    homeFormation={homeFormation}
                    awayFormation={awayFormation}
                    homeLineup={homeLineup}
                    awayLineup={awayLineup}
                    heatmap={analysis.dominance_heatmap}
                    onHomeFormation={(f) => applyOptimal('home', f)}
                    onAwayFormation={(f) => applyOptimal('away', f)}
                  />
                ) : (
                  <div className="player-loading">{t('crunchingPlayers')}</div>
                ))}

              {tab === 'battles' &&
                (analysis ? (
                  <PositionalBattles
                    analysis={analysis}
                    homeTeam={squads.home.team}
                    awayTeam={squads.away.team}
                  />
                ) : (
                  <div className="player-loading">{t('crunchingPlayers')}</div>
                ))}

              {tab === 'optimizer' && bothValid && (
                <LineupOptimizer
                  homeTeam={squads.home.team}
                  awayTeam={squads.away.team}
                  homeFormation={homeFormation}
                  awayFormation={awayFormation}
                  homeLineup={homeLineup}
                  awayLineup={awayLineup}
                  onApply={applyCandidate}
                />
              )}
            </>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
