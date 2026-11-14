import type { ReactNode } from "react";
import { POINT_BUDGET, sumPoints, type Allocation } from "../api";

export interface AllocItem {
  uri: string;
  label: string;
  meta?: ReactNode; // badges, tasks, etc. shown under the label
}

interface Props {
  items: AllocItem[];
  allocation: Allocation;
  onChange: (a: Allocation) => void;
  maxSkills?: number;
}

/** Spend exactly POINT_BUDGET points. 0 points = skill not chosen. */
export default function PointAllocator({ items, allocation, onChange, maxSkills }: Props) {
  const spent = sumPoints(allocation);
  const left = POINT_BUDGET - spent;
  const chosen = Object.values(allocation).filter((p) => p > 0).length;

  const set = (uri: string, points: number) => {
    const p = Math.max(0, Math.min(points, (allocation[uri] ?? 0) + left));
    onChange({ ...allocation, [uri]: p });
  };

  const canAddSkill = !maxSkills || chosen < maxSkills;

  return (
    <div className="allocator">
      <div className={`budget ${left === 0 ? "complete" : ""}`}>
        <div className="budget-pips" aria-hidden>
          {Array.from({ length: POINT_BUDGET }, (_, i) => (
            <span key={i} className={i < spent ? "pip on" : "pip"} />
          ))}
        </div>
        <div className="budget-text">
          <strong>{left}</strong> of {POINT_BUDGET} points left
          {maxSkills ? (
            <span className="muted">
              {" "}
              · {chosen} of max {maxSkills} skills
            </span>
          ) : null}
        </div>
      </div>

      <ul className="alloc-list">
        {items.map((item) => {
          const p = allocation[item.uri] ?? 0;
          const blocked = p === 0 && !canAddSkill;
          return (
            <li key={item.uri} className={p > 0 ? "chosen" : blocked ? "blocked" : ""}>
              <div className="alloc-label">
                <div className="skill-name">{item.label}</div>
                {item.meta && <div className="alloc-meta">{item.meta}</div>}
              </div>
              <div className="alloc-controls">
                <button
                  className="btn icon"
                  aria-label={`Remove a point from ${item.label}`}
                  disabled={p === 0}
                  onClick={() => set(item.uri, p - 1)}
                >
                  −
                </button>
                <div className="alloc-pips" role="group" aria-label={`${item.label}: ${p} points`}>
                  {Array.from({ length: POINT_BUDGET }, (_, i) => {
                    const target = i + 1;
                    const reachable = target <= p + left && !blocked;
                    return (
                      <button
                        key={i}
                        className={`pip-btn ${i < p ? "on" : ""}`}
                        disabled={!reachable && i >= p}
                        title={`${target} point${target > 1 ? "s" : ""}`}
                        aria-label={`Set ${item.label} to ${target} points`}
                        onClick={() => set(item.uri, target === p ? 0 : target)}
                      />
                    );
                  })}
                </div>
                <button
                  className="btn icon"
                  aria-label={`Add a point to ${item.label}`}
                  disabled={left === 0 || blocked}
                  onClick={() => set(item.uri, p + 1)}
                >
                  +
                </button>
                <span className="alloc-num">{p}</span>
              </div>
            </li>
          );
        })}
      </ul>
      {maxSkills && !canAddSkill && (
        <p className="hint">You've chosen {maxSkills} skills. Take all points off one to choose another.</p>
      )}
    </div>
  );
}
