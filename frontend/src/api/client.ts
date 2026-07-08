import { useEffect, useRef, useState } from 'react';
import type {
  AdjustedTeam,
  BenchmarkResponse,
  BracketProjection,
  Fixture,
  FormationMap,
  KnockoutSimResponse,
  LineupAnalysis,
  LineupJobStatus,
  MatchResult,
  OptimalXiResponse,
  PlayerSquadResponse,
  PredictRequest,
  Prediction,
  ResultIn,
  ScrapeResponse,
  Team,
  TeamAdjustment,
  TeamAdjustmentIn,
  TeamSquad,
} from '../types';

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8001';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const fetchTeams = () => request<Team[]>('/api/teams');
export const fetchMatches = () => request<Fixture[]>('/api/matches');

export const fetchPrediction = (req: PredictRequest, signal?: AbortSignal) =>
  request<Prediction>('/api/predict', {
    method: 'POST',
    body: JSON.stringify(req),
    signal,
  });

export const fetchKnockoutSim = (nSims = 4000, useResults = true) =>
  request<KnockoutSimResponse>('/api/simulate/knockout', {
    method: 'POST',
    body: JSON.stringify({ n_sims: nSims, use_results: useResults }),
  });

export const fetchBracketProjection = (useResults = true) =>
  request<BracketProjection>(
    `/api/bracket/projection?use_results=${useResults}`,
  );

export const fetchResults = () => request<MatchResult[]>('/api/results');

export const saveResult = (fixtureId: string, body: ResultIn) =>
  request<MatchResult>(`/api/results/${fixtureId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const deleteResult = (fixtureId: string) =>
  request<{ status: string }>(`/api/results/${fixtureId}`, { method: 'DELETE' });

export const triggerScrape = () =>
  request<ScrapeResponse>('/api/scrape/refresh', { method: 'POST' });

export const fetchAdjustments = () =>
  request<TeamAdjustment[]>('/api/adjustments');

export const saveAdjustment = (team: string, body: TeamAdjustmentIn) =>
  request<TeamAdjustment>(`/api/adjustments/${encodeURIComponent(team)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const deleteAdjustment = (team: string) =>
  request<{ status: string }>(`/api/adjustments/${encodeURIComponent(team)}`, {
    method: 'DELETE',
  });

export const fetchAdjustedMetrics = () =>
  request<AdjustedTeam[]>('/api/metrics/adjusted');

export const fetchBenchmark = () =>
  request<BenchmarkResponse>('/api/metrics/benchmark');

// ---- Per-game player analyzer ---------------------------------------------

export const scrapePlayers = (fixtureId: string, live = true) =>
  request<PlayerSquadResponse>('/api/scrape/players', {
    method: 'POST',
    body: JSON.stringify({ fixture_id: fixtureId, live }),
  });

export const fetchTeamPlayers = (slug: string) =>
  request<TeamSquad>(`/api/players/${slug}`);

export interface LineupAnalysisBody {
  home_team: string;
  away_team: string;
  home_formation: string;
  away_formation: string;
  home_lineup: string[];
  away_lineup: string[];
}

export const analyzeLineup = (body: LineupAnalysisBody) =>
  request<LineupAnalysis>('/api/analyze/lineup', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export interface OptimalXiBody {
  team: string;
  formation: string;
  opponent_team?: string;
  opponent_formation?: string;
  opponent_lineup?: string[];
  top_n?: number;
}

export const fetchOptimalXi = (body: OptimalXiBody) =>
  request<OptimalXiResponse>('/api/analyze/optimal-xi', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const fetchFormations = () => request<FormationMap>('/api/formations');

// ---- Confirmed-lineup scrape (Selenium background job) ---------------------

export const triggerLineupScrape = (fixtureId: string) =>
  request<LineupJobStatus>('/api/scrape/lineups', {
    method: 'POST',
    body: JSON.stringify({ fixture_id: fixtureId }),
  });

export const fetchLineupStatus = (fixtureId: string) =>
  request<LineupJobStatus>(`/api/scrape/players/status/${fixtureId}`);

/**
 * Kick off a confirmed-XI scrape and poll its status until the background job
 * finishes. `trigger` activates the hook (0 = idle); incrementing it re-runs a
 * fresh scrape. `onDone` fires once per run when the job reaches "done". Polling
 * and any pending timer stop on unmount or terminal state.
 */
export function useConfirmedLineups(
  fixtureId: string | null,
  trigger: number,
  onDone?: (status: LineupJobStatus) => void,
  intervalMs = 3000,
) {
  const [status, setStatus] = useState<LineupJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    if (!fixtureId || trigger <= 0) return;
    let cancelled = false;
    let timer: number | undefined;

    const settle = (s: LineupJobStatus) => {
      setStatus(s);
      if (s.status === 'done') {
        doneRef.current?.(s);
      } else if (s.status !== 'error') {
        timer = window.setTimeout(poll, intervalMs);
      }
    };

    const poll = () => {
      fetchLineupStatus(fixtureId)
        .then((s) => {
          if (!cancelled) settle(s);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : 'lineup poll failed');
          timer = window.setTimeout(poll, intervalMs);
        });
    };

    triggerLineupScrape(fixtureId)
      .then((s) => {
        if (cancelled) return;
        setError(null);
        settle(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'lineup scrape failed');
      });

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [fixtureId, trigger, intervalMs]);

  return { status, error };
}

/**
 * Debounced, race-safe live prediction hook. Re-runs 250ms after the last
 * parameter change and aborts any in-flight request that became stale.
 */
export function useLivePrediction(req: PredictRequest | null, delayMs = 250) {
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const key = req ? JSON.stringify(req) : null;

  useEffect(() => {
    if (!key) return;
    const parsed = JSON.parse(key) as PredictRequest;
    setLoading(true);
    const timer = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      fetchPrediction(parsed, controller.signal)
        .then((p) => {
          setPrediction(p);
          setError(null);
          setLoading(false);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : 'Prediction failed');
          setLoading(false);
        });
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [key, delayMs]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return { prediction, loading, error };
}
