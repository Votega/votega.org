/**
 * Index loading. The Worker reads only the files build_mcp_index.py publishes under
 * https://www.votega.org/assets/data/mcp/ (spec §5.1); no user input ever becomes part of a URL
 * except a validated 3-digit ZIP prefix.
 *
 * Two cache layers (spec §5.3):
 * - Cloudflare's edge cache for the subrequest (`cf.cacheTtl`), per file family;
 * - a module-scope memo, so a warm isolate parses each file once per TTL (Phase 0, §12.11).
 * If the upstream fetch fails, the last parsed copy is served and the result is flagged stale.
 */

export const DATA_BASE = "https://www.votega.org/assets/data/mcp/";

export type Loader = {
  /** The parsed file, or null when it does not exist (404). Throws when unavailable. */
  load<T = unknown>(path: string): Promise<T | null>;
  /** True once any load in this request fell back to a stale copy. */
  readonly stale: boolean;
};

/** Seconds each file family may be cached (spec §5.3). */
export function ttlFor(path: string): number {
  if (path === "meta.json") return 300;
  if (path.startsWith("zip/") || path === "counties-index.json") return 86400;
  return 3600;
}

const ALLOWED = /^(meta|members-index|counties-index|local-officials-index)\.json$|^zip\/\d{3}\.json$/;

type Memo = { at: number; data: unknown };
const memo = new Map<string, Memo>();

export class UnavailableError extends Error {}

/** A loader for one request, backed by the shared memo. `nowMs` is read inside the request. */
export function httpLoader(nowMs: number, fetcher: typeof fetch = fetch): Loader {
  let stale = false;
  return {
    get stale() {
      return stale;
    },
    async load<T>(path: string): Promise<T | null> {
      if (!ALLOWED.test(path)) throw new Error(`not an index path: ${path}`);
      const ttl = ttlFor(path);
      const hit = memo.get(path);
      if (hit && nowMs - hit.at < ttl * 1000) return hit.data as T | null;
      try {
        const res = await fetcher(DATA_BASE + path, {
          cf: { cacheTtl: ttl, cacheEverything: true },
          headers: { accept: "application/json" },
        } as RequestInit);
        if (res.status === 404) {
          memo.set(path, { at: nowMs, data: null });
          return null;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as T;
        memo.set(path, { at: nowMs, data });
        return data;
      } catch (err) {
        if (hit) {
          stale = true;
          return hit.data as T | null;
        }
        throw new UnavailableError(`VoteGA data is unavailable right now (${path}: ${String(err)})`);
      }
    },
  };
}

/** Test helper: a loader over in-memory documents (missing path = 404). */
export function fixtureLoader(files: Record<string, unknown>): Loader {
  return {
    stale: false,
    async load<T>(path: string) {
      return (path in files ? files[path] : null) as T | null;
    },
  };
}

/** Clears the module memo (tests only). */
export function clearMemo() {
  memo.clear();
}
