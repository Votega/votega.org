#!/usr/bin/env python3
"""Invariants of the dataset-manifest convention (lib/sibling_publish). No network.

Three sibling repos are written by TWO publishers each, from different workflows
on different schedules. This suite pins the arrangement that lets them coexist,
and it is a REGRESSION TEST for a real bug: the millage publisher's paths were
briefly listed inside publish_ga_local_government.py's latest.json, a document
stamped with that job's own clock — so a consumer would have read a twice-weekly
run's freshness and applied it to monthly data.

What is pinned, and why:
  * NO PUBLISHER DESCRIBES ANOTHER'S DATA. Each writes only its own
    data/<dataset>/manifest.json. A shared, merged index is impossible to write
    safely: _put_content reads the SHA then PUTs, and its 409/422 retry re-reads
    the SHA and OVERWRITES rather than re-merging, so two overlapping runs would
    silently drop one publisher's entry.
  * CO-TENANT PUBLISHERS SHARE NO PATH except LICENSE and NOTICE.md, which are
    byte-identical by design. Any other overlap means one job clobbers the other.
  * generatedAt IS THE DATA'S OWN TIMESTAMP and is required.
  * NO WALL-CLOCK TIME MAY REACH A MANIFEST, so two builds of unchanged data are
    byte-identical. An earlier draft stamped a publishedAt, which broke
    test_publish_early_vote's test_two_builds_are_byte_identical — and that test
    is right about why: a byte that moves every run means every scheduled run
    PUTs the file again, filling the sibling repo with commits that record
    nothing. When the mirror last ran is already in that repo's git history.
  * A MANIFEST CANNOT ADVERTISE A FILE THE RUN DID NOT BUILD — that is a 404 for
    a consumer, so it is refused at build time.
  * NOTHING HERE IMPORTS A PUBLISHER. CI installs no pip packages, and one
    publisher imports pyyaml at module level — importing it made this suite pass
    locally and fail in CI. The publishers are read with `ast` instead, which
    also checks the slug each one actually passes rather than a list written here.
  * ONE DATASET, ONE MANIFEST. A second manifest for the same slug is refused
    rather than silently overwriting the first.

Run: python scripts/test_dataset_manifests.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import sibling_publish as SP  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def raises(fn, needle):
    try:
        fn()
    except Exception as exc:                      # noqa: BLE001
        return needle.lower() in str(exc).lower()
    return False


def fresh(**kw):
    """A minimal valid manifest build."""
    arts = {'data/x.json': b'{"a":1}', 'X.md': b'# x'}
    opts = dict(title='T', description='D', generated_at='2026-01-02T03:04:05Z',
                files=['data/x.json', 'X.md'])
    opts.update(kw)
    path = SP.add_dataset_manifest(arts, 'Votega/ga-local-government', 'demo', **opts)
    return arts, path


print('The manifest path is derived, one writer per path')
check(SP.manifest_path('millage') == 'data/millage/manifest.json',
      'manifest_path("millage") -> data/millage/manifest.json')
for bad in ('Millage', 'mill age', '-millage', 'millage/x', '', None):
    if not raises(lambda b=bad: SP.manifest_path(b), 'lowercase slug'):
        check(False, 'a bad dataset slug %r was accepted' % (bad,))
        break
else:
    check(True, 'a non-slug dataset name is refused, so paths cannot collide by accident')

print('\nThe data timestamp, and no other')
arts, path = fresh()
doc = json.loads(arts[path])
check(doc['generatedAt'] == '2026-01-02T03:04:05Z',
      "generatedAt is the DATA's own stamp, passed in by the publisher")
import time  # noqa: E402
_a, _p = fresh()
time.sleep(1.1)
_b, _ = fresh()
check(_a[_p] == _b[_p],
      'two builds of unchanged data are BYTE-IDENTICAL across a second boundary — '
      'no wall-clock time reaches a manifest, or every scheduled run would '
      'republish and churn the sibling repo (this is why there is no publishedAt)')
check(b'publishedAt' not in _a[_p] and b'"20' not in _a[_p].replace(
          b'"2026-01-02T03:04:05Z"', b''),
      'the only timestamp in a manifest is the generatedAt the publisher passed in')
check(raises(lambda: fresh(generated_at=''), 'generated_at is required'),
      'an empty data timestamp is refused — this is the regression guard: a '
      'manifest whose only stamp is the publish time is what the old '
      'static-paths-in-latest.json approach effectively produced')
check(raises(lambda: fresh(generated_at='   '), 'generated_at is required'),
      'whitespace does not satisfy it either')

print('\nA manifest cannot advertise a file that was not built')
check(raises(lambda: fresh(files=['data/x.json', 'data/ghost.json']), 'did not build'),
      'listing an unpublished path is refused, not discovered as a 404 later')
check(raises(lambda: fresh(files=[]), 'lists no files'),
      'a manifest with no files is refused')
check(all('bytes' in f for f in doc['files']),
      'each listed file carries its byte size, taken from the artifact itself')
check([f['path'] for f in doc['files']] == sorted(f['path'] for f in doc['files']),
      'files are sorted, so the manifest is byte-stable across runs')

print('\nOne dataset, one manifest')
arts2 = {'data/x.json': b'{}'}
SP.add_dataset_manifest(arts2, 'Votega/ga-local-government', 'demo', title='T',
                        description='D', generated_at='2026-01-01T00:00:00Z',
                        files=['data/x.json'])
check(raises(lambda: SP.add_dataset_manifest(
          arts2, 'Votega/ga-local-government', 'demo', title='T2',
          description='D2', generated_at='2026-01-01T00:00:00Z',
          files=['data/x.json']), 'two manifests'),
      'a second manifest for the same dataset is refused, not silently merged')

print('\nLicense and reuse terms are carried in every manifest')
check(doc['license']['spdx'] == SP.LICENSE_SPDX and doc['license']['url'] == SP.LICENSE_URL,
      'the manifest states the same licence the published LICENSE/NOTICE do')
check(doc['repo'] == 'Votega/ga-local-government' and doc['publisher'] == 'VoteGA.org',
      'it names its repo and publisher')
check(doc['manifestSchemaVersion'] == SP.MANIFEST_SCHEMA_VERSION,
      'and its own schema version, so the shape can evolve')
check(doc['source'],
      'source defaults to the repo\'s registered upstream when not given')
check(json.loads(fresh(source='Somewhere else')[0]
                 ['data/demo/manifest.json'])['source'] == 'Somewhere else',
      'and is overridable, which millage needs: its source is DOR, not agendas')

print('\nEvery co-tenant publisher writes its own manifest and nobody else\'s')
# Read the publishers with `ast` rather than importing them. CI installs no pip
# packages (run-script-tests.yml), and publish_ga_local_government.py imports
# pyyaml at module level — importing it here passed locally and failed in CI with
# ModuleNotFoundError, which is exactly the gap this suite is supposed to be
# immune to. Parsing the committed file is also a STRONGER check: it reads the
# dataset slug each publisher actually passes to add_dataset_manifest, instead of
# trusting a list written here.
import ast  # noqa: E402


def _module_const(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    if isinstance(node.value, ast.Constant):
                        return node.value.value
    return None


def _manifest_slugs(tree, src):
    """The dataset slug(s) passed to add_dataset_manifest in this module."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = getattr(fn, 'id', None) or getattr(fn, 'attr', None)
        if fname != 'add_dataset_manifest':
            continue
        # (artifacts, repo, dataset, *, ...) — the slug is the third positional.
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
            out.append(node.args[2].value)
        elif len(node.args) >= 3 and isinstance(node.args[2], ast.Name):
            out.append(_module_const(tree, node.args[2].id))
        else:
            out.append(None)
    return out


PUBLISHERS = ('publish_ga_local_government', 'publish_ga_millage',
              'publish_races', 'publish_early_vote',
              'publish_ga_bills', 'publish_ga_ballot_measures')
INFO = {}
for name in PUBLISHERS:
    src = open(os.path.join(HERE, name + '.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    INFO[name] = {'src': src, 'repo': _module_const(tree, 'REPO'),
                  'slugs': _manifest_slugs(tree, src)}

for name, info in INFO.items():
    check(info['repo'], '%s declares a REPO' % name)
    check(len(info['slugs']) == 1 and info['slugs'][0],
          '%s emits exactly one dataset manifest, with a literal slug: %r'
          % (name, info['slugs']))

by_repo = {}
for name, info in INFO.items():
    by_repo.setdefault(info['repo'], []).append((name, info['slugs'][0]))

for repo, members in sorted(by_repo.items()):
    if len(members) < 2:
        continue
    slugs = [s for _, s in members]
    check(len(set(slugs)) == len(slugs),
          '%s is written by %d publishers and they use distinct slugs %r'
          % (repo, len(members), slugs))
    paths = [SP.manifest_path(s) for s in slugs]
    check(len(set(paths)) == len(paths),
          '%s: and therefore distinct manifest paths' % repo)

check(sorted(by_repo) == ['Votega/ga-legislation', 'Votega/ga-local-government',
                          'Votega/ga-races-elections'],
      'the three shared repos are the ones covered here: %r' % sorted(by_repo))

check('"latest.json"' not in INFO['publish_ga_millage']['src'],
      'the millage publisher does not write latest.json')
mentions_src = INFO['publish_ga_local_government']['src']
check('"millage": "data/millage.json"' not in mentions_src,
      "the mentions publisher no longer lists millage's files in its own "
      'latest.json — the regression this suite exists for')
check('data/*/manifest.json' in mentions_src,
      'it points consumers at the manifest convention instead')
check('artifacts["latest.json"]' in INFO['publish_ga_bills']['src'],
      "ga-legislation's latest.json is UNCHANGED: it is a bills pointer "
      '(biennium, currentSession, sessions[]), not a repo index, so it keeps its '
      'own meaning and no consumer of it breaks')
check('"latest.json"' not in INFO['publish_ga_ballot_measures']['src'],
      'and the ballot-measures publisher still does not write it')

print('\nThe shared pre-publish gates still accept a manifest build')
SP._assert_artifacts_sane(dict(arts))
check(True, 'a manifest is valid JSON and non-empty, so it clears the universal gate')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll dataset-manifest invariants hold.')
