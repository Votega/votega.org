# Archived scripts (retired, kept for fast fallback)

Scripts here are **no longer part of any live workflow**. They are retained so a
superseded pipeline can be restored quickly if its replacement regresses. Git history
would preserve them regardless; this folder makes the fallback path explicit.

## `generate_ga_votes_data.py` — retired 2026-10-04

The Open States producer of `assets/data/ga-member-votes.json`. **Replaced by
`scripts/generate_ga_votes_soap.py --no-overlay`** (the legis.ga.gov SOAP web service),
which is the official source: no API key, no 250/day quota, roll calls back to 2001, and
member resolution by `legisGaGovId` (collision-proof) instead of Open States' surname
matcher. The cutover was validated at 100% per-member Yea/Nay agreement on every roll
call both sources share. See `reference_ga_soap_webservices` (agent memory) and
`GA-VOTES-LEGIS-SCRAPE-DESIGN.md` for the full validation record.

### To fall back to Open States

1. `git mv scripts/archive/generate_ga_votes_data.py scripts/generate_ga_votes_data.py`
   (it imports `from lib.*`, which only resolve when it sits in `scripts/`).
2. In `.github/workflows/update-ga-votes.yml`, revert the "Generate GA vote data" step to
   `python scripts/generate_ga_votes_data.py assets/data/ga-member-votes.json`, and
   restore its `env: OPENSTATES_API_KEY` plus the `full_refresh` dispatch input.
3. Confirm the `OPENSTATES_API_KEY` repo secret is still set.

The two producers write the **same compact v2 schema** (`scripts/lib/votes_schema.py`),
so nothing downstream needs to change on a fallback. The one caveat is the voteId key
format (`"<voteId>-<legislationId>"` for SOAP vs `"ocd-vote/<uuid>"` for Open States) —
opaque to consumers, but a mixed-history file is avoided by letting the next full run
rewrite it entirely.
