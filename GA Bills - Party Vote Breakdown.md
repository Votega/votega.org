# Plan: Party Vote Breakdown on GA Bills Page

## Context
The ga-bills.html page shows a vote bar (yes/no counts) for each bill's passage votes, but gives no indication of how Republicans vs. Democrats voted. The underlying data to support this exists — `ga-members.json` has party per member, `ga-member-votes.json` has individual member votes per vote event — but the two are never joined and `ga-bills.json` only carries aggregate yea/nay/other totals.

The goal is to add a party breakdown line below each vote bar: e.g. "R: 28 yes · 2 no | D: 6 yes · 16 no".

## Approach

### 1. Create `scripts/enrich_bills_with_party_votes.py`

New build-time script. Takes three positional args:
```
python scripts/enrich_bills_with_party_votes.py \
  assets/data/ga-bills.json \
  assets/data/ga-member-votes.json \
  assets/data/ga-members.json
```

Logic:
1. Load `ga-members.json` → build `party_map: {ocd-person-id: party}` (e.g. `"Democratic"`, `"Republican"`)
2. Load `ga-member-votes.json`
   - Invert `memberVotes` (`{personId: [{voteId, vote}]}`) into `vote_roster: {voteId: {personId: vote}}` — O(totalVotes), one pass
   - Build `vote_index: {(bill_identifier, motionText): voteId}` from the `votes` dict
3. Load `ga-bills.json`
4. For each bill → each `passageVote`:
   - Look up `voteId` via `vote_index[(bill.identifier, pv.motionText)]`
   - If found, iterate `vote_roster[voteId]`, join with `party_map`, tally into `{Republican: {yea, nay, other}, Democratic: {yea, nay, other}}`
   - Add `partyTally` key to the passageVote object
5. Write the enriched `ga-bills.json` in-place (pretty-printed, same structure)
6. Print a summary line: bills enriched, passageVotes matched vs. unmatched

**Pattern to reuse:** `build_vote_record()` in `scripts/generate_curated_ga_bills.py:118–149` already does the party-tally logic. Mirror that approach (party buckets: yea/nay/other; only tally known parties).

partyTally schema added to each passageVote:
```json
"partyTally": {
  "Republican":  { "yea": 28, "nay": 2,  "other": 1 },
  "Democratic":  { "yea": 6,  "nay": 16, "other": 2 }
}
```
Only include parties with at least one vote. Omit `Independent` if zero (true in GA practically).

### 2. Update `.github/workflows/update-ga-votes.yml`

Add two steps after "Commit and push generated data":

**Step A — Enrich bills with party votes:**
```yaml
- name: Enrich GA bills with party vote tallies
  run: python scripts/enrich_bills_with_party_votes.py assets/data/ga-bills.json assets/data/ga-member-votes.json assets/data/ga-members.json
```

**Step B — Commit enriched bills:**
```yaml
- name: Commit enriched GA bills data
  run: |
    set -e
    git add -f assets/data/ga-bills.json
    if git diff --cached --quiet; then
      echo "No changes to ga-bills.json"
    else
      git commit -m "Enrich GA bills with party vote tallies"
      for attempt in 1 2 3; do
        git pull --rebase origin main && git push && break
        echo "Push attempt $attempt failed, retrying..."
        sleep 5
      done
    fi
```

Note: `ga-members.json` is always current because `update-ga-members.yml` runs one hour earlier (07:00 UTC vs 08:00 UTC).

### 3. Update `voteBarHtml()` in `ga-bills.html`

After the existing `.vote-bar-sub` div, append a party breakdown line when `v.partyTally` is present.

In `voteBarHtml(v)` (currently ga-bills.html:404–429), add before the closing `</div>`:

```javascript
let partyLine = '';
if (v.partyTally) {
  const r = v.partyTally.Republican  || {};
  const d = v.partyTally.Democratic  || {};
  const rParts = [], dParts = [];
  if ((r.yea || 0) + (r.nay || 0) + (r.other || 0) > 0)
    rParts.push('<span style="color:#b91c1c">R: ' + (r.yea||0) + ' yes · ' + (r.nay||0) + ' no</span>');
  if ((d.yea || 0) + (d.nay || 0) + (d.other || 0) > 0)
    dParts.push('<span style="color:#1d4ed8">D: ' + (d.yea||0) + ' yes · ' + (d.nay||0) + ' no</span>');
  if (rParts.length || dParts.length)
    partyLine = '<div class="vote-bar-party">' + [...rParts, ...dParts].join('<span style="color:#9ca3af"> &nbsp;|&nbsp; </span>') + '</div>';
}
```

Add CSS class (in the `<style>` block near `.vote-bar-sub`):
```css
.vote-bar-party { font-size: 0.75rem; color: #6b7280; margin-top: 2px; }
```

### 4. One-time manual run

After implementation, run the enrichment script locally to populate `partyTally` in the current `ga-bills.json` and commit it — otherwise the UI shows nothing until the next Sunday workflow run.

```
python scripts/enrich_bills_with_party_votes.py assets/data/ga-bills.json assets/data/ga-member-votes.json assets/data/ga-members.json
```

## Files to modify
- **Create:** `scripts/enrich_bills_with_party_votes.py`
- **Modify:** `.github/workflows/update-ga-votes.yml` (add 2 steps after the commit step)
- **Modify:** `ga-bills.html` (add `partyLine` to `voteBarHtml`, add `.vote-bar-party` CSS)
- **Modify (data):** `assets/data/ga-bills.json` (one-time local run to enrich existing data)

## Verification
1. Run `python scripts/enrich_bills_with_party_votes.py ...` locally, confirm summary output shows matched votes
2. Spot-check `ga-bills.json` — open any bill with a `passageVote` and confirm `partyTally` is populated with non-zero counts
3. Open `ga-bills.html` in browser (Jekyll dev server or directly), expand a bill card and confirm the party line renders below the vote bar
4. Test SB 513 specifically — its House Vote #843 (failed) should show R/D breakdown
5. Confirm bills with no vote data (no matching voteId) don't show a party line and don't error