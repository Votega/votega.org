# ga-federal-legislators

Georgia's federal congressional delegation — U.S. Senate and House members and their roll-call voting history — published by [VoteGA.org](https://votega.org).

Files are updated automatically whenever the source data changes in the [votega.org](https://github.com/Votega/votega.org) repository.

---

## Files

| File | Description |
|------|-------------|
| `data/members.json` | Georgia's current U.S. Senators and Representatives |
| `data/votes.json` | Roll-call vote records for Georgia's federal delegation, current Congress |

---

## `data/members.json`

### Top-level structure

```json
{
  "metadata": {
    "generatedAt": "2026-07-16T12:00:00+00:00",
    "source": "Congress.gov API, filtered to Georgia from votega.org current-members.json",
    "sourceGeneratedAt": "2026-07-16T08:19:05.444117",
    "count": 17
  },
  "members": [ ... ]
}
```

`members` is filtered from votega.org's full Congress.gov roster down to `state === "Georgia"` — 2 Senators plus the current U.S. House delegation. Counts shift with special elections, resignations, and appointments.

### Member object

```json
{
  "bioguideId": "W000790",
  "name": "Warnock, Raphael G.",
  "firstName": "Raphael",
  "lastName": "Warnock",
  "honorificName": "Mr.",
  "partyName": "Democratic",
  "state": "Georgia",
  "terms": { "item": [ { "chamber": "Senate", "startYear": 2021 } ] },
  "currentMember": true,
  "birthYear": "1969",
  "depiction": {
    "imageUrl": "https://www.congress.gov/img/member/w000790_200.jpg",
    "attribution": "..."
  },
  "contactInfo": {
    "officeAddress": "717 Hart Senate Office Building  Washington, DC 20510",
    "phoneNumber": "(202) 224-3643",
    "city": "Washington",
    "district": "DC",
    "zipCode": 20510
  },
  "officialWebsiteUrl": "https://www.warnock.senate.gov",
  "leadership": [],
  "committees": [ "Senate Committee on Agriculture, Nutrition, and Forestry", "..." ],
  "sponsoredLegislation": { "count": 283, "url": "https://api.congress.gov/v3/member/W000790/sponsored-legislation" },
  "cosponsoredLegislation": { "count": 1270, "url": "..." },
  "recentSponsored": [ { "type": "S", "number": "4962", "title": "...", "introducedDate": "2026-07-14", "latestAction": { "actionDate": "2026-07-14", "text": "..." }, "policyArea": null, "billUrl": "https://www.congress.gov/bill/119th-congress/senate-bill/4962" } ],
  "dataUpdatedAt": "2026-07-16T08:19:05.444117"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `bioguideId` | string | Congress.gov's stable member ID — primary key, also used as the join key into `votes.json` |
| `name`, `firstName`, `lastName`, `honorificName` | string | |
| `partyName` | string | `"Democratic"`, `"Republican"`, or `"Independent"` |
| `terms.item[]` | object[] | Term history; `terms.item[0].chamber` is `"Senate"` or `"House of Representatives"` |
| `currentMember` | boolean | |
| `birthYear` | string | |
| `depiction.imageUrl` | string | Official portrait |
| `contactInfo` | object | DC office address/phone; fields present depend on what Congress.gov reports |
| `officialWebsiteUrl` | string \| null | |
| `leadership[]` | object[] | Current leadership positions only (e.g. Speaker, Whip); empty array if none |
| `committees[]` | string[] | Full committee names, from `unitedstates/congress-legislators`; empty array if unavailable |
| `sponsoredLegislation`, `cosponsoredLegislation` | object | `{ count, url }` — counts only, not full bill lists |
| `recentSponsored[]` | object[] | Up to 20 most recent bills sponsored in the current Congress — see below |
| `dataUpdatedAt` | string | ISO timestamp of when votega.org last enriched this member's detail record |

#### `recentSponsored[]`

```json
{
  "type": "S",
  "number": "4962",
  "title": "A bill to establish an Office of Water Supply, Water Conservation, and Drought Resiliency ...",
  "introducedDate": "2026-07-14",
  "latestAction": { "actionDate": "2026-07-14", "text": "Read twice and referred to the Committee on Environment and Public Works." },
  "policyArea": null,
  "billUrl": "https://www.congress.gov/bill/119th-congress/senate-bill/4962"
}
```

`policyArea` is `null` when Congress.gov hasn't classified the bill yet.

---

## `data/votes.json`

Published as-is from votega.org's `federal-member-votes.json` — no filtering needed, since it's already scoped to Georgia's delegation.

### Top-level structure

```json
{
  "metadata": {
    "generatedAt": "2026-07-12T10:40:16.510045",
    "congress": 119,
    "sessionName": "119th Congress",
    "source": "Congress.gov API + Clerk of House + Senate.gov",
    "totalVotes": 196
  },
  "votes": { "H2026_0181": { ... } },
  "memberVotes": { "A000372": [ { "voteId": "H2026_0181", "vote": "Yea" } ] }
}
```

### `votes{}` — keyed by vote ID

```json
{
  "bill": "S. 1003",
  "billUrl": "https://www.congress.gov/bill/119th-congress/senate-bill/1003",
  "title": "Lulu's Law",
  "motionText": "On Motion to Suspend the Rules and Pass",
  "date": "2026-05-20",
  "yea": 401,
  "nay": 6,
  "chamber": "House",
  "result": "Pass"
}
```

`yea`/`nay` are chamber-wide totals (all voting members, not just Georgia's). `chamber` is `"House"` or `"Senate"`. `result` is `"Pass"` or `"Fail"`.

#### Vote ID format

| Pattern | Example | Meaning |
|---|---|---|
| `H{year}_{roll}` | `H2026_0181` | House roll call, Clerk of House vote number, zero-padded to 4 digits |
| `S{congress}_{session}_{roll}` | `S119_1_00024` | Senate roll call, zero-padded to 5 digits |

### `memberVotes{}` — keyed by `bioguideId`

```json
[
  { "voteId": "H2026_0181", "vote": "Yea" },
  { "voteId": "H2026_0193", "vote": "Yea" }
]
```

Only covers votes cast by Georgia's own delegation — a House vote array never contains a Senate roll call and vice versa, since a member only votes in their own chamber. `vote` is one of `"Yea"`, `"Nay"`, `"Not Voting"`, `"Absent"` (Congress.gov's `"Present"` is normalized to `"Not Voting"`; `"Excused"` is normalized to `"Absent"`).

---

## How data is updated

Files in this repo are pushed automatically from [Votega/votega.org](https://github.com/Votega/votega.org) via a GitHub Actions workflow (`.github/workflows/publish-federal-delegation-to-ga-federal-legislators.yml`). It runs whenever `current-members.json` or `federal-member-votes.json` changes on `main`, and can also be triggered manually.

Source data comes from the [Congress.gov API](https://api.congress.gov), the Clerk of the House's roll-call XML, and Senate.gov's roll-call XML, via `scripts/generate_current_members_data.py` and `scripts/generate_federal_votes_data.py` in the votega.org repo.

---

## Data notes

- **`recentSponsored` and `committees` are Georgia-specific enrichment.** votega.org's full national roster only fetches per-member sponsored-legislation detail for the Georgia delegation, to avoid 500+ extra Congress.gov API calls on every run — that's why it's present here on every member.
- **`votes.json` only records roll calls tied to enacted legislation.** It's built by walking public laws passed in the current Congress back to their roll-call votes, not every procedural vote taken.
- **Committee names** come from the community-maintained [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators) project, not Congress.gov directly.
- This dataset covers the **119th Congress** only.
