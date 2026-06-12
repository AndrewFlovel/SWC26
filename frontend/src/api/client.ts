import { useEffect, useRef, useState } from 'react';
import type {
  AdjustedTeam,
  Fixture,
  GroupEntry,
  GroupSimResponse,
  MatchResult,
  PredictRequest,
  Prediction,
  ResultIn,
  ScrapeResponse,
  Team,
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
export const fetchGroups = () => request<GroupEntry[]>('/api/groups');
export const fetchMatches = () => request<Fixture[]>('/api/matches');

export const fetchPrediction = (req: PredictRequest, signal?: AbortSignal) =>
  request<Prediction>('/api/predict', {
    method: 'POST',
    body: JSON.stringify(req),
    signal,
  });

export const fetchGroupSim = (group: string, nSims = 3000) =>
  request<GroupSimResponse>('/api/simulate/group', {
    method: 'POST',
    body: JSON.stringify({ group, n_sims: nSims }),
  });

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
