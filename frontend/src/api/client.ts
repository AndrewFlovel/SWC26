import { useEffect, useRef, useState } from 'react';
import type {
  AdjustedTeam,
  BenchmarkResponse,
  BracketProjection,
  Fixture,
  FormationMap,
  KnockoutSimResponse,
  LineupAnalysis,
  MatchResult,
  OptimalXiResponse,
  PlayerSquadResponse,
  PredictRequest,
  Prediction,
  ResultIn,
  ScrapeResponse,
  Team,
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
