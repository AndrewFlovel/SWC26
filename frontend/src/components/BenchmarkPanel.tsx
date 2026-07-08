import { useEffect, useState } from 'react';
import { fetchBenchmark } from '../api/client';
import { useI18n } from '../i18n';
import type { BenchmarkAggregate, BenchmarkResponse } from '../types';
import { flag } from '../types';

function AggTable({
  labelHeader,
  rows,
  withFlag = false,
}: {
  labelHeader: string;
  rows: BenchmarkAggregate[];
  withFlag?: boolean;
}) {
  const { t } = useI18n();
  return (
    <table className="sim-table">
      <thead>
        <tr>
          <th>{labelHeader}</th>
          <th>{t('benchMatches')}</th>
          <th>{t('correctWinner')}</th>
          <th>{t('brier')}</th>
          <th>{t('logLoss')}</th>
          <th>{t('exactScore')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td>
              {withFlag ? `${flag(r.label)} ` : ''}
              {r.label}
            </td>
            <td>{r.matches}</td>
            <td>{r.correct_winner_pct.toFixed(1)}%</td>
            <td>{r.brier.toFixed(3)}</td>
            <td>{r.log_loss.toFixed(3)}</td>
            <td>{r.exact_score_pct.toFixed(1)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function BenchmarkPanel() {
  const { t } = useI18n();
  const [data, setData] = useState<BenchmarkResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBenchmark()
      .then((r) => !cancelled && setData(r))
      .catch((e: unknown) =>
        !cancelled && setError(e instanceof Error ? e.message : t('benchLoadFailed')),
      );
    return () => {
      cancelled = true;
    };
  }, [t]);

  if (error) return <div className="error-box">{error}</div>;

  const s = data?.summary;
  const cards: { label: string; value: string }[] = s
    ? [
        { label: t('correctWinner'), value: `${s.correct_winner_pct.toFixed(1)}%` },
        { label: t('exactScore'), value: `${s.exact_score_pct.toFixed(1)}%` },
        { label: t('brier'), value: s.brier.toFixed(3) },
        { label: t('logLoss'), value: s.log_loss.toFixed(3) },
      ]
    : [];

  return (
    <>
      <h2 className="section-title">{t('benchmarkTitle')}</h2>
      <div className="panel" style={{ marginBottom: 22 }}>
        <p className="bracket-desc">{t('benchmarkDesc')}</p>
        {!data ? (
          <span className="loading-pulse" />
        ) : s && s.matches === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
            {t('benchNoData')}
          </div>
        ) : (
          <div className="bench-cards">
            {cards.map((c) => (
              <div className="bench-card" key={c.label}>
                <div className="bench-card-value">{c.value}</div>
                <div className="bench-card-label">
                  {c.label} · {t('benchOverall')} ({s?.matches})
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {data && data.matches.length > 0 && (
        <>
          <h2 className="section-title">{t('byRound')}</h2>
          <div className="panel" style={{ marginBottom: 22 }}>
            <AggTable labelHeader={t('stage')} rows={data.by_round} />
          </div>

          <h2 className="section-title">{t('byTeam')}</h2>
          <div className="panel">
            <AggTable labelHeader={t('team')} rows={data.by_team} withFlag />
          </div>
        </>
      )}
    </>
  );
}
