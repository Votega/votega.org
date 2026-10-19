#!/usr/bin/env python3
"""Precision / recall guard for the `alpr` (ALPR / surveillance) subject rule.

lib/meeting_topics.py classifies by keyword, so every term added to widen recall
is a chance to badge an unrelated agenda as surveillance. This pins both sides:
phrases that MUST fire, and look-alikes that MUST NOT (the real reasons a bare
term was rejected). Add a case here whenever a keyword is added or removed.

Run: python scripts/test_meeting_topics_alpr.py       (no network, no repo writes)
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import (ALPR_HIGH_TERMS, ALPR_TERMS, ALPR_VENDOR_LABELS,
                                TOPIC_RULES, alpr_vendors, classify, matched_terms)

failures = []


def fires(text):
    return 'alpr' in classify(text)


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


MUST_FIRE = [
    # original behaviour
    'Approve contract with Flock Safety for ALPR cameras',
    'Automated License Plate Reader program',
    'license plate recognition system',
    'Safer City cameras',
    # generic phrasing added in the expansion
    'Purchase of a LPR system for the sheriff',
    'Install license-plate readers at county entrances',
    'plate recognition cameras on Highway 11',
    'ANPR trial', 'LPR cameras', 'LPR/ALPR data sharing policy',
    'a license plate camera at the courthouse',
    'mobile plate scanner for patrol vehicles',
    # surveillance, beyond plate reading
    'Resolution on surveillance technology and community oversight',
    'purchase of surveillance cameras for the downtown corridor',
    'facial recognition software for the police department',
    'Real-Time Crime Center (RTCC) buildout',
    'Real Time Crime Center',
    'ShotSpotter gunshot detection renewal',
    'SoundThinking subscription',
    'Fusus integration', 'Verkada camera licenses', 'Hikvision cameras ban',
    'Avigilon appearance search', 'Cellebrite phone extraction licenses',
    'Clearview AI contract', 'cell-site simulator policy',
    'Peregrine Technologies platform', 'predictive policing pilot',
    'drone as first responder pilot program',
]

MUST_NOT_FIRE = [
    'Renew the license plate fee schedule at the tag office',
    'specialty license plates and tag renewals',
    'Clearview Drive paving project',
    'Clearview Subdivision final plat',
    'birds flocking to the retention pond', 'the crowd flocked to the park',
    'AppraisalPro contract',                                   # apprais-ALPR-o
    'disease surveillance report from the health department',
    'CCTV inspection of the sewer main',
    'Axon body cameras and tasers',
    'Motorola Solutions radio upgrade',
    'security camera at the library',                          # bare cameras stay out
    'the plate glass window replacement',
    'lprint', 'helpr', 'rtccx',                                # acronyms are whole-word only
    'drone survey of the landfill',
]

for t in MUST_FIRE:
    check('fires: %s' % t, fires(t), True)
for t in MUST_NOT_FIRE:
    check('quiet: %s' % t, fires(t), False)

# Every keyword that names a vendor must have a display label, and every label must
# be a real keyword (the file's own contract: "new vendor keyword -> label, same edit").
substr = set(TOPIC_RULES['alpr'])
check('every labelled vendor is a real keyword',
      sorted(k for k in ALPR_VENDOR_LABELS if k not in ALPR_TERMS), [])
check('HIGH terms are real keywords', sorted(ALPR_HIGH_TERMS - ALPR_TERMS), [])
check('matched_terms reports the new term', 'real-time crime center' in
      matched_terms('Real-Time Crime Center'), True)
check('vendors collapse duplicate brands',
      alpr_vendors(['shotspotter', 'soundthinking']), ['ShotSpotter (SoundThinking)'])

# The probe diagnostic must measure the SHIPPED matcher, not a private copy: an
# earlier probe kept its own ALPR_KEYWORDS dict (word-bounded, ~19 terms) that
# drifted from production in coverage AND semantics. Checked by source inspection
# rather than import: the probe imports lib.http / lib.pdf_text at module scope,
# which is fine today (stdlib only) but would make this guard fragile the moment
# either grows a dependency, and run-script-tests.yml installs no pip packages.
_probe = ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'probe_alpr_keywords.py'), encoding='utf-8').read())
_defined = {t.id for n in ast.walk(_probe) if isinstance(n, (ast.Assign, ast.AnnAssign))
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
            if isinstance(t, ast.Name)}
_defined |= {n.name for n in ast.walk(_probe) if isinstance(n, ast.FunctionDef)}
_imported = {a.name for n in ast.walk(_probe) if isinstance(n, ast.ImportFrom)
             and n.module == 'lib.meeting_topics' for a in n.names}
check('probe owns no keyword lexicon or matcher',
      sorted(_defined & {'ALPR_KEYWORDS', '_MATCHERS', 'classify'}), [])
check('probe sources its matcher from lib.meeting_topics',
      {'classify', 'matched_terms', 'ALPR_TERMS'} <= _imported, True)

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All ALPR keyword checks passed.')
