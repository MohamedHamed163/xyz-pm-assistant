import type { TopicInfo } from "./api";

export const DOC_TYPE_LABEL: Record<string, string> = { brd: "BRD", prd: "PRD", proposal: "Proposal" };

/** A topic dropdown; "Unclassified" is highlighted because it blocks publishing. */
export function TopicSelect({
  topics,
  value,
  onChange,
  disabled,
  label,
  placeholder,
}: {
  topics: TopicInfo[];
  value: string | null;
  onChange: (topic: string) => void;
  disabled?: boolean;
  label: string;
  placeholder?: string;
}) {
  return (
    <select
      className={`topic-select ${value === "unclassified" ? "unclassified" : ""}`}
      value={value ?? ""}
      onChange={(e) => e.target.value && onChange(e.target.value)}
      disabled={disabled}
      aria-label={label}
    >
      {value === null && <option value="">{placeholder ?? "Set topic…"}</option>}
      {topics.map((t) => (
        <option key={t.key} value={t.key}>
          {t.key === "unclassified" ? "⚠ Unclassified" : t.label}
        </option>
      ))}
    </select>
  );
}

export function whoCanRead(topics: TopicInfo[], key: string): string {
  const t = topics.find((x) => x.key === key);
  if (!t) return "";
  if (key === "unclassified") return "Only CEO and PM until a topic is chosen";
  return t.roles.join(", ");
}
