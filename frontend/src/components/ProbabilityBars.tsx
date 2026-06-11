import { motion } from 'framer-motion';
import { flag } from '../types';

interface Props {
  home: string;
  away: string;
  pHome: number;
  pDraw: number;
  pAway: number;
}

function Bar({
  label,
  pct,
  kind,
}: {
  label: string;
  pct: number;
  kind: 'home' | 'draw' | 'away';
}) {
  return (
    <div className="prob-row">
      <span className="who">{label}</span>
      <div className="prob-track">
        <motion.div
          className={`prob-fill ${kind}`}
          animate={{ width: `${pct * 100}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
        />
      </div>
      <motion.span
        className="pct"
        key={pct.toFixed(3)}
        initial={{ opacity: 0.4 }}
        animate={{ opacity: 1 }}
      >
        {(pct * 100).toFixed(1)}%
      </motion.span>
    </div>
  );
}

export default function ProbabilityBars({ home, away, pHome, pDraw, pAway }: Props) {
  return (
    <div className="prob-block">
      <Bar label={`${flag(home)} ${home}`} pct={pHome} kind="home" />
      <Bar label="Draw" pct={pDraw} kind="draw" />
      <Bar label={`${flag(away)} ${away}`} pct={pAway} kind="away" />
    </div>
  );
}
