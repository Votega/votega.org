## Safe keys

| To identify | Use | Notes |
|---|---|---|
| A person, across datasets and ID systems | `vgId` | VoteGA's person ID. In the [crosswalk](#vgid-votegas-person-id) only |
| A state legislator, across sessions | `legisGaGovId` | The General Assembly's own member number |
| A state legislator's votes within a session | member `id` | Opaque. Match it exactly; read nothing into its form |
| A member of Congress | `bioguideId` | |
| A bill | session **and** bill number, or `legislationId` | Bill numbers restart each General Assembly |
| A state roll call, per bill | `voteId` within its session | Form `<rollCallId>-<legislationId>` |
| A federal roll call | `voteId` within its Congress | `H<year>_<roll>` or `S<congress>_<session>_<roll>` |
| A race | race `id` with `cycle` | |
| A county | 5-digit FIPS, or VoteGA's slug | `data/county-codes.csv` maps them |
| An executive order | `number` | |
| A local government | `placeId` | For counties it matches the county slug |

The full account of state legislator identifiers is in [IDENTIFIERS.md](https://github.com/Votega/ga-legislators/blob/main/IDENTIFIERS.md).

## Do not use these as keys

- **Names.** Several unrelated Georgia legislators share surnames. Published names are the common form and can differ from the legislature's formal one.
- **District number alone.** Add the chamber, and the period: a seat changes hands, and a redistricted number may cover different ground.
- **`candidateId` in the races files, over time.** It encodes a position in the source export, so the same ID can point at a different person after a re-export. Use it only within one downloaded copy.
- **`ocdPersonId`.** A cross-reference that is missing for some people. Never required for identity.
- **`countyCode` in `millage.csv`.** It is not a FIPS code. Use `millage-places.json` (keyed by slug) or match on county name.

## State and federal do not join

The state files identify people by `legisGaGovId` and the federal files by `bioguideId`, and neither carries the other's. To connect them, use the `vgId` crosswalk below.

## vgId, VoteGA's person ID

`vgId` (for example `vg-ga-p-000001`) identifies one person across the legislature, statewide offices, Georgia's congressional delegation and campaign filings. It is in the [officeholder and candidate ID crosswalk](https://www.votega.org/about-the-data#officeholder--candidate-id-crosswalk) ([JSON](https://www.votega.org/assets/data/id-crosswalk.json)), published on votega.org and not in a repository. The data repositories' own member and candidate files don't carry it, so join to the crosswalk on an ID they do have.

Each person's `ids` can include `legisGaGovId`, `bioguideId`, `rosterId`, `executiveId`, and lists of campaign filing IDs (`fecCandidateIds`, `peachfileFilerEntityIds`).

- **An assigned `vgId` is never reused or given to someone else.**
- **It can be `null`.** A candidate with no campaign finance filing may have none. Don't group records on a null value.
- **Follow merges.** If one person was given two IDs, `metadata.mergedVgIds` maps the retired one to the one in use. Apply it to any `vgId` you have stored.
- **It doesn't cover everyone.** `metadata.scope` says who is included. Former state legislators are included only for recent sessions.
- **Check `provenance`.** It says how each link was made. A missing ID is not proof that none exists.

```python
import json, urllib.request

with urllib.request.urlopen(urllib.request.Request(
        "https://www.votega.org/assets/data/id-crosswalk.json",
        headers={"User-Agent": "my-civic-tool/1.0"}), timeout=60) as r:
    xw = json.loads(r.read().decode("utf-8-sig"))

merged = xw["metadata"].get("mergedVgIds", {})
by_vgid = {p["vgId"]: p for p in xw["people"] if p["vgId"]}
by_legis = {p["ids"]["legisGaGovId"]: p for p in xw["people"]
            if p["ids"].get("legisGaGovId")}

def person(vgid):
    return by_vgid.get(merged.get(vgid, vgid))

p = by_legis[5089]                       # from a roster row's legisGaGovId
print(p["vgId"], p["name"]["full"], p["ids"]["peachfileFilerEntityIds"])
print(person("vg-ga-p-000376")["vgId"])  # a retired ID resolves to its replacement
```

## County codes

County codes are 5-digit FIPS (`13217` for Newton). `ga-district-information` releases before 2.0.0 used the 3-digit suffix (`217`) under the same column names.

Read codes as text so spreadsheets don't reformat them.
