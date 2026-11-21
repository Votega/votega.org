/**
 * get_data_freshness (spec §6.1): per dataset, its own stamp, the day its job last checked the
 * source, the cadence, and whether it is older than usual by the site's own rule
 * (_data/data_freshness.yml, assets/scripts/freshness.js: measure from the newer of the stamp and
 * the check day).
 */
import type { Loader } from "../data";
import type { DatasetDates, Meta } from "../types";
import { fail, ok, SITE, type ToolResult } from "../util";

const DAY = 86_400_000;

export function olderThanUsual(d: DatasetDates, nowMs: number): boolean | null {
  if (d.neverFlagged || !d.windowDays) return null;
  const stamps = [d.generatedAt, d.checkedAt].filter(Boolean).map((s) => Date.parse(s!)).filter((n) => !isNaN(n));
  if (!stamps.length) return null;
  return nowMs - Math.max(...stamps) > d.windowDays * DAY;
}

export async function getDataFreshness(loader: Loader, nowMs: number): Promise<ToolResult> {
  const meta = await loader.load<Meta>("meta.json");
  if (!meta) return fail("VoteGA's data index is unavailable right now. Try again later.");
  const datasets = Object.fromEntries(
    Object.entries(meta.datasets).map(([name, d]) => [
      name,
      {
        as_of: d.generatedAt,
        last_checked: d.checkedAt,
        cadence: d.cadence,
        window_days: d.windowDays,
        hand_maintained: d.neverFlagged || d.review === "manual",
        older_than_usual: olderThanUsual(d, nowMs),
      },
    ]),
  );
  const old = Object.entries(datasets).filter(([, d]) => d.older_than_usual).map(([n]) => n);
  return ok({
    summary:
      `${Object.keys(datasets).length} datasets; ` +
      (old.length ? `older than usual: ${old.join(", ")}.` : "none is older than usual.") +
      ` Index built ${meta.metadata.generatedAt}; local officials last reviewed ${meta.localOfficialsLastReviewed ?? "unknown"}.`,
    index_built: meta.metadata.generatedAt,
    local_officials_last_reviewed: meta.localOfficialsLastReviewed,
    source_stamps: meta.sourceStamps,
    datasets,
    as_of: meta.metadata.generatedAt,
    source_url: `${SITE}/about-the-data/`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
