Examples in Python 3, standard library only. No key or signup is needed. Run this setup first; every example uses it.

```python
import csv, io, json, urllib.request

def url(repo, path):
    return f"https://raw.githubusercontent.com/Votega/{repo}/main/{path}"

def get_json(repo, path):
    with urllib.request.urlopen(url(repo, path)) as r:
        return json.loads(r.read().decode("utf-8-sig"))

def get_csv(repo, path):
    with urllib.request.urlopen(url(repo, path)) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig"))))
```

These examples read the "current" paths, which change meaning when new officeholders are seated. To pin a period, see each repository's **Linking to this data** section.

## ZIP code to state House members

A ZIP is not a district. This returns every district that touches the ZIP, so label the result that way. Only a street address identifies one voter's district.

```python
zips = get_json("ga-district-information", "data/zips.json")["zips"]
members = get_json("ga-legislators", "data/all.json")["members"]

house = {m["district"]: m for m in members
         if m["chamber"] == "House of Representatives"
         and m["status"] in (None, "Suspended")}   # suspended members still hold the seat

for d in zips["30014"]["stateHouse"] or []:       # PO-box ZIPs carry no districts
    m = house.get(d["district"])
    who = f'{m["name"]} ({m["party"]})' if m else "no sitting member listed"
    print(f'HD {d["district"]}: {who}, about {d["share"]:.1%} of residents')
```

The same pattern works for `stateSenate` (chamber `"Senate"`) and `usHouse` (members from `ga-federal-legislators`, field `district`). Keep the small shares: those residents still vote in that district.

## A legislator's recorded votes

Votes are archived per session. `latest.json` names the sessions, so don't hard-code one.

```python
latest = get_json("ga-legislators", "latest.json")
members = get_json("ga-legislators", "data/all.json")["members"]
me = next(m for m in members
          if m["chamber"] == "House of Representatives" and m["district"] == 114)

for s in latest["sessions"]:
    data = get_json("ga-legislators", f'sessions/{s["slug"]}/votes.json')
    rows = data["memberVotes"].get(me["id"], [])
    print(s["name"], me["name"], len(rows), "bill votes")
    for row in rows[:3]:
        v = data["votes"][row["voteId"]]
        print("  ", v["date"], v["bill"], row["vote"], f'({v["yea"]}-{v["nay"]})')
```

One floor vote on a bundled calendar appears once per bill. To count floor votes, count distinct values of the part of `voteId` before the hyphen.

## Bills a legislator sponsored

Bill sponsors carry `legisGaGovId`.

```python
latest = get_json("ga-legislation", "latest.json")
members = get_json("ga-legislators", "data/all.json")["members"]
me = next(m for m in members
          if m["chamber"] == "House of Representatives" and m["district"] == 114)

for s in latest["sessions"]:
    bills = get_json("ga-legislation", f'sessions/{s["slug"]}/bills.json')["bills"]
    mine = [b for b in bills
            if any(p["legisGaGovId"] == me["legisGaGovId"] for p in b["sponsors"])]
    primary = [b for b in mine
               if any(p["legisGaGovId"] == me["legisGaGovId"] and p["primary"]
                      for p in b["sponsors"])]
    print(s["name"], len(mine), "sponsored,", len(primary), "as primary sponsor")
```

## Incumbents on the ballot

In `candidates.csv`, `memberId` points at a sitting officeholder's record. `memberSource` says which dataset.

```python
rows = get_csv("ga-races-elections", "races/2026/candidates.csv")
state = {m["id"]: m for m in get_json("ga-legislators", "data/all.json")["members"]}
federal = {m["bioguideId"]: m
           for m in get_json("ga-federal-legislators", "data/members.json")["members"]}
lookup = {"state": state, "congress": federal}

linked = {}
for r in rows:
    m = lookup.get(r["memberSource"], {}).get(r["memberId"])
    if m and r["phase"] == "general":
        linked[(r["raceId"], r["memberId"])] = m["name"]

for (race, _), name in list(linked.items())[:10]:
    print(race, "|", name)
print(len(linked), "general-election entries linked to an officeholder")
```

An officeholder running for a different office is linked the same way, and a member who has since left the roster will not resolve. A race's result is on the race in `races.json` (`status: "certified"` and `winner`), and is absent until recorded.

## One county across repositories

The county slug (`newton`) is shared by the district crosswalk and the local-government files.

```python
slug = "newton"
codes = {r["slug"]: r for r in get_csv("ga-district-information", "data/county-codes.csv")}
fips = codes[slug]["county_fips"]

districts = [r for r in get_csv("ga-district-information", "data/county-districts.csv")
             if r["county_fips"] == fips]
officials = [r for r in get_csv("ga-local-government", "data/officials/officials.csv")
             if r["jurisdiction"] == slug]
mentions = [r for r in get_csv("ga-local-government", "data/mentions.csv")
            if r["placeId"] == slug]
millage = get_json("ga-local-government", "data/millage-places.json")["places"].get(slug)

for d in districts:
    print(d["chamber"], d["district"], d["coverage"])
print(len(officials), "officials;", len(mentions), "agenda mentions")
if millage:
    year = max(millage["combined"])
    print("combined millage", year, millage["combined"][year])
```

An empty result can mean the place is not covered, not that nothing happened. Check `data/coverage.json`. The combined millage excludes special districts, which depend on the parcel.
