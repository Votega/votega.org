#!/usr/bin/env python3
"""One HTTP fetcher for every build-time data generator.

CLAUDE.md states the policy plainly:

    Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx —
    these are non-retryable client errors.

Before this module there were seven hand-rolled implementations of that policy
across scripts/, following three mutually incompatible interpretations of it:

    generate_current_members_data.py   429 + 5xx     (correct)
    generate_ga_bills_data.py          429 + 5xx     (correct)
    generate_ga_campaign_finance.py    429 + 5xx     (correct)
    generate_curated_ga_bills.py       5xx only      <- ran daily against Open
                                                        States, whose quota
                                                        response is 429: the one
                                                        status it would not retry
    generate_fec_data.py               429 only
    generate_ga_congress_trades.py     no retries at all
    generate_federal_votes_data.py     no retries at all

Every one of them returns None on failure and lets the caller continue with a
partial dataset, so a transient blip becomes committed data loss. Consolidating
here means the policy is fixed in one place and cannot drift again.

The review counted seven fetchers; migrating them turned up five more with the
same shape (generate_ga_members_data.py, generate_presidential_laws.py,
generate_scotus_decisions.py, generate_vp_tie_votes.py, and the YAML fetch in
generate_current_members_data.py). generate_ga_members_data.py mattered most:
like generate_curated_ga_bills.py it retried 5xx only, and it is the *daily*
Open States job, so it gave up immediately on exactly the 429 that a drained
quota produces.

Deliberately NOT migrated:

    generate_ga_campaign_finance.py          PeachFile, POST-based
    generate_ga_campaign_finance_history.py  PeachFile, POST-based

This module is GET-only and both already implement the documented policy
correctly. They keep their own clients until this grows POST support.

Addresses CODEBASE-REVIEW-2026-08-18.md finding 2.4.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`, so the `lib` package resolves):

    from lib.http import fetch_json, fetch_raw
"""

import json
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5
DEFAULT_USER_AGENT = 'votega.org/1.0'

#: Statuses worth retrying. 429 = rate limited, 5xx = server-side fault.
#: Everything else in 4xx is a client error and will fail identically on retry.
RETRYABLE = lambda code: code == 429 or code >= 500  # noqa: E731


def _redact(text, secret):
    if secret and text:
        return text.replace(secret, '***')
    return text


def _request(url, headers=None, timeout=DEFAULT_TIMEOUT):
    merged = {'User-Agent': DEFAULT_USER_AGENT}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, headers=merged)
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_bytes(url, headers=None, retries=DEFAULT_RETRIES,
                backoff=DEFAULT_BACKOFF, rate_limit_backoff=None,
                timeout=DEFAULT_TIMEOUT, redact=None, label=None,
                quiet_statuses=(), verbose=True):
    """Fetch a URL and return raw bytes, or None on failure.

    Retries on 429 and 5xx with linear backoff (backoff * attempt); returns
    None immediately on any other 4xx. Network-level exceptions are retried.

    Args:
        rate_limit_backoff: seconds to wait on a 429 specifically. Some APIs
            (the FEC's, for one) rate limit per hour, so the generic 5s ramp is
            useless there and a much longer wait is the only thing that helps.
            Defaults to `backoff` when not given.
        redact: a secret (API key) to strip from anything logged.
        quiet_statuses: statuses to not log at all, e.g. (404,) when a miss is
            an expected, uninteresting outcome.
        label: short human-readable name for log lines; defaults to the URL.
    """
    shown = _redact(label or url, redact)
    rl_backoff = rate_limit_backoff if rate_limit_backoff is not None else backoff

    for attempt in range(1, retries + 1):
        try:
            with _request(url, headers, timeout) as resp:
                return resp.read()

        except urllib.error.HTTPError as exc:
            if exc.code not in quiet_statuses and verbose:
                detail = ''
                try:
                    body = exc.read().decode('utf-8', errors='replace')
                    if body:
                        detail = ' - %s' % _redact(body[:300], redact)
                except Exception:
                    pass
                print('  HTTP %s: %s%s' % (exc.code, exc.reason, detail))

            if RETRYABLE(exc.code) and attempt < retries:
                wait = (rl_backoff if exc.code == 429 else backoff) * attempt
                if verbose:
                    reason = 'rate limited' if exc.code == 429 else 'server error'
                    print('  %s - retrying in %ss (attempt %s/%s)'
                          % (reason, wait, attempt, retries))
                time.sleep(wait)
                continue

            # 4xx (non-429), or retries exhausted.
            return None

        except Exception as exc:  # timeouts, DNS, connection resets, bad JSON body
            if verbose:
                print('  Error fetching %s: %s' % (shown[:120], exc))
            if attempt < retries:
                wait = backoff * attempt
                if verbose:
                    print('  Retrying in %ss (attempt %s/%s)' % (wait, attempt, retries))
                time.sleep(wait)
                continue
            return None

    return None


def fetch_json(url, **kwargs):
    """Fetch a URL and decode it as JSON. Returns None on failure.

    A body that arrives but does not parse is treated as a failed fetch rather
    than raising, so callers keep the single `if data is None` contract.
    """
    raw = fetch_bytes(url, **kwargs)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        if kwargs.get('verbose', True):
            label = _redact(kwargs.get('label') or url, kwargs.get('redact'))
            print('  Malformed JSON from %s: %s' % (label[:120], exc))
        return None


#: Backwards-compatible alias — several generators call their local helper
#: `fetch_raw`, and keeping the name lets them delegate without touching call sites.
fetch_raw = fetch_bytes
