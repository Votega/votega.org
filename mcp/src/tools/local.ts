/**
 * search_local_government (spec §6.1): topic mentions found in county and city agendas and
 * minutes. A mention is not an action, and only some places are scanned, so an empty result is
 * never reported as nothing having happened.
 */
import { need, type Loader } from "../data";
import type { MentionsIndex, Meta } from "../types";
import { fail, isoDate, ok, SITE, type ToolResult } from "../util";
import { matchPlaces } from "./officials";

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

export async function searchLocalGovernment(
  loader: Loader,
  input: { place?: string; county_fips?: string; topic?: string; since?: string; limit?: number },
  nowMs: number,
): Promise<ToolResult> {
  const [meta, index] = await Promise.all([
    need<Meta>(loader, "meta.json"),
    need<MentionsIndex>(loader, "local-mentions-index.json"),
  ]);
  const { topics, places } = index.metadata;
  const topic = input.topic?.trim().toLowerCase();
  if (topic !== undefined && !topics.some((t) => t.slug === topic)) {
    return fail(`Unknown topic. VoteGA's topics: ${topics.map((t) => t.slug).join(", ")}.`);
  }
  const limit = Math.min(Math.max(input.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);

  let slugs: Set<string> | null = null;
  if (input.place !== undefined) {
    const all = Object.entries(places).map(([slug, p]) => ({ slug, name: p.name, type: p.type }));
    slugs = new Set(matchPlaces(all, input.place).map((p) => p.slug));
  }

  const found = index.mentions
    .filter((m) => !slugs || slugs.has(m.place))
    .filter((m) => input.county_fips === undefined || places[m.place]?.countyFips === input.county_fips)
    .filter((m) => topic === undefined || m.topic === topic)
    .filter((m) => input.since === undefined || (m.date ?? "") >= input.since);

  const today = isoDate(nowMs);
  const label = new Map(topics.map((t) => [t.slug, t.label ?? t.slug]));
  const mentions = found.slice(0, limit).map((m) => ({
    place: places[m.place]?.name ?? m.place,
    place_slug: m.place,
    county_fips: places[m.place]?.countyFips ?? null,
    topic: label.get(m.topic) ?? m.topic,
    date: m.date,
    upcoming: !!m.date && m.date > today,
    body: m.body,
    docType: m.docType,
    terms: m.terms,
    confidence: m.confidence,
    sourceUrl: m.sourceUrl,
    minutesUrl: m.minutesUrl,
    votegaUrl: places[m.place]?.votegaUrl ?? null,
  }));
  const summary = found.length
    ? `${found.length} mention(s) match, newest first` + (found.length > limit ? `; showing ${limit}.` : ".") +
      " A mention means a topic's keywords appear in an agenda or minutes; it is not an action taken. Check the source document."
    : "VoteGA's index has no matching mentions. It scans only some counties and cities, so this does not mean nothing happened.";
  const only = new Set(mentions.map((m) => m.votegaUrl));
  return ok({
    summary,
    total: found.length,
    mentions,
    topics: topics.map((t) => ({ topic: t.slug, label: t.label, mentions: t.count })),
    meaning: index.metadata.meaning,
    as_of: meta.metadata.generatedAt,
    source_url: only.size === 1 && mentions[0].votegaUrl ? mentions[0].votegaUrl : `${SITE}/local/topics/`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
