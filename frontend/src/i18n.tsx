/* Lightweight i18n: a typed dictionary + React context. No external deps. */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type Lang = 'en' | 'es' | 'pt';

export const LANGS: { code: Lang; label: string }[] = [
  { code: 'en', label: 'EN' },
  { code: 'es', label: 'ES' },
  { code: 'pt', label: 'PT' },
];

const dictionaries = {
  en: {
    kicker: 'FIFA World Cup 2026 · Predictive Engine',
    titleLine2: 'BLOOD & GLORY',
    heroDesc:
      'Elo-grounded bivariate Poisson with Dixon-Coles correction, blended with xG ' +
      'tactical profiles, injury attrition, altitude hypoxia and WBGT heat burden. ' +
      'Drag the sliders — the engine recalculates in real time.',
    engineUnreachable:
      'Engine unreachable: {msg}. Is the backend running on port 8001?',
    sectionGroups: 'Group stage · select battlefield',
    sectionMatches: 'Upcoming matches — Group {g}',
    sectionOdds: 'Qualification odds',
    footnote:
      'Monte Carlo engine · Dixon-Coles ρ = −0.13 · 48 nations · 16 venues · ' +
      'built from deep-research telemetry, June 2026',
    group: 'Group',
    match: 'Match',
    analyze: 'Analyze →',
    matchday: 'Matchday',
    hostBadge: '★ {team} host',
    groupTableTitle: 'Group {g} — Monte Carlo qualification odds (3,000 runs)',
    team: 'Team',
    winGroup: 'Win group',
    second: '2nd',
    third: '3rd',
    avgPts: 'Avg pts',
    top2: 'Top-2 qualify',
    simulating: 'Simulating…',
    simFailed: 'Simulation failed',
    params: 'Predictive parameters',
    xgForm: 'xG form',
    injuryImpact: 'injury impact',
    altitudeSlider: 'Altitude / fatigue penalty',
    heatSlider: 'Heat burden (WBGT index)',
    blendSlider: 'xG model weight (vs Elo)',
    hostAdvantage: 'Host advantage',
    neutral: 'Neutral',
    liveOutput: 'Live simulation output',
    topScores: 'Most probable scorelines',
    matrixTitle: 'Exact score probability matrix',
    matrixAxis: 'rows: {home} goals · cols: {away} goals',
    crunching: 'Crunching probabilities…',
    predictionFailed: 'Prediction failed',
    draw: 'Draw',
    close: 'Close',
    navAnalysis: 'Analysis',
    navResults: 'Results control',
    resultsTitle: 'Results control — group stage',
    resultsDesc:
      'Record final scores manually or fetch the day’s data. Final results ' +
      'feed Elo and form adjustments into every prediction and simulation.',
    fetchToday: 'Fetch today’s data',
    fetching: 'Fetching…',
    scrapeOk: 'Live data fetched · {n} results found',
    scrapeFallback: 'Page fetched but no parsable data — use manual entry',
    scrapeFailed: 'Fetch failed',
    resultsLoadFailed: 'Could not load results',
    statusScheduled: 'Scheduled',
    statusLive: 'Live',
    statusFinal: 'Final',
    sourceManual: 'manual',
    sourceScraped: 'scraped',
    save: 'Save',
    clearResult: 'Clear',
    metricsTitle: 'Adjusted metrics — Elo & form after played matches',
    baseElo: 'Base Elo',
    adjustedElo: 'Adjusted Elo',
    eloDelta: 'Δ Elo',
    formDelta: 'Δ Form',
    matchesPlayed: 'Played',
    noAdjustments: 'No final results recorded yet — metrics match the baseline.',
    oddsConditioned: 'Includes {n} played results',
    deepAnalysis: '⚔ Deep player analysis',
    playerAnalysisTitle: 'Player-level matchup',
    runningScraper: 'Running scraper — fetching squads…',
    liveScrape: 'Live scrape',
    playersScraped: '{n} players · source: {src}',
    noSquadData:
      'No player data for {team} yet. Seeded squads: Spain, Uruguay, Argentina, Austria.',
    tabSquad: 'Squad',
    tabFormation: 'Formation',
    tabBattles: 'Battles',
    tabOptimizer: 'Optimizer',
    srcScraped: 'scraped',
    srcCached: 'cached',
    srcSeed: 'seed',
    srcUnavailable: 'unavailable',
    formation: 'Formation',
    formationStrength: 'Formation strength (home)',
    pressingIntensity: 'Pressing intensity',
    dominance: 'Dominance heatmap',
    showHeatmap: 'Heatmap',
    battle: 'Battle',
    attacker: 'Attacker',
    defender: 'Defender',
    pms: 'Battle score',
    favored: 'Edge',
    favoredHome: 'home',
    favoredAway: 'away',
    bestXi: 'Best XI',
    findBestXi: 'Find best XI',
    optimizeFor: 'Optimize for',
    applyXi: 'Apply to pitch',
    pps: 'PPS',
    age: 'Age',
    caps: 'Caps',
    starts: 'Starts',
    assists: 'Assists',
    yellowCards: 'Yellow cards',
    redCards: 'Red cards',
    crunchingPlayers: 'Computing matchup…',
  },
  es: {
    kicker: 'Copa Mundial FIFA 2026 · Motor Predictivo',
    titleLine2: 'SANGRE Y GLORIA',
    heroDesc:
      'Poisson bivariado anclado en Elo con corrección de Dixon-Coles, combinado con ' +
      'perfiles tácticos xG, desgaste por lesiones, hipoxia de altitud y carga térmica ' +
      'WBGT. Mueve los controles: el motor recalcula en tiempo real.',
    engineUnreachable:
      'Motor inaccesible: {msg}. ¿Está el backend corriendo en el puerto 8001?',
    sectionGroups: 'Fase de grupos · elige tu campo de batalla',
    sectionMatches: 'Próximos partidos — Grupo {g}',
    sectionOdds: 'Probabilidades de clasificación',
    footnote:
      'Motor Monte Carlo · Dixon-Coles ρ = −0.13 · 48 selecciones · 16 sedes · ' +
      'construido con telemetría de investigación profunda, junio 2026',
    group: 'Grupo',
    match: 'Partido',
    analyze: 'Analizar →',
    matchday: 'Jornada',
    hostBadge: '★ {team} anfitrión',
    groupTableTitle:
      'Grupo {g} — Probabilidades Monte Carlo de clasificación (3.000 corridas)',
    team: 'Equipo',
    winGroup: 'Gana grupo',
    second: '2do',
    third: '3ro',
    avgPts: 'Pts medios',
    top2: 'Clasifica Top-2',
    simulating: 'Simulando…',
    simFailed: 'La simulación falló',
    params: 'Parámetros predictivos',
    xgForm: 'forma xG',
    injuryImpact: 'impacto de lesiones',
    altitudeSlider: 'Altitud / penalización por fatiga',
    heatSlider: 'Carga térmica (índice WBGT)',
    blendSlider: 'Peso del modelo xG (vs Elo)',
    hostAdvantage: 'Ventaja de anfitrión',
    neutral: 'Neutral',
    liveOutput: 'Salida de simulación en vivo',
    topScores: 'Marcadores más probables',
    matrixTitle: 'Matriz de probabilidad de marcador exacto',
    matrixAxis: 'filas: goles de {home} · columnas: goles de {away}',
    crunching: 'Calculando probabilidades…',
    predictionFailed: 'La predicción falló',
    draw: 'Empate',
    close: 'Cerrar',
    navAnalysis: 'Análisis',
    navResults: 'Control de resultados',
    resultsTitle: 'Control de resultados — fase de grupos',
    resultsDesc:
      'Captura marcadores finales manualmente u obtén los datos del día. Los ' +
      'resultados finales ajustan Elo y forma en cada predicción y simulación.',
    fetchToday: 'Obtener datos del día',
    fetching: 'Obteniendo…',
    scrapeOk: 'Datos en vivo obtenidos · {n} resultados encontrados',
    scrapeFallback: 'Página obtenida pero sin datos parseables — usa captura manual',
    scrapeFailed: 'La obtención falló',
    resultsLoadFailed: 'No se pudieron cargar los resultados',
    statusScheduled: 'Programado',
    statusLive: 'En vivo',
    statusFinal: 'Final',
    sourceManual: 'manual',
    sourceScraped: 'scrapeado',
    save: 'Guardar',
    clearResult: 'Limpiar',
    metricsTitle: 'Métricas ajustadas — Elo y forma tras partidos jugados',
    baseElo: 'Elo base',
    adjustedElo: 'Elo ajustado',
    eloDelta: 'Δ Elo',
    formDelta: 'Δ Forma',
    matchesPlayed: 'Jugados',
    noAdjustments:
      'Aún no hay resultados finales registrados — las métricas son las base.',
    oddsConditioned: 'Incluye {n} resultados jugados',
    deepAnalysis: '⚔ Análisis de jugadores',
    playerAnalysisTitle: 'Enfrentamiento a nivel de jugador',
    runningScraper: 'Ejecutando scraper — obteniendo plantillas…',
    liveScrape: 'Scrape en vivo',
    playersScraped: '{n} jugadores · fuente: {src}',
    noSquadData:
      'Aún no hay datos de {team}. Plantillas disponibles: España, Uruguay, Argentina, Austria.',
    tabSquad: 'Plantilla',
    tabFormation: 'Formación',
    tabBattles: 'Duelos',
    tabOptimizer: 'Optimizador',
    srcScraped: 'scrapeado',
    srcCached: 'caché',
    srcSeed: 'base',
    srcUnavailable: 'no disponible',
    formation: 'Formación',
    formationStrength: 'Fuerza de formación (local)',
    pressingIntensity: 'Intensidad de presión',
    dominance: 'Mapa de dominio',
    showHeatmap: 'Mapa de calor',
    battle: 'Duelo',
    attacker: 'Atacante',
    defender: 'Defensor',
    pms: 'Puntaje del duelo',
    favored: 'Ventaja',
    favoredHome: 'local',
    favoredAway: 'visitante',
    bestXi: 'Mejor XI',
    findBestXi: 'Calcular mejor XI',
    optimizeFor: 'Optimizar para',
    applyXi: 'Aplicar al campo',
    pps: 'PPS',
    age: 'Edad',
    caps: 'Partidos',
    starts: 'Titularidades',
    assists: 'Asistencias',
    yellowCards: 'Tarjetas amarillas',
    redCards: 'Tarjetas rojas',
    crunchingPlayers: 'Calculando enfrentamiento…',
  },
  pt: {
    kicker: 'Copa do Mundo FIFA 2026 · Motor Preditivo',
    titleLine2: 'SANGUE E GLÓRIA',
    heroDesc:
      'Poisson bivariado ancorado em Elo com correção de Dixon-Coles, combinado com ' +
      'perfis táticos de xG, desgaste por lesões, hipóxia de altitude e carga térmica ' +
      'WBGT. Arraste os controles: o motor recalcula em tempo real.',
    engineUnreachable:
      'Motor inacessível: {msg}. O backend está rodando na porta 8001?',
    sectionGroups: 'Fase de grupos · escolha seu campo de batalha',
    sectionMatches: 'Próximas partidas — Grupo {g}',
    sectionOdds: 'Probabilidades de classificação',
    footnote:
      'Motor Monte Carlo · Dixon-Coles ρ = −0.13 · 48 seleções · 16 estádios · ' +
      'construído com telemetria de pesquisa profunda, junho de 2026',
    group: 'Grupo',
    match: 'Partida',
    analyze: 'Analisar →',
    matchday: 'Rodada',
    hostBadge: '★ {team} anfitrião',
    groupTableTitle:
      'Grupo {g} — Probabilidades Monte Carlo de classificação (3.000 execuções)',
    team: 'Seleção',
    winGroup: 'Vence grupo',
    second: '2º',
    third: '3º',
    avgPts: 'Pts médios',
    top2: 'Classifica Top-2',
    simulating: 'Simulando…',
    simFailed: 'A simulação falhou',
    params: 'Parâmetros preditivos',
    xgForm: 'forma xG',
    injuryImpact: 'impacto de lesões',
    altitudeSlider: 'Altitude / penalidade de fadiga',
    heatSlider: 'Carga térmica (índice WBGT)',
    blendSlider: 'Peso do modelo xG (vs Elo)',
    hostAdvantage: 'Vantagem de anfitrião',
    neutral: 'Neutro',
    liveOutput: 'Saída da simulação ao vivo',
    topScores: 'Placares mais prováveis',
    matrixTitle: 'Matriz de probabilidade de placar exato',
    matrixAxis: 'linhas: gols de {home} · colunas: gols de {away}',
    crunching: 'Calculando probabilidades…',
    predictionFailed: 'A previsão falhou',
    draw: 'Empate',
    close: 'Fechar',
    navAnalysis: 'Análise',
    navResults: 'Controle de resultados',
    resultsTitle: 'Controle de resultados — fase de grupos',
    resultsDesc:
      'Registre placares finais manualmente ou busque os dados do dia. Os ' +
      'resultados finais ajustam Elo e forma em cada previsão e simulação.',
    fetchToday: 'Buscar dados do dia',
    fetching: 'Buscando…',
    scrapeOk: 'Dados ao vivo obtidos · {n} resultados encontrados',
    scrapeFallback: 'Página obtida mas sem dados analisáveis — use entrada manual',
    scrapeFailed: 'A busca falhou',
    resultsLoadFailed: 'Não foi possível carregar os resultados',
    statusScheduled: 'Agendado',
    statusLive: 'Ao vivo',
    statusFinal: 'Final',
    sourceManual: 'manual',
    sourceScraped: 'raspado',
    save: 'Salvar',
    clearResult: 'Limpar',
    metricsTitle: 'Métricas ajustadas — Elo e forma após partidas jogadas',
    baseElo: 'Elo base',
    adjustedElo: 'Elo ajustado',
    eloDelta: 'Δ Elo',
    formDelta: 'Δ Forma',
    matchesPlayed: 'Jogadas',
    noAdjustments:
      'Nenhum resultado final registrado ainda — as métricas são as de base.',
    oddsConditioned: 'Inclui {n} resultados jogados',
    deepAnalysis: '⚔ Análise de jogadores',
    playerAnalysisTitle: 'Confronto a nível de jogador',
    runningScraper: 'Executando scraper — buscando elencos…',
    liveScrape: 'Scrape ao vivo',
    playersScraped: '{n} jogadores · fonte: {src}',
    noSquadData:
      'Ainda sem dados de {team}. Elencos disponíveis: Espanha, Uruguai, Argentina, Áustria.',
    tabSquad: 'Elenco',
    tabFormation: 'Formação',
    tabBattles: 'Duelos',
    tabOptimizer: 'Otimizador',
    srcScraped: 'raspado',
    srcCached: 'cache',
    srcSeed: 'base',
    srcUnavailable: 'indisponível',
    formation: 'Formação',
    formationStrength: 'Força da formação (mandante)',
    pressingIntensity: 'Intensidade de pressão',
    dominance: 'Mapa de domínio',
    showHeatmap: 'Mapa de calor',
    battle: 'Duelo',
    attacker: 'Atacante',
    defender: 'Defensor',
    pms: 'Pontuação do duelo',
    favored: 'Vantagem',
    favoredHome: 'mandante',
    favoredAway: 'visitante',
    bestXi: 'Melhor XI',
    findBestXi: 'Calcular melhor XI',
    optimizeFor: 'Otimizar para',
    applyXi: 'Aplicar ao campo',
    pps: 'PPS',
    age: 'Idade',
    caps: 'Jogos',
    starts: 'Titularidades',
    assists: 'Assistências',
    yellowCards: 'Cartões amarelos',
    redCards: 'Cartões vermelhos',
    crunchingPlayers: 'Calculando confronto…',
  },
} as const;

export type TranslationKey = keyof (typeof dictionaries)['en'];

interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

const STORAGE_KEY = 'swc26-lang';

function initialLang(): Lang {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'en' || stored === 'es' || stored === 'pt') return stored;
  const nav = navigator.language.slice(0, 2).toLowerCase();
  if (nav === 'es' || nav === 'pt') return nav;
  return 'en';
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  const setLang = useCallback((next: Lang) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLangState(next);
  }, []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      let text: string = dictionaries[lang][key] ?? dictionaries.en[key];
      if (vars) {
        for (const [name, value] of Object.entries(vars)) {
          text = text.replaceAll(`{${name}}`, String(value));
        }
      }
      return text;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside LanguageProvider');
  return ctx;
}
