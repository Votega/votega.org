/** Shared helpers: the result envelope (spec §6), input hygiene and name matching. */

export const SITE = "https://www.votega.org";
export const LICENSE = "CC BY-SA 4.0";
export const MAX_STRING = 500;
// C0 controls except tab and newline, DEL, and the Unicode line/paragraph separators.
const CONTROL_CHARS = new RegExp("[\u0000-\u0008\u000b-\u001f\u007f\u2028\u2029]", "g");

/** Remove control characters (keeping tab and newline), with no length cap. */
export function stripControls(s: string): string {
  return s.replace(CONTROL_CHARS, "");
}

/** Strip control characters and bound every string (spec §9: dataset text is untrusted). */
export function clean<T>(value: T): T {
  if (typeof value === "string") {
    const s = stripControls(value);
    return (s.length > MAX_STRING ? s.slice(0, MAX_STRING - 1) + "…" : s) as T;
  }
  if (Array.isArray(value)) return value.map(clean) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, clean(v)])) as T;
  }
  return value;
}

/** Georgia General Assembly pass thresholds: a summary of scripts/lib/ga_vote_rules.py. */
export const GA_PASS_RULE =
  "Georgia passage is not decided by yea versus nay. A bill needs a majority of all seats (91 of 180 " +
  "in the House, 29 of 56 in the Senate). Constitutional amendments and local property-tax exemption " +
  "acts need two-thirds (120 House, 38 Senate). A few procedural motions need only a majority of those " +
  "voting, and a few results follow the official record instead. Report the stored result; never " +
  "recompute it.";

export type Envelope = {
  summary: string;
  as_of: string | null;
  source_url: string;
  license: string;
  stale?: true;
  [key: string]: unknown;
};

export type ToolResult = {
  content: { type: "text"; text: string }[];
  isError?: boolean;
};

/** Every result: a one-line summary first, then compact JSON (spec §6.1 design rules). */
export function ok(body: Envelope, stale = false): ToolResult {
  const out = clean(stale ? { ...body, stale: true as const } : body);
  return { content: [{ type: "text", text: JSON.stringify(out) }] };
}

/** The answer's `as_of`: the oldest data it read, or the index build when it read only meta.json. */
export function asOf(loader: { asOf: string | null }, meta: { metadata: { generatedAt: string } }): string {
  return loader.asOf ?? meta.metadata.generatedAt;
}

export function fail(message: string): ToolResult {
  return { content: [{ type: "text", text: clean(message) }], isError: true };
}

/** Letters and digits only, lower case: "DeKalb" == "dekalb", "O'Steen" == "osteen". */
export function norm(s: string | null | undefined): string {
  return (s ?? "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

/** Lower-case word tokens, accents removed. */
export function tokens(s: string | null | undefined): string[] {
  return (s ?? "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** The request's UTC date, 'YYYY-MM-DD'. */
export function isoDate(nowMs: number): string {
  return new Date(nowMs).toISOString().slice(0, 10);
}
