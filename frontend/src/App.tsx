import { useEffect, useMemo, useState } from 'react';
import { fetchMatches, fetchTeams } from './api/client';
import GroupTable from './components/GroupTable';
import KnockoutBracket from './components/KnockoutBracket';
import LanguageSelector from './components/LanguageSelector';
import MatchAnalysis from './components/MatchAnalysis';
import MatchList from './components/MatchList';
import PlayerAnalysis from './components/PlayerAnalysis';
import ResultsControl from './components/ResultsControl';
import { useI18n } from './i18n';
import HeroScene from './three/HeroScene';
import type { Fixture, Team } from './types';

const GROUPS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];

export default function App() {
  const { t } = useI18n();
  const [teams, setTeams] = useState<Record<string, Team>>({});
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [group, setGroup] = useState('A');
  const [selected, setSelected] = useState<Fixture | null>(null);
  const [deepFixture, setDeepFixture] = useState<Fixture | null>(null);
  const [view, setView] = useState<'analysis' | 'results' | 'knockout'>('analysis');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchTeams(), fetchMatches()])
      .then(([teamList, matchList]) => {
        setTeams(Object.fromEntries(teamList.map((t) => [t.name, t])));
        setFixtures(matchList);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'unknown');
      });
  }, []);

  const groupFixtures = useMemo(
    () => fixtures.filter((f) => f.group === group),
    [fixtures, group],
  );

  return (
    <>
      <HeroScene />
      <LanguageSelector />
      <div className="shell">
        <header className="masthead">
          <div className="kicker">{t('kicker')}</div>
          <h1>
            SWC26
            <br />
            {t('titleLine2')}
          </h1>
          <p>{t('heroDesc')}</p>
        </header>

        {error && (
          <div className="error-box">{t('engineUnreachable', { msg: error })}</div>
        )}

        <div className="view-tabs">
          <button
            type="button"
            className={view === 'analysis' ? 'on' : ''}
            onClick={() => setView('analysis')}
          >
            {t('navAnalysis')}
          </button>
          <button
            type="button"
            className={view === 'knockout' ? 'on' : ''}
            onClick={() => setView('knockout')}
          >
            {t('navKnockout')}
          </button>
          <button
            type="button"
            className={view === 'results' ? 'on' : ''}
            onClick={() => setView('results')}
          >
            {t('navResults')}
          </button>
        </div>

        {view === 'analysis' && (
          <>
            <h2 className="section-title">{t('sectionGroups')}</h2>
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

            <h2 className="section-title">{t('sectionMatches', { g: group })}</h2>
            <MatchList fixtures={groupFixtures} onSelect={setSelected} />

            <h2 className="section-title">{t('sectionOdds')}</h2>
            <GroupTable group={group} />
          </>
        )}

        {view === 'knockout' && <KnockoutBracket teams={teams} />}

        {view === 'results' && <ResultsControl />}

        <div className="footnote">
          <b>SWC26</b> · {t('footnote')}
        </div>
      </div>

      {selected && teams[selected.home] && teams[selected.away] && (
        <MatchAnalysis
          fixture={selected}
          teams={teams}
          onClose={() => setSelected(null)}
          onDeepAnalyze={() => {
            setDeepFixture(selected);
            setSelected(null);
          }}
        />
      )}

      {deepFixture && (
        <PlayerAnalysis
          fixture={deepFixture}
          onClose={() => setDeepFixture(null)}
        />
      )}
    </>
  );
}
