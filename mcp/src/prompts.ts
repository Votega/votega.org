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

export function explainBill(bill: string, session?: string): PromptResult {
  const b = arg(bill).replace(/"/g, "");
  const s = arg(session ?? "").replace(/"/g, "");
  return message(
    `Explain the Georgia bill "${b}" in plain language. ` +
      `Call get_bill with identifier "${b}"${s ? ` and session "${s}"` : ""}.\n\n` +
      "Then get Georgia Commons' summary. Georgia Commons is an independent project: if its MCP server " +
      "(mcp.georgiacommons.org/mcp) is connected, call its fetch tool with the id in georgia_commons.id; " +
      "otherwise open georgia_commons.url if you can read web pages. From the section headed \"Summaries " +
      "written by Georgia Commons\", show the one-sentence headline, \"Plain-language summary\" and \"What it " +
      "does\". That section follows the bill text, so read further if the first result stops before it. Leave " +
      "out \"Why it matters\" and the other parts.\n\n" +
      "Put it under its own heading that says it is a summary AI-written by Georgia Commons, and say with it " +
      "that it is not part of the bill, is not official and may contain errors. Link georgia_commons.url and, " +
      "for the wording that counts, the bill text at bill.textUrl (or bill.billUrl if that is empty). " +
      "Quote the bill itself when quoting the law. About the summary: never present it as the bill's own text or as VoteGA's. " +
      "If you can do neither, or there is no summary, give the title, status and official links, say that no " +
      "summary was retrieved, and do not write one from the title or from memory.\n\n" +
      "Before you show a summary, check the summary against the bill text (the same Georgia Commons document " +
      "usually carries it above the summaries; else read bill.textUrl). Compare who it applies to, amounts, " +
      "deadlines, penalties, exceptions and what triggers each duty. A limit may come from the title and the " +
      "Code section being amended rather than from the changed words. Where the summary says something broader, " +
      "narrower or different, say so under \"Where the summary differs from the bill\", quoting the bill; do not " +
      "silently rewrite the summary. If you could not read the bill text, say the summary was not checked against " +
      "the bill text. If you found no difference, say only that you found none: do not call the summary verified " +
      "or accurate.\n\n" +
      "Also report the status, sponsors, passage votes and governor action get_bill returns. Do not say " +
      "whether the bill is good or bad, or what its sponsors intended.\n\n" +
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
