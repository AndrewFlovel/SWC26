import { useI18n } from '../i18n';
import { flag } from '../types';

interface Props {
  home: string;
  away: string;
  matrix: number[][];
  maxGoalsShown?: number;
}

/** Heatmap of exact-score probabilities, blood-red intensity scale. */
export default function ScoreMatrix({ home, away, matrix, maxGoalsShown = 6 }: Props) {
  const { t } = useI18n();
  const n = Math.min(maxGoalsShown, matrix.length);
  const peak = Math.max(...matrix.slice(0, n).flatMap((row) => row.slice(0, n)), 1e-9);

  const cellStyle = (p: number) => {
    const t = Math.pow(p / peak, 0.7);
    return {
      background: `rgba(217, 4, 41, ${(t * 0.55).toFixed(3)})`,
      color: t > 0.55 ? '#fff' : undefined,
    };
  };

  return (
    <div className="matrix-wrap">
      <div className="axis-label">
        {t('matrixAxis', { home: `${flag(home)} ${home}`, away: `${flag(away)} ${away}` })}
      </div>
      <table className="matrix">
        <thead>
          <tr>
            <th />
            {Array.from({ length: n }, (_, j) => (
              <th key={j}>{j}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: n }, (_, i) => (
            <tr key={i}>
              <th>{i}</th>
              {Array.from({ length: n }, (_, j) => {
                const p = matrix[i][j];
                return (
                  <td key={j} style={cellStyle(p)}>
                    {(p * 100).toFixed(1)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
