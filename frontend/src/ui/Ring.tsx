import { useEffect, useState } from "react";

export type Segment = { key: string; value: number; label: string };

const R = 40;
const C = 2 * Math.PI * R;
// A thin gap between parts keeps them apart at small sizes.
const GAP = 3;

/** The time budget as a ring: way there, the visit, the way back and what is left. */
export function Ring({
  segments,
  total,
  size = 92,
  center,
  unit,
}: {
  segments: Segment[];
  total: number;
  size?: number;
  center: string | number;
  unit: string;
}) {
  // Parts grow from zero on the first paint.
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const sum = Math.max(total, segments.reduce((a, s) => a + Math.max(0, s.value), 0), 1);
  let offset = 0;
  return (
    <svg className="ring" width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={segments.map((s) => `${s.label}: ${Math.round(s.value)}`).join(", ")}>
      <circle className="ring-track" cx="50" cy="50" r={R} />
      {segments
        .filter((s) => s.value > 0)
        .map((s) => {
          const len = Math.max(0, (s.value / sum) * C - GAP);
          const el = (
            <circle
              key={s.key}
              className={"ring-seg ring-" + s.key}
              cx="50"
              cy="50"
              r={R}
              strokeDasharray={`${shown ? len : 0} ${C}`}
              strokeDashoffset={-offset}
            />
          );
          offset += (s.value / sum) * C;
          return el;
        })}
      <text x="50" y="49" className="ring-num">
        {center}
      </text>
      <text x="50" y="66" className="ring-unit">
        {unit}
      </text>
    </svg>
  );
}

export function RingLegend({ segments, unit }: { segments: Segment[]; unit: string }) {
  return (
    <ul className="ring-legend">
      {segments.map((s) => (
        <li key={s.key}>
          <i className={"ring-dot ring-" + s.key} aria-hidden="true" />
          <span>{s.label}</span>
          <b>
            {Math.round(s.value)} {unit}
          </b>
        </li>
      ))}
    </ul>
  );
}
