import { motion } from 'framer-motion';
import type { Scoreline } from '../types';

export default function TopScorelines({ scorelines }: { scorelines: Scoreline[] }) {
  return (
    <div className="scoreline-chips">
      {scorelines.map((s, i) => (
        <motion.div
          className="sc"
          key={s.score}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.04 }}
        >
          <b>{s.score}</b>
          <span>{(s.prob * 100).toFixed(1)}%</span>
        </motion.div>
      ))}
    </div>
  );
}
