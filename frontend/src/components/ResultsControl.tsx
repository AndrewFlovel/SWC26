import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  deleteResult,
  fetchAdjustedMetrics,
  fetchResults,
  saveResult,
  triggerScrape,
} from '../api/client';
import { useI18n } from '../i18n';
import type { AdjustedTeam, MatchResult, ScrapeResponse } from '../types';
import { flag } from '../types';
import MetricsPanel from './MetricsPanel';

const GROUPS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
const MATCHDAYS = [1, 2, 3];

interface Draft {
  home: string;
  away: string;
}

function ResultRow({
  result,
  onSaved,
}: {
  result: MatchResult;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<Draft>({
    home: result.goals_home?.toString() ?? '',
    away: result.goals_away?.toString() ?? '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft({
      home: result.goals_home?.toString() ?? '',
      away: result.goals_away?.toString() ?? '',
    });
  }, [result.goals_home, result.goals_away]);

  const valid =
    draft.home !== '' &&
    draft.away !== '' &&
    Number(draft.home) >= 0 &&
    Number(draft.away) >= 0;

  const save = () => {
    if (!valid) return;
    setBusy(true);
    setError(null);
    saveResult(result.fixture_id, {
      goals_home: Number(draft.home),
      goals_away: Number(draft.away),
      status: 'final',
    })
      .then(onSaved)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'failed'),
      )
      .finally(() => setBusy(false));
  };

  const clear = () => {
    setBusy(true);
    setError(null);
    deleteResult(result.fixture_id)
      .then(onSaved)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'failed'),
      )
      .finally(() => setBusy(false));
  };

  const statusKey =
    result.status === 'final'
      ? 'statusFinal'
      : result.status === 'live'
        ? 'statusLive'
        : 'statusScheduled';

  return (
    <div className="result-row">
      <span className="result-id">{result.fixture_id}</span>
      <span className="result-date">{result.date.slice(5)}</span>
      <span className="result-team home">
        <span className="name">{result.home}</span>
        <span className="flag">{flag(result.home)}</span>
      </span>
      <input
        type="number"
        min={0}
        max={20}
        value={draft.home}
        disabled={busy}
        onChange={(e) => setDraft({ ...draft, home: e.target.value })}
        aria-label={`${result.home} goals`}
      />
      <span className="result-dash">–</span>
      <input
        type="number"
        min={0}
        max={20}
        value={draft.away}
        disabled={busy}
        onChange={(e) => setDraft({ ...draft, away: e.target.value })}
        aria-label={`${result.away} goals`}
      />
      <span className="result-team">
        <span className="flag">{flag(result.away)}</span>
        <span className="name">{result.away}</span>
      </span>
      <span className={`badge status-${result.status}`}>{t(statusKey)}</span>
      {result.source && (
        <span className="badge">
          {t(result.source === 'manual' ? 'sourceManual' : 'sourceScraped')}
        </span>
      )}
      <span className="result-actions">
        <button type="button" disabled={!valid || busy} onClick={save}>
          {t('save')}
        </button>
        {result.status !== 'scheduled' && (
          <button type="button" className="ghost" disabled={busy} onClick={clear}>
            {t('clearResult')}
          </button>
        )}
      </span>
      {error && <span className="result-error">{error}</span>}
    </div>
  );
}

export default function ResultsControl() {
  const { t } = useI18n();
  const [results, setResults] = useState<MatchResult[]>([]);
  const [metrics, setMetrics] = useState<AdjustedTeam[]>([]);
  const [group, setGroup] = useState('A');
  const [scrape, setScrape] = useState<ScrapeResponse | null>(null);
  const [scraping, setScraping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    Promise.all([fetchResults(), fetchAdjustedMetrics()])
      .then(([res, met]) => {
        setResults(res);
        setMetrics(met);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : t('resultsLoadFailed')),
      );
  }, [t]);

  useEffect(() => {
    reload();
  }, [reload]);

  const runScrape = () => {
    setScraping(true);
    triggerScrape()
      .then((resp) => {
        setScrape(resp);
        reload();
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : t('scrapeFailed')),
      )
      .finally(() => setScraping(false));
  };

  const groupResults = useMemo(
    () => results.filter((r) => r.group === group),
    [results, group],
  );

  const scrapeBanner = useMemo(() => {
    if (!scrape) return null;
    const text =
      scrape.status === 'ok'
        ? t('scrapeOk', { n: scrape.results_found })
        : scrape.status === 'fallback'
          ? t('scrapeFallback')
          : `${t('scrapeFailed')}: ${scrape.messages[0] ?? ''}`;
    return { text, status: scrape.status };
  }, [scrape, t]);

  return (
    <>
      <h2 className="section-title">{t('resultsTitle')}</h2>
      <p className="results-desc">{t('resultsDesc')}</p>

      <div className="results-toolbar">
        <div className="group-chips">
          {GROUPS.map((g) => (
            <button
              type="button"
              key={g}
              className={`chip ${g === group ? 'active' : ''}`}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="scrape-btn"
          disabled={scraping}
          onClick={runScrape}
        >
          {scraping ? t('fetching') : `⟳ ${t('fetchToday')}`}
        </button>
      </div>

      {scrapeBanner && (
        <div className={`scrape-banner ${scrapeBanner.status}`}>
          {scrapeBanner.text}
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {MATCHDAYS.map((md) => {
        const rows = groupResults.filter((r) => r.matchday === md);
        if (rows.length === 0) return null;
        return (
          <div className="panel" key={md} style={{ marginTop: 18 }}>
            <h3 className="panel-title">
              {t('matchday')} {md}
            </h3>
            {rows.map((r) => (
              <ResultRow key={r.fixture_id} result={r} onSaved={reload} />
            ))}
          </div>
        );
      })}

      <MetricsPanel metrics={metrics} />
    </>
  );
}
