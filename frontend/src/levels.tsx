import type { Level } from "./api";

export const LEVELS: Level[] = ["client_shared", "team", "management"];

export const LEVEL_META: Record<Level, { label: string; who: string }> = {
  client_shared: { label: "Client", who: "Team, CEO and the client" },
  team: { label: "Team", who: "PM, developers, QA and CEO" },
  management: { label: "Management", who: "PM and CEO only" },
};

export function LevelPicker({
  value,
  onChange,
  disabled,
  name,
}: {
  value: Level | null;
  onChange: (level: Level) => void;
  disabled?: boolean;
  name: string;
}) {
  return (
    <div className="level-picker" role="radiogroup" aria-label={`Who can see ${name}`}>
      {LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          role="radio"
          aria-checked={value === level}
          className={`level-btn level-${level} ${value === level ? "on" : ""}`}
          title={LEVEL_META[level].who}
          disabled={disabled}
          onClick={() => onChange(level)}
        >
          {LEVEL_META[level].label}
        </button>
      ))}
    </div>
  );
}

export function summaryText(summary: Record<Level, number>, clientName: string | null) {
  const parts = [];
  if (summary.client_shared)
    parts.push(`${summary.client_shared} visible to the client${clientName ? ` (${clientName})` : ""}`);
  if (summary.team) parts.push(`${summary.team} team`);
  if (summary.management) parts.push(`${summary.management} management only`);
  return parts.join(" · ");
}
