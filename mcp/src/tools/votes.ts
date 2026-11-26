/**
 * get_legislator_votes (spec §6.1, §12.5): recorded votes from the site's vote files. A member's
 * file names votes by POSITION in the shared index, and positions move between builds, so both
 * files must match vote-files.json (the hashes of one deploy) or nothing is reported.
 * Results are read from the stored value, never re-derived from tallies or wording.
 */
import { MismatchError, need, UnavailableError, type Loader } from "../data";
import type { FederalVoteIndex, GaVoteIndex, Member, Meta, MembersIndex, VoteFiles, VoteSlice } from "../types";
import { fail, GA_PASS_RULE, ok, type ToolResult } from "../util";
import { findMember, loadMembers, ordinal, sessionKey } from "./legislators";

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

const CODES: Record<string, string> = {
  Y: "Yea", N: "Nay", NV: "Not Voting", P: "Present", A: "Absent", E: "Excused", O: "Other",
};
const UPDATING = "VoteGA's voting records are updating. Try again in a few minutes.";

/** An index and a member's slice from the same build, or null when they cannot be matched yet. */
async function votePair<I>(loader: Loader, indexFile: string, sliceFile: string) {
  // Second pass: the cached manifest or files straddle a deploy, so go to the origin for all three.
  for (const fresh of [false, true]) {
    const manifest = await need<VoteFiles>(loader, "vote-files.json", { fresh });
    const want = [manifest.files[indexFile], manifest.files[sliceFile]];
    if (!want[0] || !want[1]) {
      if (fresh) throw new UnavailableError(`vote-files.json does not list ${sliceFile}`);
      continue;
    }
    try {
      const [index, slice] = await Promise.all([
        need<I>(loader, `data/${indexFile}`, { sha256: want[0], fresh }),
        need<VoteSlice>(loader, `data/${sliceFile}`, { sha256: want[1], fresh }),
      ]);
      return { index, slice };
    } catch (err) {
      if (!(err instanceof MismatchError)) throw err;
    }
  }
  return null;
}

type Vote = { position: number; date: string | null; [key: string]: unknown };

function answer(
  m: Member,
  meta: Meta,
  loader: Loader,
  votes: Vote[],
  covers: string,
  where: string,
  limit: number,
): ToolResult {
  votes.sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "") || b.position - a.position);
  const shown = votes.slice(0, limit).map(({ position: _position, ...v }) => v);
  return ok({
    summary:
      `${m.name}: ${votes.length} recorded vote(s) ${where}` +
      (votes.length > limit ? `; showing the ${limit} most recent.` : ".") +
      " Not Voting, Absent and Excused are not positions for or against.",
    legislator: { id: m.key, name: m.name, party: m.party, chamber: m.chamber, district: m.district },
    record_covers: covers,
    ...(m.level === "state" ? { pass_rule: GA_PASS_RULE } : {}),
    total: votes.length,
    votes: shown,
    as_of: meta.metadata.generatedAt,
    source_url: m.votegaUrl ?? "https://www.votega.org/",
    license: "CC BY-SA 4.0",
  }, loader.stale);
}

function noRecord(m: Member, meta: Meta, why: string): ToolResult {
  return ok({
    summary: `VoteGA has no voting record for ${m.name} ${why}. That is not a statement about how they voted.`,
    total: 0,
    votes: [],
    as_of: meta.metadata.generatedAt,
    source_url: m.votegaUrl ?? "https://www.votega.org/",
    license: "CC BY-SA 4.0",
  });
}

export async function getLegislatorVotes(
  loader: Loader,
  input: { id: string; session?: string; limit?: number },
): Promise<ToolResult> {
  const meta = await need<Meta>(loader, "meta.json");
  const members = await loadMembers(loader);
  const m = findMember(members.all, input.id);
  if (!m) return fail(`No legislator with id ${input.id}. Use an id from search_legislators.`);
  const limit = Math.min(Math.max(input.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);
  const path = m.slices.votes;
  if (!path) return noRecord(m, meta, "in its data");
  return m.level === "federal"
    ? federalVotes(loader, meta, members.live, m, path, input.session, limit)
    : stateVotes(loader, meta, m, path, input.session, limit);
}

async function federalVotes(
  loader: Loader,
  meta: Meta,
  live: MembersIndex,
  m: Member,
  path: string,
  session: string | undefined,
  limit: number,
): Promise<ToolResult> {
  const current = live.metadata.federal.congress;
  if (session !== undefined && session.trim().replace(/(st|nd|rd|th)$/i, "") !== String(current)) {
    return fail(
      `This server covers votes of the current Congress (${current}) only. Earlier Congresses are published at ` +
        "https://github.com/Votega/ga-federal-legislators.",
    );
  }
  const pair = await votePair<FederalVoteIndex>(loader, "federal-votes-index.json", path);
  if (!pair) return fail(UPDATING);
  const { index, slice } = pair;
  const votes: Vote[] = Object.entries(slice.compact).flatMap(([key, code]) => {
    const position = Number(key);
    const row = index.rows[position];
    if (!row) return [];
    const [chamber, date, billType, billNumber, title, motion, result, yea, nay, , , nominees] = row;
    return [{
      position,
      date: date || null,
      bill: billType && billNumber ? `${billType.toUpperCase()} ${billNumber}` : null,
      title,
      motion: index.motions[motion] ?? null,
      chamber: chamber === "H" ? "House" : "Senate",
      vote: CODES[code] ?? code,
      result: result === "P" ? "Passed" : result === "F" ? "Failed" : result || null,
      yea,
      nay,
      ...(nominees ? { nominees_in_this_vote: nominees } : {}),
    }];
  });
  const congress = index.metadata.congress;
  const covers = `${congress ? ordinal(congress) : "current"} Congress`;
  return answer(m, meta, loader, votes, covers, `in the ${covers}`, limit);
}

async function stateVotes(
  loader: Loader,
  meta: Meta,
  m: Member,
  path: string,
  session: string | undefined,
  limit: number,
): Promise<ToolResult> {
  const prefixOf = (p: string) => /^(ga-bienniums\/[^/]+\/)/.exec(p)?.[1] ?? "";
  const wanted = session === undefined ? null : sessionKey(session);
  let pair = await votePair<GaVoteIndex>(loader, `${prefixOf(path)}ga-votes-index.json`, path);
  if (!pair) return fail(UPDATING);
  let sessionFilter = wanted;
  if (wanted && !pair.index.metadata.sessions?.some((s) => s.id === wanted)) {
    // Not in this file: an earlier General Assembly, frozen under its own tag.
    if (!/^\d{4}_\d{2}$/.test(wanted)) return fail(`VoteGA has no votes for session ${session}.`);
    const prefix = `ga-bienniums/${wanted}/`;
    const manifest = await need<VoteFiles>(loader, "vote-files.json");
    if (!manifest.files[`${prefix}ga-votes-index.json`]) return fail(`VoteGA has no votes for session ${session}.`);
    const frozenSlice = `${prefix}ga-votes/${path.slice(path.lastIndexOf("/") + 1)}`;
    if (!manifest.files[frozenSlice]) return noRecord(m, meta, `in session ${wanted}`);
    pair = await votePair<GaVoteIndex>(loader, `${prefix}ga-votes-index.json`, frozenSlice);
    if (!pair) return fail(UPDATING);
    sessionFilter = null; // the tag names the whole biennium
  }
  const { index, slice } = pair;
  const votes: Vote[] = Object.entries(slice.compact).flatMap(([key, code]) => {
    const position = Number(key);
    const v = index.votes[index.voteIds[position]];
    if (!v || (sessionFilter && v.session !== sessionFilter)) return [];
    return [{
      position,
      date: v.date,
      bill: v.bill,
      title: v.title,
      motion: v.motionText,
      chamber: v.chamber,
      vote: CODES[code] ?? code,
      result: v.result,
      yea: v.yea,
      nay: v.nay,
      session: v.session,
      billUrl: v.billUrl,
    }];
  });
  const covers = sessionFilter ? `session ${sessionFilter}` : (index.metadata.biennium ?? "current General Assembly");
  const where = sessionFilter ? `in ${covers}` : `in the ${covers} General Assembly`;
  return answer(m, meta, loader, votes, covers, where, limit);
}
