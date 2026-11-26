# City election rules from charters: design

Date: 2026-11-26. Status: awaiting approval.

## Intent
Use city charters to (1) fill missing term dates on `/local/` rosters and (2) show
voters how and when their city elects its officials. 73 of 132 city and
consolidated roster rows have no `next_election`, and 2027 is a municipal election
year. Pilot: Atlanta, Conyers, Carrollton.

## Source
Georgia Commons holds charter text by section, with the publisher and a "current
through" or "retrieved" date. It is an independent project, not an official source.
It holds charters for 15 of our 17 city and consolidated places (not Covington;
Social Circle has code only).

## Approaches
1. **Hand-researched, cited rules in our data** (chosen). A person reads the
   sections, writes plain-English rules with links, and checks dates against
   election results. Slow per city, but nothing publishes unread.
2. **Scheduled pull and extraction.** Rejected: charters rarely change, and the
   text needs judgment (superseded clauses sit beside current ones).
3. **Roster dates only, no page content.** Rejected by the owner: capture both
   while the charter is open.

## Data
A new optional block per jurisdiction in `_data/local_officials.yml` (it already
holds `term_years` and joins to the place page by slug):

```yaml
    election_rules:
      checked: 2026-11-26             # date a person verified these
      text_as_of: 2026-10-21          # Georgia Commons' edition date
      items:
        - topic: schedule
          text: The mayor, council president and all council members are elected together every four years, in November (2025, 2029).
          cite: Charter § 5-102
          url: https://georgiacommons.org/cities/atlanta/charter/5-102
```

- `topic` is one of: `schedule`, `terms`, `winning` (majority or plurality),
  `districts`, `vacancies`, `eligibility`, `term_limits`. Each appears at most once.
- A topic we cannot establish is left out. No empty strings, no guesses.
- A rule resting on two sections cites the controlling one.
- Set `term_years` where the charter establishes it.

## Roster dates
For each active member fill `last_elected`, `term_end`, `next_election`.
`last_elected` is filled only from an election result or an official city page, never
inferred from the charter.
- `term_provenance: verified` when the charter rule and an election result (SoS or
  county) or an official city page agree.
- `term_provenance: assumed` when the date follows from the charter rule alone.
- Where sources disagree, leave the field unchanged and list the conflict in the PR.
- Add no member rows and change no names, seats or roles.

## Page
An "Elections & terms" section in the Officials tab of `/local/<slug>/`, below the
roster, rendered only when the block exists:
- One labelled row per topic, in the order listed above, each with its section link.
- Footer: "From the city charter as stored by Georgia Commons, text as of <date>.
  Checked <date>. Charters can be amended and state election law also applies;
  confirm with the city clerk."
- Role tokens only, Font Awesome icons, checked at 375 and 1280 wide.

## Validation
`scripts/validate_local_officials.py` fails on: unknown or repeated `topic`, missing
`text`/`cite`/`url`, non-https `url`, missing or malformed `checked`/`text_as_of`.
Tests go in a `scripts/test_*.py`. Document the block in the file header and
`docs/conventions-local-government.md`.

## What the pilot has already shown
- **Atlanta** is simple: every office is elected in November 1997 and every four
  years after, majority required (§ 5-102), so the next regular election is 2029.
- **Conyers** has a conflict to resolve. § 4-103 sets staggered classes that put
  District 2 Post 2 on the 2023/2027 cycle, but our roster says that member was last
  elected in 2025. § 4-102.1 and § 4-103 also differ on when terms begin.
- **Carrollton** is the hard case. Its charter is a set of old acts: one section
  says two-year terms and October elections, a later one says four-year terms from
  1975. Its stagger matches our roster's 2027/2029 split. The at-large versus ward
  wording needs a check for later amendments.

## Not in scope
Counties, the other 12 city and consolidated places, scheduled syncing, race or
candidate pages, and explaining state election law.

## Effects to know about
`local_officials.yml` feeds the published local-officials dataset and the MCP index,
so new term dates flow there on merge. The `election_rules` block is not added to
either export in this pass.

## Done when
The three pilot pages show the section, their roster dates are filled or listed as
conflicts, the validator and tests pass, and the owner has reviewed every rule's
wording in the PR. Then decide whether to continue to the other 12.

## Left to the builder
Markup and styling of the section, test layout, and exact rule wording (reviewed by
the owner in the PR).
