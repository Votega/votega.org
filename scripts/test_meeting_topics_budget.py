#!/usr/bin/env python3
"""Invariants for the `budget` topic and the two rule types it introduced.

`budget` replaces the retired `millage-budget`, whose bare 'budget' and 'fiscal
year' keywords put it on 59 of 59 flagged places. See docs/BUDGET-TOPIC-SCOPE.md
for the corpus measurements these tests encode.

What is pinned here:
  1. The budget DECISIONS fire — proposed, hearing, work session, adoption,
     amendment — including the Georgia phrasings where the fiscal year sits
     between the verb and the noun, which no fixed phrase can reach.
  2. The money PLUMBING does not. 'budgeted' is the largest false-positive source
     and there is no bare 'budget' keyword for it to match.
  3. A place's agenda TEMPLATE cannot manufacture the topic. Savannah prints
     "HEARINGS (Alcohol, Public, Zoning, and Budget)" on every meeting; 15 of its
     18 flagged documents were flagged by that string alone before the exclusion
     rule existed.
  4. The new rule types do not disturb any other topic.

Stdlib only: CI installs no pip packages.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import (  # noqa: E402
    BUDGET_TERMS, TOPIC_EXCLUDE_RULES, TOPIC_PROXIMITY_RULES, TOPIC_RULES,
    classify, matched_terms, topic_excerpts, topic_flags, topic_spans)

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def fires(text):
    return 'budget' in classify(text)


# ---------------------------------------------------------------------------
print("Budget decisions fire")

for label, text in [
    ("a proposed budget", "PUBLIC HEARING FY2027 PROPOSED BUDGET"),
    ("public comment on one", "PUBLIC COMMENT ON PROPOSED 2027 BUDGET"),
    ("adoption", "Consideration of Resolution to adopt the budget."),
    ("a work session", "Approval of Minutes for Budget Work Session May 28, 2026"),
    ("a workshop", "Chairwoman Teems will Call to Order the Budget Workshop"),
    ("an amendment", "approve Resolution 026-006 to amend the Fiscal Year 2026 Budget"),
    ("an ordinance", "Second reading of the budget ordinance for the coming year"),
    ("the operating budget", "Review of the operating budget for the water fund"),
]:
    check(label, fires(text), True)

# ---------------------------------------------------------------------------
print("The fiscal-year token does not break the match (this is why proximity exists)")

# Every one of these is real Georgia agenda phrasing from the corpus. A fixed
# phrase cannot reach any of them, because FY<year> sits between verb and noun.
for label, text in [
    ("adopt FY2027 Budget", "10. discuss action to adopt the FY 2027 budget."),
    ("amend the FY 2026 budget", "to amend the FY 2026 budget by amending revenue lines"),
    ("public hearing (FY27 budget)", "11. public hearing (FY27 budget) - Chairman Perdue"),
    ("worksession - FY2027 budget", "Commissioners called meeting/worksession - FY2027 budget"),
    ("proposed FY 2026-2027 budget", "v. public hearing 1. proposed fy 2026-2027 budget"),
]:
    check(label, fires(text), True)
    # ...and specifically NOT via a fixed phrase, or the proximity rule is dead code.
    phrases = [k for k in TOPIC_RULES['budget'] if k in text.lower()]
    check("  %s is reached only by proximity" % label, phrases, [])

# ---------------------------------------------------------------------------
print("Money plumbing does not fire")

for label, text in [
    ("'Budgeted: Yes' on a grant", "Award amount: $96,217.00 Budgeted: Yes"),
    ("a budgeted purchase line", "6.2. Contracts & Budgeted Purchases of $25,000 or Greater"),
    ("a purchase from a budget", "roof replacement, $194,200.00, to be paid from the "
                                 "facilities management budget"),
    ("an item included in a budget", "purchase of a Kubota Skid Steer, which was "
                                     "included in the FY 2026-2027 approved budget"),
    ("a construction budget", "which exceeds the current construction budget of $586,000"),
    ("a fiscal-year grant", "acceptance of the Fiscal Year 2025 emergency management "
                            "performance grant"),
    ("a comp-plan filing", "Capital Improvements Element Annual Update Report for "
                           "Fiscal Year 2026"),
]:
    check(label, fires(text), False)

check("there is no bare 'budget' keyword", 'budget' in TOPIC_RULES['budget'], False)
check("there is no 'fiscal year' keyword", 'fiscal year' in TOPIC_RULES['budget'], False)

# ---------------------------------------------------------------------------
print("An agenda template cannot manufacture the topic")

# Savannah's, verbatim, on every one of its meetings.
BOILERPLATE = ("Meeting will begin at 2:00 p.m. PUBLIC COMMENTS ARE ACCEPTED ONLY "
               "FOR HEARINGS (Alcohol, Public, Zoning, and Budget) Please limit "
               "comments to 2 minutes.")
check("the Savannah boilerplate alone does not fire", fires(BOILERPLATE), False)
# Without this the exclusion test above would pass even if the proximity rule had
# silently stopped matching, and the suite would be proving nothing.
check("it does trip a proximity rule before exclusion",
      any(re.search(pat, BOILERPLATE.lower())
          for _, pat in TOPIC_PROXIMITY_RULES['budget']), True)

# The same page WITH a real budget item must still fire, and must quote the item.
WITH_ITEM = BOILERPLATE + (" 72. Authorize Quarter 2 Budget Appropriations to the "
                           "Fiscal Year 2026 Budget. Exhibit 1: 2026 Q2 Budget "
                           "Amendment Memo.pdf")
check("boilerplate plus a real item still fires", fires(WITH_ITEM), True)
ex = topic_excerpts(WITH_ITEM, classify(WITH_ITEM)).get('budget') or {}
check("the excerpt is not the boilerplate", 'Alcohol' in ex.get('excerpt', ''), False)
check("the excerpt quotes the real item", 'Budget Amendment' in ex.get('excerpt', ''), True)

# A category menu generally, not just Savannah's wording.
check("another parenthesised category list is excluded",
      fires("Hearings (Zoning, Alcohol, and Budget) are heard first"), False)

# ---------------------------------------------------------------------------
print("Evidence reports only surviving hits")

terms = matched_terms(WITH_ITEM)
check("a real hit is reported", bool(set(terms) & BUDGET_TERMS), True)
check("the excluded boilerplate reports no budget evidence",
      sorted(set(matched_terms(BOILERPLATE)) & BUDGET_TERMS), [])

# ---------------------------------------------------------------------------
print("The new rule types leave other topics alone")

check("the flag is wired", topic_flags(['budget']), ['budget'])
check("millage-budget is retired", 'millage-budget' in TOPIC_RULES, False)
check("only budget carries the new rule types",
      sorted(set(TOPIC_PROXIMITY_RULES) | set(TOPIC_EXCLUDE_RULES)), ['budget'])
# An exclusion belongs to its own tag and must not reach across topics.
check("a land-use item in a category list still fires",
      'rezoning' in classify("Hearings (Alcohol, Zoning, and Budget): a rezoning "
                             "of 12 acres"), True)
check("an ALPR item beside a budget line still fires",
      'alpr' in classify("Approve the Flock Safety contract, paid from the police "
                         "department budget"), True)

# A document with no budget content yields no spans at all.
check("a quiet agenda yields no budget spans",
      topic_spans("approval of minutes and a proclamation", 'budget'), [])

# ---------------------------------------------------------------------------
if failures:
    print("\n%d FAILED: %s" % (len(failures), ', '.join(failures)))
    sys.exit(1)
print("\nAll budget-topic invariants hold.")
