/**
 * One deterministic 3-domain SLO presentation shared by the Lesson Plan and
 * Lesson Notes. Both screens must show the same three items.
 *
 * The stored outcome is a single sentence from the backend, e.g.
 *   "By the end of the lesson, the learner should be able to: a) sort objects by colour only"
 * We keep the first stored outcome verbatim as the Cognitive item and derive the
 * Psychomotor / Affective items from the lesson's own atomic focus. No backend
 * value is changed; this is presentation only.
 */

export const SLO_PREFIX = "By the end of the lesson, the learner should be able to:";

export type SloDomain = "Cognitive" | "Psychomotor" | "Affective";

export interface SloItem {
  domain: SloDomain;
  text: string;
}

const HEADING_RE =
  /by the end of the (?:lesson|sub-strand),?\s*(?:the learner should|you will|the learner will)\s*be able to\s*:?/i;

function lowerFirst(text: string): string {
  const clean = text.trim().replace(/[.;,\s]+$/, "");
  if (!clean) return "";
  return clean[0].toLowerCase() + clean.slice(1);
}

function normaliseFocus(focus: string): string {
  const afterColon = focus.includes(":") ? focus.split(":").slice(1).join(":").trim() : focus;
  return lowerFirst(afterColon || focus)
    .replace(/\bonly\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function splitOutcomeItems(body: string): string[] {
  const withoutHeading = (body || "").replace(HEADING_RE, " ").trim();
  if (!withoutHeading) return [];
  return withoutHeading
    .split(/\n+|(?:\s*[a-z]\)\s*)|;\s*/i)
    .map((item) => item.replace(/^[-•*]\s*/, "").replace(/[.;,\s]+$/, "").trim())
    .filter(Boolean);
}

function withHeading(text: string): string {
  return `${SLO_PREFIX} ${lowerFirst(text)}`;
}

export function buildSloDomains(
  body: string,
  focus: string,
  sourceOutcomes: string[] = [],
): SloItem[] {
  const stored = splitOutcomeItems(body);
  const sourced = sourceOutcomes
    .flatMap((item) => splitOutcomeItems(item))
    .filter(Boolean);
  const focusText = normaliseFocus(focus);

  const cognitive = stored[0] || sourced[0] || `identify and describe objects when we ${focusText}`;
  const psychomotor = stored[1] || sourced[1] || focusText;
  const affective =
    stored[2] ||
    sourced[2] ||
    `share materials and take turns while we ${focusText}`;

  return [
    { domain: "Cognitive", text: withHeading(cognitive) },
    { domain: "Psychomotor", text: withHeading(psychomotor) },
    { domain: "Affective", text: withHeading(affective) },
  ];
}
