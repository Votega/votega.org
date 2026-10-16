#!/usr/bin/env python3
"""Tests for employer-name cleanup in generate_fec_data.py.

Donor-supplied employer strings arrive as free text, uppercased by the FEC. The
old code title-cased them and deduped on a key that kept commas, so the finance
panel showed "Google" and "Google, Inc." as separate rows (splitting Ossoff's
Google total) and printed "Cvs", "Ibm", "At&T", "University Of California".

Nothing here expands an acronym into a company name -- there is no registry to
resolve an employer against, unlike a stock ticker. Spelling and casing only.

Runs offline. Usage:
  python scripts/test_fec_employers.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('FEC_API_KEY', 'test-key-not-used')  # import-time guard

from generate_fec_data import (  # noqa: E402
    display_employer, employer_key, merge_top_employers,
)

PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"          got={got!r}  want={want!r}")


print('=== employer_key merges spellings of one employer ===')
check('a legal suffix does not split a key',
      employer_key('GOOGLE') == employer_key('GOOGLE, INC.'), True)
check('LLC and bare name share a key',
      employer_key('Google') == employer_key('Google LLC'), True)
check('punctuation and spacing are ignored',
      employer_key('Madderra, Cazalot & Head')
      == employer_key('Madderra Cazalot &  Head'), True)
check('Saulsbury variants share a key',
      employer_key('Saulsbury Industries')
      == employer_key('Saulsbury Industries, Inc.'), True)
check('distinct employers keep distinct keys',
      employer_key('Delta Air Lines') == employer_key('Delta Dental'), False)
# A suffix is only stripped as a whole word, so it cannot eat part of a name.
check('a suffix inside a word is left alone',
      employer_key('COSTCO'), 'COSTCO')
check('a name that is only a suffix survives', employer_key('CO'), '')

print('\n=== display_employer preserves acronyms ===')
check('a vowelless token stays uppercase', display_employer('CVS'), 'CVS')
check('IBM', display_employer('IBM'), 'IBM')
check('KPMG', display_employer('KPMG'), 'KPMG')
check('DFCS', display_employer('DFCS'), 'DFCS')
check('an acronym inside a phrase', display_employer('BGR GROUP'), 'BGR Group')
check('FH STRATEGIES', display_employer('FH STRATEGIES'), 'FH Strategies')
check('a real word is not mistaken for an acronym',
      display_employer('GOOGLE'), 'Google')
check('Apple', display_employer('APPLE'), 'Apple')
check('Emory', display_employer('EMORY UNIVERSITY'), 'Emory University')

print('\n=== display_employer casing rules ===')
check('a small word lowercases inside a name',
      display_employer('UNIVERSITY OF CALIFORNIA'), 'University of California')
check('Bank of America', display_employer('BANK OF AMERICA'), 'Bank of America')
check('a small word still leads a name',
      display_employer('THE HOME DEPOT'), 'The Home Depot')
check('a possessive is not capitalized',
      display_employer("MCKENNEY'S INC"), "McKenney's Inc")
check('a Mc prefix is restored',
      display_employer('MCMULLEN CPAS'), 'McMullen Cpas')

print('\n=== known limit: a vowel-bearing initialism cannot be told from a word ===')
# Documented, not hidden: AFGE and Apple are the same shape to any rule that
# does not consult a word list. _STYLED_NAMES pins the whole-string cases.
check('AFGE title-cases, as documented', display_employer('AFGE'), 'Afge')
check('ACOG title-cases, as documented', display_employer('ACOG'), 'Acog')
check('a pinned whole-string case is correct', display_employer('IBM'), 'IBM')
check('a personal-name suffix is not shouted',
      display_employer('BENTON J. MATHIS, JR.'), 'Benton J. Mathis, Jr.')
check('a roman numeral suffix is not flattened',
      display_employer('JOHN SMITH III'), 'John Smith III')
check('a styling no rule derives', display_employer('AT&T'), 'AT&T')
check('FedEx', display_employer('FEDEX'), 'FedEx')
check('empty name', display_employer(''), '')

print('\n=== merge_top_employers sums rather than discards ===')
# Ossoff's two real Google rows, as published in ga-fec-data.json.
OSSOFF = [
    {'employer': 'GOOGLE',       'total': 751643, 'count': 2288},
    {'employer': 'MICROSOFT',    'total': 200733, 'count': 990},
    {'employer': 'GOOGLE, INC.', 'total': 86000,  'count': 240},
]
merged = merge_top_employers(OSSOFF)
check('the two Google rows become one', len(merged), 2)
check('the money is summed, not dropped', merged[0]['total'], 751643 + 86000)
check('the donor counts are summed', merged[0]['count'], 2288 + 240)
check('the most-used spelling wins', merged[0]['employer'], 'Google')
check('merging re-ranks: Google outgrows Microsoft',
      [e['employer'] for e in merged], ['Google', 'Microsoft'])

# The display name comes from the largest variant, not the first row seen.
REVERSED = list(reversed(OSSOFF))
check('order of the input does not change the result',
      merge_top_employers(REVERSED), merged)

TIE = [{'employer': 'ACME CORP', 'total': 100, 'count': 1},
       {'employer': 'ACME', 'total': 100, 'count': 1}]
check('a tie resolves deterministically by name',
      merge_top_employers(TIE)[0]['employer'], 'Acme Corp')
check('a tie still sums', merge_top_employers(TIE)[0]['total'], 200)

check('no rows', merge_top_employers([]), [])
check('a single row is display-cased',
      merge_top_employers([{'employer': 'CVS', 'total': 5, 'count': 1}]),
      [{'employer': 'CVS', 'total': 5, 'count': 1}])

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
