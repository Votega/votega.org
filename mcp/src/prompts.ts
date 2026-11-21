/**
 * MCP prompts (spec §8): templates a user picks from their assistant's prompt menu. They add no
 * data; they tell the model which tool to call and how to report what it returns, so the answer
 * keeps VoteGA's rules (a ZIP or county is not a district, cite source_url, stay neutral).
 *
 * Arguments are typed by the user and interpolated into the message, so they are stripped of
 * control characters and bounded like any other untrusted text.
 */
import type { Loader } from "./data";
import type { CountiesIndex } from "./types";
import { norm, stripControls } from "./util";

export const MAX_ARG = 80;

export type PromptResult = { messages: { role: "user"; content: { type: "text"; text: string } }[] };

const RULES =
  "Rules for your answer: report only what the tool returns, and cite each source_url and the " +
  "data's as_of date. VoteGA is nonpartisan: show party as a fact, and never endorse, rate, rank or " +
  "compare anyone. If the tool says something is unavailable or not covered, say so plainly; do not " +
  "fill the gap from memory.";

function arg(s: string): string {
  const t = stripControls(s).replace(/\s+/g, " ").trim();
  return t.length > MAX_ARG ? t.slice(0, MAX_ARG) : t;
}

function message(text: string): PromptResult {
  return { messages: [{ role: "user", content: { type: "text", text } }] };
}

/** A Georgia county name ("Newton", "newton county", "DeKalb") to its 5-digit FIPS, or null. */
export async function countyFips(loader: Loader, name: string): Promise<string | null> {
  const q = norm(name).replace(/county$/, "");
  if (!q) return null;
  try {
    const idx = await loader.load<CountiesIndex>("counties-index.json");
    for (const [fips, c] of Object.entries(idx?.counties ?? {})) if (norm(c.name) === q) return fips;
  } catch {
    // Index unavailable: fall through and let the model ask for a ZIP.
  }
  return null;
}

export async function whoRepresentsArea(loader: Loader, area: string): Promise<PromptResult> {
  const a = arg(area);
  let call: string;
  // County FIPS first: Georgia's are 13xxx and no Georgia ZIP starts with 13 (they are 30-31, 398-399).
  if (/^13\d{3}$/.test(a)) {
    call = `Call find_my_representatives with county_fips "${a}".`;
  } else if (/^\d{5}$/.test(a)) {
    call = `Call find_my_representatives with zip "${a}".`;
  } else {
    const fips = await countyFips(loader, a);
    call = fips
      ? `"${a}" is the Georgia county with FIPS code ${fips}. Call find_my_representatives with county_fips "${fips}".`
      : `"${a}" is not a 5-digit ZIP code or a Georgia county name VoteGA recognizes. Ask me for my ZIP ` +
        `code or county instead of guessing, then call find_my_representatives.`;
  }
  return message(
    `Who represents ${a ? `"${a}"` : "my area"} in Georgia? ${call}\n\n` +
      "List the Georgia Senate, Georgia House and U.S. House districts it returns, each with its " +
      "estimated share and its member, and both U.S. senators. A ZIP code or county can span several " +
      "districts: list every one returned, never pick one as mine, and say that only a street address " +
      "decides which district a voter is in. Show a vacant or suspended seat exactly as the tool " +
      "reports it. If it is a PO-box ZIP, say it has no districts and ask for the ZIP of a street address.\n\n" +
      RULES,
  );
}

export function localOfficials(place: string): PromptResult {
  const p = arg(place);
  const call = /^13\d{3}$/.test(p)
    ? `Call find_local_officials with county_fips "${p}".`
    : `Call find_local_officials with place "${p}".`;
  return message(
    `Who are the local officials for "${p}" in Georgia? ${call}\n\n` +
      "List the commission or council members with their seats, and the sheriff if one is returned. " +
      "List anyone who has been elected but not yet taken office separately, with the date their term " +
      "begins. VoteGA reviews local rosters by hand and covers only some places: if the place is not " +
      "covered, say so and name nobody. If it returns more than one place (a city and a county can " +
      "share a name), show each one under its own heading.\n\n" +
      RULES,
  );
}
