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
