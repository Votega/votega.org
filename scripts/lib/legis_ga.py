#!/usr/bin/env python3
"""Client for the Georgia General Assembly site API (legis.ga.gov).

This is the official-source replacement for the Open States person-matching layer
that produces ga-member-votes.json. Every roll call it returns is keyed by the
legislature's OWN numeric member id (`member.id`), which is exactly the
`legisGaGovId` the project already crosswalks — so the surname-collision problem
Open States introduces (two Clarks, etc.) is gone by construction. See
GA-VOTES-LEGIS-SCRAPE-DESIGN.md (local/gitignored) for the full rationale.

Auth — the one subtlety
------------------------
The `/api/` endpoints are gated by a SHORT-LIVED ANONYMOUS bearer JWT (no login,
no user). Flow confirmed 2026-10-02:

    GET /api/authentication/token?key=<clientKey>&ms=<epoch_ms>   -> a ~5-min JWT
    ... then every data call sends  Authorization: Bearer <jwt>
    ... on a 401 (expiry) the token is re-minted

`<clientKey>` is the public client key baked into the SPA bundle (the `obscureKey`
constant in main.*.js). It is NOT a secret in any meaningful sense, but it also is
not ours to hardcode, so this client takes it from the environment
(`LEGIS_GA_CLIENT_KEY`) or the constructor.

Two ways to supply auth:
  * client_key / LEGIS_GA_CLIENT_KEY  -> the client mints and auto-refreshes.
    This is the normal path in GitHub Actions / local runs.
  * token / LEGIS_GA_TOKEN            -> use a pre-minted token as-is. Useful for
    testing against a captured token WITHOUT minting. Because an injected token
    cannot be refreshed (we weren't given the key), it will fail with a clear
    TokenUnavailable once it expires.

NOTE for in-agent use: programmatically *minting* the token trips Claude Code's
credential-exploration guardrail, so live mint/refresh runs in CI or locally, NOT
inside the agent sandbox. Unit-test the join/parse logic with injected fixtures;
reserve live mint for CI. (This is why the parsing functions below are pure and
take plain dicts — they're testable without any network.)

This client is GET+POST and stateful (holds a token), so it does not use
lib.http.fetch_json (GET-only, stateless, swallows 401). It follows the same
retry policy: retry 429/5xx, give up on other 4xx.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://www.legis.ga.gov/api"
TOKEN_ENDPOINT = "/authentication/token"
USER_AGENT = "votega.org/1.0 (+https://votega.org)"

DEFAULT_TIMEOUT = 45
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5
#: Tokens live ~5 min; re-mint a little early so a call never races the expiry.
TOKEN_TTL_SECONDS = 240
#: Courtesy pause between calls — this is an undocumented site API; be gentle.
DEFAULT_SLEEP = 0.5

#: legis.ga.gov chamber code -> the chamber strings used in ga-members.json /
#: id-crosswalk.json. `chamberType` (roster) and `chamber` (detail/vote) share it.
CHAMBER = {1: "House of Representatives", 2: "Senate"}
#: legis.ga.gov party code. Confirmed 2026-10-02 across both chambers + parties
#: (Adesanya D->0, Anderson R->1; Tonya Anderson D->0, Anavitarte R->1).
PARTY = {0: "Democratic", 1: "Republican"}


class LegisGaError(RuntimeError):
    """Any legis.ga.gov client failure."""


class TokenUnavailable(LegisGaError):
    """No usable token and none can be minted (no client key, or injected token
    expired and we have no key to refresh it)."""


class LegisGaClient:
    """Stateful, token-aware JSON client for legis.ga.gov.

    Example:
        client = LegisGaClient()                     # key from LEGIS_GA_CLIENT_KEY
        for bill in client.iter_legislation(1033):
            detail = client.legislation_detail(bill["legislationId"])
            for vid in vote_ids(detail):
                vote = client.vote_detail(vid)
    """

    def __init__(self, token=None, client_key=None, base_url=BASE_URL,
                 timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES,
                 backoff=DEFAULT_BACKOFF, sleep=DEFAULT_SLEEP, verbose=True):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.verbose = verbose

        self._injected = token or os.environ.get("LEGIS_GA_TOKEN") or None
        self._client_key = client_key or os.environ.get("LEGIS_GA_CLIENT_KEY") or None
        self._token = self._injected
        self._minted_at = time.monotonic() if self._injected else 0.0

    # -- token lifecycle --------------------------------------------------

    def _mint_token(self):
        """Mint a fresh anonymous JWT via the token endpoint. Requires a client key.

        Isolated here so the credential-sensitive call has one home. Raises
        TokenUnavailable when no client key is configured.
        """
        if not self._client_key:
            raise TokenUnavailable(
                "No legis.ga.gov client key. Set LEGIS_GA_CLIENT_KEY (the public "
                "SPA client key) to auto-mint, or inject a pre-minted LEGIS_GA_TOKEN."
            )
        # Retry the mint itself. It is the single point of failure for a whole run
        # and a long run re-mints every ~5 min, so a transient hiccup on the token
        # endpoint (an intermittent 401, a 429 masquerading as 401, a 5xx, or a
        # network blip) must not abort everything. A PERSISTENT 401 (rotated key)
        # still surfaces clearly after the retries are exhausted.
        last = None
        for attempt in range(1, self.retries + 1):
            url = "%s%s?%s" % (self.base_url, TOKEN_ENDPOINT, urllib.parse.urlencode(
                {"key": self._client_key, "ms": int(time.time() * 1000)}))  # fresh ms
            try:
                raw = self._raw_request("GET", url)
                body = raw.decode("utf-8").strip()
                # Response may be a bare JWT, a quoted string, or {token: ...}.
                try:
                    parsed = json.loads(body)
                    token = parsed if isinstance(parsed, str) else (
                        parsed.get("token") or parsed.get("accessToken")
                        or parsed.get("value"))
                except (ValueError, AttributeError):
                    token = body
                if not token:
                    raise TokenUnavailable("Token endpoint returned an unrecognized body.")
                self._token = token
                self._minted_at = time.monotonic()
                return token
            except urllib.error.HTTPError as exc:
                last = exc
                # 401 is retryable HERE specifically: the endpoint has been seen to
                # return it transiently, and a bad key fails the same way every time
                # so it just exhausts the retries and raises.
                if attempt < self.retries and (exc.code in (401, 429) or exc.code >= 500):
                    wait = self.backoff * attempt
                    self._log("  token mint HTTP %s — retrying in %ss (%s/%s)"
                              % (exc.code, wait, attempt, self.retries))
                    time.sleep(wait)
                    continue
                raise LegisGaError("token mint failed: HTTP %s" % exc.code) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = exc
                if attempt < self.retries:
                    wait = self.backoff * attempt
                    self._log("  token mint error: %s — retrying in %ss (%s/%s)"
                              % (exc, wait, attempt, self.retries))
                    time.sleep(wait)
                    continue
                raise LegisGaError("token mint failed: %s" % exc) from exc
        raise LegisGaError("token mint failed after %d attempts: %s"
                           % (self.retries, last))

    def _ensure_token(self, force=False):
        """Return a usable token, minting/refreshing when needed.

        An injected token is used as-is and never proactively re-minted (we have
        no key); it only fails lazily via a 401 -> TokenUnavailable.
        """
        fresh = self._token and (time.monotonic() - self._minted_at) < TOKEN_TTL_SECONDS
        if self._token and fresh and not force:
            return self._token
        if self._injected and not self._client_key:
            # Can't refresh an injected token; hand back what we have and let a
            # 401 surface a clear error if it has expired.
            return self._token
        return self._mint_token()

    # -- low-level request ------------------------------------------------

    def _raw_request(self, method, url, body=None, token=None):
        """One HTTP round trip. Raises urllib.error.HTTPError on HTTP status."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.legis.ga.gov/",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _request(self, method, path, params=None, body=None):
        """Authenticated JSON request with retry (429/5xx) and one auth refresh.

        Mirrors lib.http's policy — retry 429/5xx with linear backoff, give up on
        other 4xx — but adds the token header and a single re-mint-and-retry when a
        call comes back 401 (token expired mid-run).
        """
        url = "%s/%s" % (self.base_url, path.lstrip("/"))
        if params:
            url = "%s?%s" % (url, urllib.parse.urlencode(params))

        auth_refreshed = False
        for attempt in range(1, self.retries + 1):
            token = self._ensure_token()
            try:
                raw = self._raw_request(method, url, body=body, token=token)
                if self.sleep:
                    time.sleep(self.sleep)
                text = raw.decode("utf-8")
                # An empty 200 body is how this API signals "no content" (e.g. a
                # paginated endpoint asked past its last page). Return None rather
                # than letting json.loads choke on "" — callers treat None as "no
                # data"/end-of-results instead of crashing mid-run.
                return json.loads(text) if text.strip() else None
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and not auth_refreshed:
                    # Token expired or rejected: re-mint once and retry immediately.
                    if self._injected and not self._client_key:
                        raise TokenUnavailable(
                            "Injected LEGIS_GA_TOKEN was rejected (401) and no "
                            "LEGIS_GA_CLIENT_KEY is set to refresh it. Re-inject a "
                            "fresh token or provide the client key."
                        )
                    auth_refreshed = True
                    self._ensure_token(force=True)
                    continue
                if (exc.code == 429 or exc.code >= 500) and attempt < self.retries:
                    wait = self.backoff * attempt
                    self._log("  HTTP %s on %s — retrying in %ss (%s/%s)"
                              % (exc.code, path, wait, attempt, self.retries))
                    time.sleep(wait)
                    continue
                raise LegisGaError("HTTP %s on %s" % (exc.code, url)) from exc
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                if attempt < self.retries:
                    wait = self.backoff * attempt
                    self._log("  Error on %s: %s — retrying in %ss (%s/%s)"
                              % (path, exc, wait, attempt, self.retries))
                    time.sleep(wait)
                    continue
                raise LegisGaError("Failed on %s: %s" % (url, exc)) from exc
        raise LegisGaError("Exhausted retries on %s" % url)

    def _log(self, msg):
        if self.verbose:
            print(msg)

    # -- typed endpoints --------------------------------------------------

    def sessions(self):
        """All sessions: [{id, description, library, isCurrent, type, ...}]."""
        return self._request("GET", "/sessions")

    def members(self, session_id):
        """Full session roster: [{id, name, title, chamberType}]. NO district —
        use member_detail() for that."""
        return self._request("GET", "/members/search-options",
                             params={"sessionId": session_id})

    def member_detail(self, member_id, session_id, chamber):
        """Full member record incl. districtNumber, party, committees, bio."""
        return self._request("GET", "/members/detail/%s" % member_id,
                             params={"session": session_id, "chamber": chamber})

    def legislation_search(self, session_id, page_size=50, page=0, **filters):
        """One page of the bill list for a session. Returns
        {results:[{legislationId, ...}], resultCount:int} or None past the last
        page. The URL path is /Legislation/Search/{pageSize}/{pageIndex} — the
        second segment is a 0-based PAGE INDEX, not a row offset."""
        body = {
            "committeeIds": [], "documentTypes": [], "legislationTypes": [],
            "chamberTypes": [], "keywords": None, "legislationNumber": None,
            "sessionId": session_id, "sponsorIds": [], "titleIds": [],
            "currentStatus": None,
        }
        body.update(filters)
        return self._request("POST", "/Legislation/Search/%d/%d" % (page_size, page),
                             body=body)

    def iter_legislation(self, session_id, page_size=50):
        """Yield every bill record for a session, paginating Legislation/Search by
        PAGE INDEX. Stops when a page is empty/None or the known total is reached."""
        page = 0
        total = None
        while True:
            resp = self.legislation_search(session_id, page_size=page_size, page=page)
            results = (resp or {}).get("results") or []
            if total is None:
                total = (resp or {}).get("resultCount", 0)
            if not results:
                break
            for row in results:
                yield row
            page += 1
            if page * page_size >= (total or 0):
                break

    def legislation_detail(self, legislation_id):
        """Full bill record. The `votes` field lists this bill's roll calls (or
        None when it has none)."""
        return self._request("GET", "/legislation/detail/%s" % legislation_id)

    def vote_detail(self, vote_id):
        """A roll call: {votes:[{member:{id,name}, memberVoted}], legislation:[...],
        session:{...}}. `member.id` == legisGaGovId."""
        return self._request("GET", "/Vote/detail/%s" % vote_id)


# -- pure parse helpers (no network; unit-testable with fixtures) ---------

def vote_ids(legislation_detail):
    """Extract this bill's vote ids from a legislation_detail() response.

    The `votes` field is None when the bill has no roll calls. When populated its
    exact item shape is not yet confirmed from a live sample (every bill captured
    so far had `votes: null`), so pull an id defensively: accept a bare int/str, or
    an object with any of the id-ish keys legis uses elsewhere.
    """
    votes = (legislation_detail or {}).get("votes")
    if not votes:
        return []
    out = []
    for v in votes:
        if isinstance(v, (int, str)):
            out.append(v)
        elif isinstance(v, dict):
            vid = v.get("voteId") or v.get("id") or v.get("voteNumber")
            if vid is not None:
                out.append(vid)
    return out
