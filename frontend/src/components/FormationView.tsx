import { useState } from 'react';
import { useI18n } from '../i18n';
import type { FormationMap, Player, TeamSquad } from '../types';
import { FORMATION_NAMES, ppsColor } from '../types';

const W = 100;
const H = 150;

interface Props {
  formations: FormationMap;
  home: TeamSquad;
  away: TeamSquad;
  homeFormation: string;
  awayFormation: string;
  homeLineup: string[];
  awayLineup: string[];
  heatmap: number[][];
  onHomeFormation: (f: string) => void;
  onAwayFormation: (f: string) => void;
}

interface Node {
  x: number;
  y: number;
  pps: number;
  name: string;
}

function surname(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1] || name;
}

function nameMap(squad: TeamSquad): Map<string, Player> {
  const m = new Map<string, Player>();
  for (const p of squad.players) m.set(p.name, p);
  return m;
}

export default function FormationView(props: Props) {
  const { t } = useI18n();
  const [showHeat, setShowHeat] = useState(true);

  const homeMap = nameMap(props.home);
  const awayMap = nameMap(props.away);
  const homeSlots = props.formations[props.homeFormation] ?? [];
  const awaySlots = props.formations[props.awayFormation] ?? [];

  // Home attacks "up" (y→1); away coords are point-reflected onto the shared
  // pitch, matching the analyzer's frame. SVG y is inverted (0 at top).
  const homeNodes: Node[] = homeSlots.map((s, i) => {
    const name = props.homeLineup[i] ?? s.position;
    return { x: s.x * W, y: H * (1 - s.y), pps: homeMap.get(name)?.pps ?? 0.3, name };
  });
  const awayNodes: Node[] = awaySlots.map((s, i) => {
    const name = props.awayLineup[i] ?? s.position;
    return { x: (1 - s.x) * W, y: H * s.y, pps: awayMap.get(name)?.pps ?? 0.3, name };
  });

  const maxAbs = Math.max(0.01, ...props.heatmap.flat().map((v) => Math.abs(v)));

  return (
    <div className="formation-view">
      <div className="formation-controls">
        <label className="formation-pick">
          <span style={{ color: '#7ddf8f' }}>{props.home.team}</span>
          <select
            value={props.homeFormation}
            onChange={(e) => props.onHomeFormation(e.target.value)}
          >
            {FORMATION_NAMES.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={`heat-toggle ${showHeat ? 'on' : ''}`}
          onClick={() => setShowHeat((v) => !v)}
        >
          {t('showHeatmap')}
        </button>
        <label className="formation-pick">
          <span style={{ color: '#ff7b5f' }}>{props.away.team}</span>
          <select
            value={props.awayFormation}
            onChange={(e) => props.onAwayFormation(e.target.value)}
          >
            {FORMATION_NAMES.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
      </div>

      <svg className="pitch-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        <rect x="1" y="1" width={W - 2} height={H - 2} rx="3" className="pitch-bg" />
        <line x1="1" y1={H / 2} x2={W - 1} y2={H / 2} className="pitch-line" />
        <circle cx={W / 2} cy={H / 2} r="9" className="pitch-line" fill="none" />
        <rect x={W / 2 - 18} y="1" width="36" height="20" className="pitch-line" fill="none" />
        <rect x={W / 2 - 18} y={H - 21} width="36" height="20" className="pitch-line" fill="none" />

        {showHeat &&
          props.heatmap.map((row, r) =>
            row.map((v, c) => {
              const intensity = Math.min(Math.abs(v) / maxAbs, 1);
              const rgb = v >= 0 ? '125,223,143' : '255,123,95';
              return (
                <rect
                  key={`h-${r}-${c}`}
                  x={(c / 3) * W}
                  y={H * (1 - (r + 1) / 3)}
                  width={W / 3}
                  height={H / 3}
                  fill={`rgba(${rgb},${(intensity * 0.3).toFixed(3)})`}
                />
              );
            }),
          )}

        {[
          ...awayNodes.map((n) => ({ n, side: 'away' as const })),
          ...homeNodes.map((n) => ({ n, side: 'home' as const })),
        ].map(({ n, side }, i) => (
          <g key={`${side}-${i}`} className={`pitch-node ${side}`}>
            <circle
              cx={n.x}
              cy={n.y}
              r="4.6"
              fill={ppsColor(n.pps)}
              stroke={side === 'home' ? '#fff' : 'rgba(255,255,255,0.45)'}
              strokeWidth="0.5"
            />
            <text x={n.x} y={n.y + 1.3} className="node-pps">
              {n.pps.toFixed(2).replace(/^0/, '')}
            </text>
            <text x={n.x} y={n.y + 9} className="node-name">
              {surname(n.name)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
