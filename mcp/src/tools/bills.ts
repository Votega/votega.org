/**
 * search_bills and get_bill (spec §6.1, §12.14). Bills are keyed session + identifier (numbers
 * restart each General Assembly) or legislationId. The default is the current General Assembly:
 * every session the catalog marks live. A missing file means "unavailable", never "no bills".
 */
import { need, type Loader } from "../data";
import type { BillCatalog, BillDetail, BillRow, BillSession, BillShard, BillTokens, Member, Meta, MembersIndex } from "../types";
import { asOf, fail, GA_PASS_RULE, ok, SITE, tokens, type ToolResult } from "../util";

// The stage's steps named by position, as the bills page names them.
function stageOut(row: { identifier: string }, stage: NonNullable<BillDetail["bills"][string]["stage"]>) {
  const origin = /^S/.test(row.identifier) ? "Senate" : "House";
  const other = origin === "House" ? "Senate" : "House";
  const names = stage.path === "short"
    ? ["Filed", "Adoption"]
    : [`${origin} committee`, `${origin} floor`, `${other} committee`, `${other} floor`, "Final version", "Governor"];
  return {
    kind: stage.kind,
    label: stage.label,
    steps: stage.steps.map(([state, headline, detail], i) => ({ stage: names[i], state, headline, detail: detail || undefined })),
  };
}

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

/** "2025_26", "2025-2026" or "2026-special" -> the catalog's session id. */
function sessionKey(input: string): string {
  const s = input.trim().toLowerCase();
  const years = /^(\d{4})-\d{2}(\d{2})$/.exec(s);
  if (years) return `${years[1]}_${years[2]}`;
  return s.replace(/-(special|ss)$/, "_ss");
}

/** No session: the current General Assembly, regular session first. Unknown session: null. */
function pickSessions(catalog: BillCatalog, session: string | undefined): BillSession[] | null {
  if (session === undefined) {
    return catalog.sessions.filter((s) => s.live).sort((a, b) => Number(a.active) - Number(b.active));
  }
  const hit = catalog.sessions.filter((s) => s.session === sessionKey(session));
  return hit.length ? hit : null;
}

const noSession = (catalog: BillCatalog) =>
  fail(`VoteGA has no bills for that session. Sessions: ${catalog.sessions.map((s) => s.session).join(", ")}.`);

/** "hb1", "HB 1", "H.B. 1EX" -> the identifiers it can mean, plain number first. */
export function identifierForms(input: string): string[] | null {
  const m = /^([hs][br])(\d+)(ex)?$/.exec(input.toLowerCase().replace(/[\s.]/g, ""));
  if (!m) return null;
  const base = `${m[1].toUpperCase()} ${Number(m[2])}`;
  return m[3] ? [`${base}EX`] : [base, `${base}EX`];
}

type Found = { session: BillSession; row: BillRow; names: Record<string, string> };

async function rowsOf(loader: Loader, session: BillSession, paths: string[]): Promise<Found[]> {
  const shards = await Promise.all(paths.map((p) => need<BillShard>(loader, p)));
  return shards.flatMap((s) => s.bills.map((row) => ({ session, row, names: s.sponsorNames })));
}

/** Bills in a session whose titles carry every word (word beginnings count). */
async function wordMatches(loader: Loader, session: BillSession, words: string[]): Promise<Found[]> {
  const perShard = await Promise.all(
    session.shards.map(async (shard) => {
      const table = await need<BillTokens>(loader, shard.tokensPath);
      const wanted = words.filter((w) => !table.metadata.ignored.includes(w));
      let hits: Set<number> | undefined;
      for (const w of wanted) {
        const found = new Set<number>();
        for (const [key, positions] of Object.entries(table.tokens)) {
          if (key === w || (w.length >= 3 && key.startsWith(w))) positions.forEach((p) => found.add(p));
        }
        hits = hits ? new Set([...hits].filter((p: number) => found.has(p))) : found;
      }
      if (!hits?.size) return [];
      const ids = new Set([...hits].map((p) => table.identifiers[p]));
      return (await rowsOf(loader, session, [shard.path])).filter((f) => ids.has(f.row.identifier));
    }),
  );
  return perShard.flat();
}

function votegaUrl(catalog: BillCatalog, row: BillRow): string {
  return catalog.metadata.votegaUrlTemplate
    .replace("{identifier}", encodeURIComponent(row.identifier))
    .replace("{legislationId}", String(row.legislationId));
}

/** State member records by legisGaGovId, sitting and former. */
async function membersByGid(loader: Loader): Promise<Map<number, Member>> {
  const [live, former] = await Promise.all([
    loader.load<MembersIndex>("members-index.json"),
    loader.load<MembersIndex>("former-members-index.json"),
  ]);
  const out = new Map<number, Member>();
  for (const m of [...(former?.members ?? []), ...(live?.members ?? [])]) {
    if (m.level === "state") out.set(Number(m.key.slice(3)), m);
  }
  return out;
}

const secondRole = (chamber: "lower" | "upper") => (chamber === "upper" ? "Senate sponsor" : "House sponsor");

/** How a member is on a bill, or null when they are not. */
function sponsorRole(row: BillRow, gid: number): string | null {
  const author = row.sponsors.find(([g]) => g === gid);
  if (author) return author[1] ? "primary sponsor" : "co-sponsor";
  const second = row.secondChamberSponsor;
  return second?.[0] === gid ? secondRole(second[1]) : null;
}

async function sponsorGid(loader: Loader, id: string): Promise<number | null> {
  const s = id.trim().toLowerCase();
  const direct = /^(?:ga:)?(\d+)$/.exec(s);
  if (direct) return Number(direct[1]);
  if (!/^vg-ga-p-\d{6}$/.test(s)) return null;
  for (const [gid, m] of await membersByGid(loader)) if (m.vgId === s) return gid;
  return null;
}

export async function searchBills(
  loader: Loader,
  input: { query?: string; session?: string; status?: string; sponsor_id?: string; subject?: string; limit?: number },
): Promise<ToolResult> {
  const meta = await need<Meta>(loader, "meta.json");
  const catalog = await need<BillCatalog>(loader, "bills/sessions.json");
  const sessions = pickSessions(catalog, input.session);
  if (!sessions) return noSession(catalog);
  const limit = Math.min(Math.max(input.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);

  let gid: number | null = null;
  if (input.sponsor_id !== undefined) {
    gid = await sponsorGid(loader, input.sponsor_id);
    if (gid === null) return fail("sponsor_id must be a state legislator: ga:<legisGaGovId> or a VoteGA vgId.");
  }

  const query = input.query?.trim() ?? "";
  const forms = query ? identifierForms(query) : null;
  const words = tokens(query).filter((w) => w.length > 1);
  const everything = async () =>
    (await Promise.all(sessions.map((s) => rowsOf(loader, s, s.shards.map((x) => x.path))))).flat();
  let found: Found[];
  if (forms) {
    const type = forms[0].split(" ")[0];
    const typed = await Promise.all(
      sessions.map((s) => rowsOf(loader, s, s.shards.filter((x) => x.type === type).map((x) => x.path))),
    );
    found = typed
      .flat()
      .filter((f) => forms.includes(f.row.identifier))
      .sort((a, b) => forms.indexOf(a.row.identifier) - forms.indexOf(b.row.identifier));
  } else if (words.length) {
    found = (await Promise.all(sessions.map((s) => wordMatches(loader, s, words)))).flat();
  } else {
    found = await everything();
  }

  const status = input.status?.trim().toLowerCase();
  const subject = input.subject?.trim().toLowerCase();
  found = found
    .filter((f) => gid === null || sponsorRole(f.row, gid) !== null)
    .filter((f) => !status || (f.row.status ?? "").toLowerCase().includes(status))
    .filter((f) => !subject || f.row.subjects.some((s) => s.toLowerCase().includes(subject)));
  if (!forms) found.sort((a, b) => (b.row.statusDate ?? "").localeCompare(a.row.statusDate ?? ""));

  const covered = sessions.map((s) => s.session).join(" and ");
  const results = found.slice(0, limit).map(({ session, row, names }) => ({
    session: session.session,
    identifier: row.identifier,
    legislationId: row.legislationId,
    title: row.title,
    status: row.status,
    statusDate: row.statusDate,
    primary_sponsors: row.sponsors.filter(([, primary]) => primary).map(([g]) => names[String(g)] ?? `ga:${g}`),
    ...(gid === null ? {} : { sponsor_role: sponsorRole(row, gid) }),
    votegaUrl: votegaUrl(catalog, row),
  }));
  const summary = found.length
    ? `${found.length} bill(s) or resolution(s) match in session(s) ${covered}` +
      (found.length > limit ? `; showing ${limit}.` : ".") +
      " Use get_bill for votes, sponsors and a plain-language summary link."
    : `No bills or resolutions match in session(s) ${covered}. Keyword search reads titles only.`;
  return ok({
    summary,
    total: found.length,
    results,
    as_of: asOf(loader, meta),
    source_url: `${SITE}/ga-bills.html`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}

export async function getBill(
  loader: Loader,
  input: { identifier?: string; session?: string; legislation_id?: number },
): Promise<ToolResult> {
  if ((input.identifier === undefined) === (input.legislation_id === undefined)) {
    return fail("Give either identifier (with an optional session) or legislation_id.");
  }
  const meta = await need<Meta>(loader, "meta.json");
  const catalog = await need<BillCatalog>(loader, "bills/sessions.json");
  const sessions =
    input.legislation_id !== undefined && input.session === undefined
      ? [...catalog.sessions].sort((a, b) => Number(b.live) - Number(a.live))
      : pickSessions(catalog, input.session);
  if (!sessions) return noSession(catalog);

  type Hit = Found & { detailPath: string };
  const search = async (type: string | null, match: (r: BillRow) => boolean): Promise<Hit | undefined> => {
    for (const session of sessions) {
      for (const shard of session.shards.filter((s) => !type || s.type === type)) {
        const row = (await rowsOf(loader, session, [shard.path])).find((f) => match(f.row));
        if (row) return { ...row, detailPath: shard.detailPath };
      }
    }
    return undefined;
  };
  let hit: Hit | undefined;
  if (input.legislation_id !== undefined) {
    hit = await search(null, (r) => r.legislationId === input.legislation_id);
  } else {
    const forms = identifierForms(input.identifier!);
    if (!forms) return fail('identifier must look like "HB 1", "SR 25" or "HB 1EX".');
    // The plain number in any session beats the special session's EX form.
    for (const form of forms) {
      hit = await search(form.split(" ")[0], (r) => r.identifier === form);
      if (hit) break;
    }
  }
  if (!hit) {
    return fail(
      `No bill matches in session(s) ${sessions.map((s) => s.session).join(", ")}. Check the number, or give a session.`,
    );
  }

  const { session, row, names } = hit;
  const detail = (await need<BillDetail>(loader, hit.detailPath)).bills[row.identifier];
  if (!detail) return fail("VoteGA's data for that bill is unavailable right now. Try again later.");
  const members = await membersByGid(loader);
  const page = votegaUrl(catalog, row);
  const person = (g: number) => ({
    id: `ga:${g}`,
    name: members.get(g)?.name ?? names[String(g)] ?? null,
    votegaUrl: members.get(g)?.votegaUrl ?? null,
  });
  const second = row.secondChamberSponsor;
  const commons = detail.commonsUrl
    ? {
        label: catalog.metadata.commonsLabel,
        url: detail.commonsUrl,
        id: `bill:${detail.commonsUrl.split("/bills/")[1]}`,
      }
    : null;
  return ok({
    summary:
      `${row.identifier} (${session.session}): ${row.title ?? "untitled"}. ` +
      `Status: ${row.status ?? "unknown"}${row.statusDate ? ` (${row.statusDate.slice(0, 10)})` : ""}.` +
      (detail.stage?.label ? ` Where it is: ${detail.stage.label}.` : ""),
    bill: {
      session: session.session,
      identifier: row.identifier,
      legislationId: row.legislationId,
      type: row.billType,
      title: row.title,
      status: row.status,
      ...(row.officialStatus ? { official_status: row.officialStatus } : {}),
      statusDate: row.statusDate,
      subjects: row.subjects,
      sponsors: row.sponsors.map(([g, primary]) => ({ ...person(g), primary })),
      ...(second
        ? { second_chamber_sponsor: { ...person(second[0]), chamber: second[1], role: secondRole(second[1]) } }
        : {}),
      passage_votes: detail.passageVotes,
      governor_action: detail.governorAction,
      ...(detail.stage ? { stage: stageOut(row, detail.stage) } : {}),
      ...(detail.committees?.length ? { committees: detail.committees } : {}),
      billUrl: detail.billUrl,
      textUrl: detail.textUrl,
      votegaUrl: page,
    },
    ...(detail.passageVotes.length ? { pass_rule: GA_PASS_RULE } : {}),
    georgia_commons: commons,
    as_of: asOf(loader, meta),
    source_url: page,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
