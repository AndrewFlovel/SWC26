import { useEffect, useMemo, useState } from 'react';
import { fetchMatches, fetchTeams } from './api/client';
import GroupTable from './components/GroupTable';
import MatchAnalysis from './components/MatchAnalysis';
import MatchList from './components/MatchList';
import HeroScene from './three/HeroScene';
import type { Fixture, Team } from './types';

const GROUPS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];

export default function App() {
  const [teams, setTeams] = useState<Record<string, Team>>({});
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [group, setGroup] = useState('A');
  const [selected, setSelected] = useState<Fixture | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchTeams(), fetchMatches()])
      .then(([teamList, matchList]) => {
        setTeams(Object.fromEntries(teamList.map((t) => [t.name, t])));
        setFixtures(matchList);
      })
      .catch((err: unknown) => {
        setError(
          err instanceof Error
            ? `Engine unreachable: ${err.message}. Is the backend running on port 8001?`
            : 'Engine unreachable.',
        );
      });
  }, []);

  const groupFixtures = useMemo(
    () => fixtures.filter((f) => f.group === group),
    [fixtures, group],
  );

  return (
    <>
      <HeroScene />
      <div className="shell">
        <header className="masthead">
          <div className="kicker">FIFA World Cup 2026 · Predictive Engine</div>
          <h1>
            SWC26
            <br />
            BLOOD &amp; GLORY
          </h1>
          <p>
            Elo-grounded bivariate Poisson with Dixon-Coles correction, blended with xG
            tactical profiles, injury attrition, altitude hypoxia and WBGT heat burden.
            Drag the sliders — the engine recalculates in real time.
          </p>
        </header>

        {error && <div className="error-box">{error}</div>}

        <h2 className="section-title">Group stage · select battlefield</h2>
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

        <h2 className="section-title">Upcoming matches — Group {group}</h2>
        <MatchList fixtures={groupFixtures} onSelect={setSelected} />

        <h2 className="section-title">Qualification odds</h2>
        <GroupTable group={group} />

        <div className="footnote">
          <b>SWC26</b> · Monte Carlo engine · Dixon-Coles ρ = −0.13 · 48 nations · 16 venues ·
          built from deep-research telemetry, June 2026
        </div>
      </div>

      {selected && teams[selected.home] && teams[selected.away] && (
        <MatchAnalysis
          fixture={selected}
          teams={teams}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
