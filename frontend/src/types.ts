export interface Team {
  name: string;
  group: string;
  elo: number;
  fifa_ranking: number;
  confederation: string;
  is_host: boolean;
  altitude_adapted: boolean;
  xg_avg: number;
  xga_avg: number;
  form_index: number;
  injury_impact: number;
}

export interface Venue {
  id: string;
  stadium: string;
  city: string;
  country: string;
  altitude_m: number;
  heat_index: number;
  wbgt_score: number;
  notes: string;
}

export interface Fixture {
  id: string;
  group: string;
  matchday: number;
  date: string;
  home: string;
  away: string;
  home_team_host: string | null;
  venue: Venue;
}

export interface GroupEntry {
  group: string;
  teams: Team[];
}

export interface PredictRequest {
  home: string;
  away: string;
  home_form?: number;
  away_form?: number;
  home_injury?: number;
  away_injury?: number;
  altitude_m?: number;
  heat_index?: number;
  home_advantage?: 'home' | 'away';
  xg_blend_weight?: number;
  rho?: number;
}

export interface Scoreline {
  score: string;
  prob: number;
}

export interface Prediction {
  home: string;
  away: string;
  lambda_home: number;
  lambda_away: number;
  p_home: number;
  p_draw: number;
  p_away: number;
  top_scorelines: Scoreline[];
  matrix: number[][];
  matrix_size: number;
}

export interface GroupSimRow {
  team: string;
  win_group_pct: number;
  second_pct: number;
  top2_pct: number;
  third_pct: number;
  avg_points: number;
}

export interface GroupSimResponse {
  group: string;
  n_sims: number;
  played: number;
  table: GroupSimRow[];
}

export type ResultStatus = 'scheduled' | 'live' | 'final';

export interface MatchResult {
  fixture_id: string;
  group: string;
  matchday: number;
  date: string;
  home: string;
  away: string;
  goals_home: number | null;
  goals_away: number | null;
  status: ResultStatus;
  source: 'manual' | 'scraped' | null;
  updated_at: string | null;
}

export interface ResultIn {
  goals_home: number;
  goals_away: number;
  status: 'live' | 'final';
}

export interface ScrapeEloUpdate {
  team: string;
  live_elo: number;
  model_elo: number;
  delta: number;
}

export interface ScrapeResponse {
  status: 'ok' | 'fallback' | 'error';
  fetched_at: string;
  elo_updates: ScrapeEloUpdate[];
  results_found: number;
  messages: string[];
}

export interface AdjustedTeam {
  team: string;
  group: string;
  base_elo: number;
  adjusted_elo: number;
  elo_delta: number;
  base_form: number;
  adjusted_form: number;
  form_delta: number;
  matches_played: number;
}

export const FLAGS: Record<string, string> = {
  Mexico: '🇲🇽',
  'South Korea': '🇰🇷',
  'South Africa': '🇿🇦',
  Czechia: '🇨🇿',
  Canada: '🇨🇦',
  Switzerland: '🇨🇭',
  Qatar: '🇶🇦',
  'Bosnia and Herzegovina': '🇧🇦',
  Brazil: '🇧🇷',
  Morocco: '🇲🇦',
  Scotland: '🏴󠁧󠁢󠁳󠁣󠁴󠁿',
  Haiti: '🇭🇹',
  'United States': '🇺🇸',
  Australia: '🇦🇺',
  Paraguay: '🇵🇾',
  Turkey: '🇹🇷',
  Germany: '🇩🇪',
  Ecuador: '🇪🇨',
  'Ivory Coast': '🇨🇮',
  Curacao: '🇨🇼',
  Netherlands: '🇳🇱',
  Japan: '🇯🇵',
  Tunisia: '🇹🇳',
  Sweden: '🇸🇪',
  Belgium: '🇧🇪',
  Iran: '🇮🇷',
  Egypt: '🇪🇬',
  'New Zealand': '🇳🇿',
  Spain: '🇪🇸',
  Uruguay: '🇺🇾',
  'Saudi Arabia': '🇸🇦',
  'Cape Verde': '🇨🇻',
  France: '🇫🇷',
  Senegal: '🇸🇳',
  Norway: '🇳🇴',
  Iraq: '🇮🇶',
  Argentina: '🇦🇷',
  Austria: '🇦🇹',
  Algeria: '🇩🇿',
  Jordan: '🇯🇴',
  Portugal: '🇵🇹',
  Colombia: '🇨🇴',
  Uzbekistan: '🇺🇿',
  'DR Congo': '🇨🇩',
  England: '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
  Croatia: '🇭🇷',
  Panama: '🇵🇦',
  Ghana: '🇬🇭',
};

export const flag = (name: string): string => FLAGS[name] ?? '🏳️';

// --------------------------------------------------------------------------- //
// Per-game player analyzer
// --------------------------------------------------------------------------- //

export interface Player {
  name: string;
  team: string;
  position: string;
  position_group: string;
  age: number;
  caps: number;
  international_goals: number;
  club: string;
  xg90: number;
  xa90: number;
  shots90: number;
  progressive_passes90: number;
  shot_creating_actions90: number;
  dribbles_completed90: number;
  tackles_won_pct: number;
  interceptions90: number;
  clearances90: number;
  pressures90: number;
  pressures_won_pct: number;
  aerial_won_pct: number;
  minutes_played: number;
  is_starter: boolean;
  injury_flag: boolean;
  pps: number;
}

export type SquadSource = 'scraped' | 'cached' | 'seed' | 'unavailable';

export interface TeamSquad {
  team: string;
  slug: string;
  source: SquadSource;
  players: Player[];
}

export interface PlayerSquadResponse {
  fixture_id: string;
  home: TeamSquad;
  away: TeamSquad;
  scraped_at: string;
  messages: string[];
}

export interface PositionalBattle {
  side: 'home' | 'away';
  attacker: string;
  attacker_position: string;
  attacker_pps: number;
  defender: string | null;
  defender_position: string | null;
  defender_pps: number | null;
  pms: number;
  favored: 'home' | 'away';
}

export interface LineupAnalysis {
  fsi: number;
  home_index: number;
  away_index: number;
  pis_home: number;
  pis_away: number;
  positional_battles: PositionalBattle[];
  dominance_heatmap: number[][];
}

export interface XiSlot {
  slot: string;
  position: string;
  player: string;
  pps: number;
}

export interface XiCandidate {
  formation: string;
  fsi: number;
  pis: number;
  lineup: XiSlot[];
}

export interface OptimalXiResponse {
  team: string;
  opponent_team: string;
  candidates: XiCandidate[];
}

export interface ConfirmedSide {
  team: string;
  formation: string;
  lineup: string[]; // 11 names in slot order, or [] when not applicable
  unmatched: string[]; // confirmed starters absent from our squad data
  announced: boolean; // Sofascore posted a confirmed XI for this side
}

export type LineupJobState = 'pending' | 'running' | 'done' | 'error';

export interface LineupJobStatus {
  fixture_id: string;
  status: LineupJobState;
  home: ConfirmedSide | null;
  away: ConfirmedSide | null;
  messages: string[];
  started_at: string;
  finished_at: string | null;
}

export interface FormationSlot {
  slot: string;
  position: string;
  x: number;
  y: number;
}

export type FormationMap = Record<string, FormationSlot[]>;

export const FORMATION_NAMES = ['4-3-3', '4-2-3-1', '4-4-2', '3-5-2'] as const;
export type FormationName = (typeof FORMATION_NAMES)[number];

/** Mirror of the backend `team_slug` (lowercase, spaces → hyphens). */
export const teamSlug = (name: string): string =>
  name.trim().toLowerCase().replace(/\s+/g, '-');

/** Green (strong) → gold → blood (weak) for a Player Performance Score. */
export const ppsColor = (pps: number): string =>
  pps >= 0.66 ? '#7ddf8f' : pps >= 0.33 ? '#e8c547' : '#ff7b5f';

/** Position-group accent colors for chips. */
export const POSITION_GROUP_COLOR: Record<string, string> = {
  GK: '#e8c547',
  DEF: '#5fa8ff',
  MID: '#7ddf8f',
  ATT: '#ff7b5f',
};
