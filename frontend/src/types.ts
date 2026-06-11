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
  table: GroupSimRow[];
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
