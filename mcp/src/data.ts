/**
 * Data loading. The Worker reads only listed files under https://www.votega.org/assets/data/:
 * the index files build_mcp_index.py publishes in mcp/ (spec §5.1), and, for votes and
 * scorecards, the site's own vote files (`data/…` paths, spec §5.2). No user input becomes part
 * of a URL except a validated 3-digit ZIP prefix; every other variable segment comes from an
 * index and still has to match the allowlist.
 *
 * Two cache layers (spec §5.3):
 * - Cloudflare's edge cache for the subrequest (`cf.cacheTtl`), per file family;
 * - a module-scope memo, so a warm isolate parses each file once per TTL (Phase 0, §12.11).
 * If the upstream fetch fails, the last parsed copy is served and the result is flagged stale.
 *
 * A caller may name the sha256 a file must have (vote-files.json). Different bytes are a
 * MismatchError and are never kept or served.
 */

export const SITE_DATA = "https://www.votega.org/assets/data/";
export const DATA_BASE = `${SITE_DATA}mcp/`;

export type LoadOptions = {
  /** The file must hash to this. */
  sha256?: string;
  /** Skip both caches and fetch from the origin. */
  fresh?: boolean;
};

export type Loader = {
  /** The parsed file, or null when it does not exist (404). Throws when unavailable. */
  load<T = unknown>(path: string, options?: LoadOptions): Promise<T | null>;
  /** True once any load in this request fell back to a stale copy. */
  readonly stale: boolean;
};

/** Seconds each file family may be cached (spec §5.3). */
export function ttlFor(path: string): number {
  if (path === "meta.json" || path === "vote-files.json") return 300;
  if (path.startsWith("zip/") || path === "counties-index.json") return 86400;
  if (path === "races-index.json" || path === "candidates-index.json") return 900;
  if (path === "local-mentions-index.json") return 21600;
  return 3600;
}

const ALLOWED = [
  /^(meta|members-index|former-members-index|counties-index|local-officials-index|local-mentions-index|races-index|candidates-index|resources|vote-files)\.json$/,
  /^zip\/\d{3}\.json$/,
  /^bills\/(sessions|\d{4}_(\d{2}|ss)-[A-Z]+(-detail|-tokens)?)\.json$/,
  /^data\/(ga|federal)-(votes-index|party-unity)\.json$/,
  /^data\/ga-votes\/[A-Za-z0-9-]+\.json$/,
  /^data\/federal-votes\/[A-Z]\d{6}\.json$/,
  /^data\/ga-bienniums\/\d{4}_\d{2}\/(ga-members|ga-votes-index|ga-party-unity|ga-votes\/[A-Za-z0-9-]+)\.json$/,
];

type Memo = { at: number; data: unknown; sha256?: string };
const memo = new Map<string, Memo>();

export class UnavailableError extends Error {}
export class MismatchError extends Error {}

/** A file a tool cannot answer without: missing means unavailable, never "no results". */
export async function need<T>(loader: Loader, path: string, options?: LoadOptions): Promise<T> {
  const doc = await loader.load<T>(path, options);
  if (!doc) throw new UnavailableError(`VoteGA data is unavailable right now (${path} is missing)`);
  return doc;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A loader for one request, backed by the shared memo. `nowMs` is read inside the request. */
export function httpLoader(nowMs: number, fetcher: typeof fetch = fetch): Loader {
  let stale = false;
  return {
    get stale() {
      return stale;
    },
    async load<T>(path: string, options: LoadOptions = {}): Promise<T | null> {
      if (!ALLOWED.some((a) => a.test(path))) throw new Error(`not an index path: ${path}`);
      const { sha256, fresh } = options;
      const ttl = ttlFor(path);
      const hit = memo.get(path);
      const usable = hit && (!sha256 || hit.sha256 === sha256) ? hit : undefined;
      if (!fresh && usable && nowMs - usable.at < ttl * 1000) return usable.data as T | null;
      try {
        const base = path.startsWith("data/") ? SITE_DATA + path.slice(5) : DATA_BASE + path;
        // A one-off query string passes every cache between here and the origin.
        const res = await fetcher(fresh ? `${base}?r=${nowMs}` : base, {
          cf: fresh ? { cacheTtl: 0 } : { cacheTtl: ttl, cacheEverything: true },
          headers: { accept: "application/json" },
        } as RequestInit);
        if (res.status === 404) {
          memo.set(path, { at: nowMs, data: null });
          return null;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (sha256 && (await sha256Hex(text)) !== sha256) throw new MismatchError(`${path} does not match`);
        const data = JSON.parse(text) as T;
        memo.set(path, { at: nowMs, data, sha256 });
        return data;
      } catch (err) {
        if (err instanceof MismatchError) throw err;
        if (usable) {
          stale = true;
          return usable.data as T | null;
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
    async load<T>(path: string, options: LoadOptions = {}) {
      if (!(path in files)) return null;
      if (options.sha256 && (await sha256Hex(JSON.stringify(files[path]))) !== options.sha256) {
        throw new MismatchError(`${path} does not match`);
      }
      return files[path] as T;
    },
  };
}

/** Clears the module memo (tests only). */
export function clearMemo() {
  memo.clear();
}
