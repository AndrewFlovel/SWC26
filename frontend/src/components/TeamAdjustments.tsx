import { useCallback, useEffect, useState } from 'react';
import {
  deleteAdjustment,
  fetchAdjustments,
  fetchTeams,
  saveAdjustment,
} from '../api/client';
import { useI18n } from '../i18n';
import type { TeamAdjustment } from '../types';
import { flag } from '../types';

/**
 * Manual squad-availability overrides: record real suspensions/injuries per
 * team as a signed delta on top of the baseline injury impact. Feeds every
 * prediction and simulation through the adjusted team metrics.
 */
export default function TeamAdjustments({ onChanged }: { onChanged?: () => void }) {
  const { t } = useI18n();
  const [teams, setTeams] = useState<string[]>([]);
  const [adjustments, setAdjustments] = useState<TeamAdjustment[]>([]);
  const [team, setTeam] = useState('');
  const [delta, setDelta] = useState('0.1');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    fetchAdjustments()
      .then((rows) => {
        setAdjustments(rows);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'failed'),
      );
  }, []);

  useEffect(() => {
    fetchTeams()
      .then((list) => setTeams(list.map((tm) => tm.name).sort()))
      .catch(() => setTeams([]));
    reload();
  }, [reload]);

  const parsed = Number(delta);
  const valid = team !== '' && delta !== '' && parsed >= -1 && parsed <= 1;

  const save = () => {
    if (!valid) return;
    setBusy(true);
    saveAdjustment(team, { injury_delta: parsed, note })
      .then(() => {
        setNote('');
        reload();
        onChanged?.();
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'failed'),
      )
      .finally(() => setBusy(false));
  };

  const clear = (name: string) => {
    setBusy(true);
    deleteAdjustment(name)
      .then(() => {
        reload();
        onChanged?.();
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'failed'),
      )
      .finally(() => setBusy(false));
  };

  return (
    <div className="panel" style={{ marginTop: 18 }}>
      <h3 className="panel-title">{t('adjustmentsTitle')}</h3>
      <p className="results-desc">{t('adjustmentsDesc')}</p>

      <div className="adjust-form">
        <select
          value={team}
          disabled={busy}
          onChange={(e) => setTeam(e.target.value)}
          aria-label={t('team')}
        >
          <option value="">{t('team')}…</option>
          {teams.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <label className="adjust-field">
          {t('adjustDelta')}
          <input
            type="number"
            step={0.05}
            min={-1}
            max={1}
            value={delta}
            disabled={busy}
            onChange={(e) => setDelta(e.target.value)}
          />
        </label>
        <input
          type="text"
          className="adjust-note"
          maxLength={280}
          placeholder={t('adjustNote')}
          value={note}
          disabled={busy}
          onChange={(e) => setNote(e.target.value)}
        />
        <button type="button" disabled={!valid || busy} onClick={save}>
          {t('adjustAdd')}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {adjustments.length === 0 ? (
        <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          {t('adjustEmpty')}
        </div>
      ) : (
        adjustments.map((a) => (
          <div className="result-row" key={a.team}>
            <span className="result-team home">
              <span className="name">{a.team}</span>
              <span className="flag">{flag(a.team)}</span>
            </span>
            <span className={`badge ${a.injury_delta > 0 ? 'status-live' : ''}`}>
              {a.injury_delta > 0 ? '+' : ''}
              {a.injury_delta.toFixed(2)}
            </span>
            <span className="badge">
              {t('adjustEffective')}: {a.effective_injury.toFixed(2)}
            </span>
            {a.note && <span className="adjust-note-text">{a.note}</span>}
            <span className="result-actions">
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => clear(a.team)}
              >
                {t('clearResult')}
              </button>
            </span>
          </div>
        ))
      )}
    </div>
  );
}
