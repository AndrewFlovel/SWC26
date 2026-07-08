import { useEffect, useState } from 'react';
import { fetchTeams } from './api/client';
import BenchmarkPanel from './components/BenchmarkPanel';
import KnockoutBracket from './components/KnockoutBracket';
import LanguageSelector from './components/LanguageSelector';
import ResultsControl from './components/ResultsControl';
import { useI18n } from './i18n';
import HeroScene from './three/HeroScene';
import type { Team } from './types';

export default function App() {
  const { t } = useI18n();
  const [teams, setTeams] = useState<Record<string, Team>>({});
  const [view, setView] = useState<'knockout' | 'results' | 'benchmark'>('knockout');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTeams()
      .then((teamList) => {
        setTeams(Object.fromEntries(teamList.map((tm) => [tm.name, tm])));
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'unknown');
      });
  }, []);

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
          <button
            type="button"
            className={view === 'benchmark' ? 'on' : ''}
            onClick={() => setView('benchmark')}
          >
            {t('navBenchmark')}
          </button>
        </div>

        {view === 'knockout' && <KnockoutBracket teams={teams} />}

        {view === 'results' && <ResultsControl />}

        {view === 'benchmark' && <BenchmarkPanel />}

        <div className="footnote">
          <b>SWC26</b> · {t('footnote')}
        </div>
      </div>
    </>
  );
}
