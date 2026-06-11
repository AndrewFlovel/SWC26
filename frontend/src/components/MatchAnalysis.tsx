import { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useLivePrediction } from '../api/client';
import type { Fixture, PredictRequest, Team } from '../types';
import { flag } from '../types';
import ProbabilityBars from './ProbabilityBars';
import ScoreMatrix from './ScoreMatrix';
import TopScorelines from './TopScorelines';

interface Props {
  fixture: Fixture;
  teams: Record<string, Team>;
  onClose: () => void;
}

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
  onChange: (v: number) => void;
}

function Slider({ label, value, min, max, step, format, onChange }: SliderProps) {
  const fill = ((value - min) / (max - min)) * 100;
  return (
    <div className="slider-row">
      <label>
        <span>{label}</span>
        <output>{format ? format(value) : value.toFixed(2)}</output>
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ ['--fill' as string]: `${fill}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

type Advantage = 'none' | 'home' | 'away';

export default function MatchAnalysis({ fixture, teams, onClose }: Props) {
  const homeTeam = teams[fixture.home];
  const awayTeam = teams[fixture.away];

  const [homeForm, setHomeForm] = useState(homeTeam.form_index);
  const [awayForm, setAwayForm] = useState(awayTeam.form_index);
  const [homeInjury, setHomeInjury] = useState(homeTeam.injury_impact);
  const [awayInjury, setAwayInjury] = useState(awayTeam.injury_impact);
  const [altitude, setAltitude] = useState(fixture.venue.altitude_m);
  const [heat, setHeat] = useState(fixture.venue.heat_index);
  const [blend, setBlend] = useState(0.45);
  const [advantage, setAdvantage] = useState<Advantage>(
    fixture.home_team_host === fixture.home
      ? 'home'
      : fixture.home_team_host === fixture.away
        ? 'away'
        : 'none',
  );

  const req = useMemo<PredictRequest>(
    () => ({
      home: fixture.home,
      away: fixture.away,
      home_form: homeForm,
      away_form: awayForm,
      home_injury: homeInjury,
      away_injury: awayInjury,
      altitude_m: altitude,
      heat_index: heat,
      xg_blend_weight: blend,
      ...(advantage !== 'none' ? { home_advantage: advantage } : {}),
    }),
    [fixture, homeForm, awayForm, homeInjury, awayInjury, altitude, heat, blend, advantage],
  );

  const { prediction, loading, error } = useLivePrediction(req);

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
            <button type="button" className="close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
          <div className="analysis-sub">
            {fixture.venue.stadium}, {fixture.venue.city} · Matchday {fixture.matchday} ·{' '}
            {fixture.date} · {fixture.venue.notes}
          </div>

          <div className="analysis-grid">
            <div className="controls">
              <h3>Predictive parameters</h3>
              <Slider
                label={`${flag(fixture.home)} ${fixture.home} — xG form`}
                value={homeForm}
                min={0}
                max={1}
                step={0.05}
                onChange={setHomeForm}
              />
              <Slider
                label={`${flag(fixture.home)} ${fixture.home} — injury impact`}
                value={homeInjury}
                min={0}
                max={1}
                step={0.05}
                onChange={setHomeInjury}
              />
              <Slider
                label={`${flag(fixture.away)} ${fixture.away} — xG form`}
                value={awayForm}
                min={0}
                max={1}
                step={0.05}
                onChange={setAwayForm}
              />
              <Slider
                label={`${flag(fixture.away)} ${fixture.away} — injury impact`}
                value={awayInjury}
                min={0}
                max={1}
                step={0.05}
                onChange={setAwayInjury}
              />
              <Slider
                label="Altitude / fatigue penalty"
                value={altitude}
                min={0}
                max={3000}
                step={10}
                format={(v) => `${v.toFixed(0)} m`}
                onChange={setAltitude}
              />
              <Slider
                label="Heat burden (WBGT index)"
                value={heat}
                min={0}
                max={2}
                step={0.05}
                onChange={setHeat}
              />
              <Slider
                label="xG model weight (vs Elo)"
                value={blend}
                min={0}
                max={1}
                step={0.05}
                onChange={setBlend}
              />
              <div className="slider-row">
                <label>
                  <span>Host advantage</span>
                </label>
                <div className="seg">
                  {(['none', 'home', 'away'] as const).map((opt) => (
                    <button
                      type="button"
                      key={opt}
                      className={advantage === opt ? 'on' : ''}
                      onClick={() => setAdvantage(opt)}
                    >
                      {opt === 'none'
                        ? 'Neutral'
                        : opt === 'home'
                          ? fixture.home
                          : fixture.away}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="results">
              <h3>
                Live simulation output
                {prediction && (
                  <span style={{ color: 'var(--text-dim)', marginLeft: 12, letterSpacing: 0 }}>
                    λ {prediction.lambda_home.toFixed(2)} / {prediction.lambda_away.toFixed(2)}
                  </span>
                )}
              </h3>
              {error && <div className="error-box">{error}</div>}
              {prediction && (
                <>
                  <ProbabilityBars
                    home={prediction.home}
                    away={prediction.away}
                    pHome={prediction.p_home}
                    pDraw={prediction.p_draw}
                    pAway={prediction.p_away}
                  />
                  <h3>Most probable scorelines</h3>
                  <TopScorelines scorelines={prediction.top_scorelines} />
                  <h3>Exact score probability matrix</h3>
                  <ScoreMatrix
                    home={prediction.home}
                    away={prediction.away}
                    matrix={prediction.matrix}
                  />
                </>
              )}
              {!prediction && !error && (
                <div style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                  Crunching probabilities…
                </div>
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
