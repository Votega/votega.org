#!/usr/bin/env python3
"""Every scripts/test_*.py must run on the standard library alone. No network.

WHY THIS EXISTS
---------------
run-script-tests.yml installs NO pip packages, on purpose — its own header says
so, and notes that the one step which needed pyyaml failed on every run it ever
reached. So a test suite that imports a third-party module, directly or through
a local module, PASSES LOCALLY (where the packages are installed) and can only
ever fail in CI. There is no way to notice it from a normal local run.

That is not hypothetical. scripts/test_dataset_manifests.py imported the six
sibling publishers to read their REPO constants; exactly one of them,
publish_ga_local_government.py, imports pyyaml at module level. The suite went
green locally, and run-script-tests failed on both push and pull_request with
ModuleNotFoundError: No module named 'yaml'. This file is the guard for that
whole class of failure.

WHAT IT CHECKS
--------------
For every scripts/test_*.py it walks the import graph with `ast` — never
importing anything it inspects, which would defeat the point — and refuses any
module that is neither in sys.stdlib_module_names nor a local module under
scripts/.

For the TEST FILE itself every import counts, wherever it appears: these suites
are flat scripts, so a helper's import runs too. For a local module reached
through an import, only MODULE-LEVEL imports count, because those are what
executing the import statement runs.

KNOWN LIMIT, stated rather than papered over: an import sitting inside a
function of a local module is not flagged, since knowing whether a test reaches
it needs call-graph analysis. Those are the safe shape anyway — a lazy import
only costs anything if it is actually used — and the failure that bit us was a
module-level one.

THE HOUSE PATTERN IS RECOGNISED, NOT FOUGHT
-------------------------------------------
Two suites already solve this the right way, and this checker models them rather
than flagging them. test_executive_identity.py and test_ga_legislator_pages.py
need a local module that imports pyyaml at module level, so they pre-stub it:

    try:
        import yaml  # noqa: F401
    except ImportError:
        sys.modules["yaml"] = types.ModuleType("yaml")

A name a suite stubs into sys.modules, or imports inside a try/except ImportError,
counts as satisfied for that suite and everything it reaches. That is exactly
what makes those two safe in CI. Use this pattern when a test must reach a
module with a third-party import it never actually exercises.

Otherwise: if a suite genuinely NEEDS a third-party package at runtime, it does
not belong in scripts/test_*.py; move the check into a workflow that installs
that package.

Run: python scripts/test_no_third_party_imports.py
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STDLIB = set(sys.stdlib_module_names) | {'__future__'}

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def _toplevel_stmts(tree):
    """Statements an `import` of this module would actually execute."""
    out, stack = [], list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # a lazy import inside a def is not run by importing
        out.append(node)
        for field in ('body', 'orelse', 'finalbody', 'handlers'):
            stack.extend(getattr(node, field, []) or [])
    return out


def _guarded_names(tree):
    """Names a module makes safe for itself and everything it reaches.

    Two forms, both the established pattern in this repo:
      * `sys.modules["x"] = ...` — an explicit stub, so a downstream module's
        module-level `import x` finds it.
      * an import inside `try: ... except ImportError:` — the author handled the
        package being absent.
    """
    safe = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == 'modules'
                        and isinstance(tgt.slice, ast.Constant)
                        and isinstance(tgt.slice.value, str)):
                    safe.add(tgt.slice.value.split('.')[0])
        elif isinstance(node, ast.Try):
            handles_import_error = any(
                h.type is None
                or (isinstance(h.type, ast.Name) and h.type.id in ('ImportError', 'Exception'))
                or (isinstance(h.type, ast.Tuple)
                    and any(isinstance(e, ast.Name) and e.id in ('ImportError', 'Exception')
                            for e in h.type.elts))
                for h in node.handlers)
            if not handles_import_error:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    safe.update(a.name.split('.')[0] for a in inner.names)
                elif isinstance(inner, ast.ImportFrom) and inner.module:
                    safe.add(inner.module.split('.')[0])
    return safe


def _imported(tree, module_level_only):
    """[(dotted_candidate, top_level_name, lineno)] for each import.

    `from pkg import thing` yields BOTH "pkg.thing" and "pkg": `thing` may be a
    submodule (`from lib import xlsx`) or just a name inside pkg
    (`from lib.sibling_publish import build_json`). Resolution tries the longer
    candidate first, so a submodule is followed rather than being mistaken for
    its package's __init__.
    """
    nodes = _toplevel_stmts(tree) if module_level_only else list(ast.walk(tree))
    out = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((a.name, a.name.split('.')[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue  # relative: local by definition
            top = node.module.split('.')[0]
            for a in node.names:
                out.append(('%s.%s' % (node.module, a.name), top, node.lineno))
            out.append((node.module, top, node.lineno))
    return out


def _local_path(dotted, root):
    """The file a dotted module name resolves to under `root`, or None.

    Tries the full name, then successively shorter prefixes, so
    `lib.sibling_publish.build_json` still resolves to lib/sibling_publish.py.
    """
    parts = dotted.split('.')
    while parts:
        rel = os.sep.join(parts)
        for cand in (os.path.join(root, rel + '.py'),
                     os.path.join(root, rel, '__init__.py')):
            if os.path.exists(cand):
                return cand
        parts.pop()
    return None


def offenders(entry, root=None):
    """Third-party modules an entry file pulls in, with the chain reaching them.

    `root` is the directory local module names resolve against; it defaults to
    scripts/. It is a parameter so the self-check below can build its synthetic
    fixtures in a temp directory OUTSIDE scripts/ — writing them inside would
    leave a stray package directory there if a run were interrupted, and other
    suites enumerate that directory.

    Returns [(dotted_module, lineno, [chain of files])]. Nothing is imported —
    everything is read with ast, which is the point: importing the thing under
    inspection is the failure being guarded against.
    """
    root = root or HERE
    try:
        entry_tree = ast.parse(open(entry, encoding='utf-8').read(), filename=entry)
    except SyntaxError as exc:
        return [('<unparseable: %s>' % exc, 0, [os.path.basename(entry)])]

    allowed = STDLIB | _guarded_names(entry_tree)
    found, seen, reported = [], set(), set()
    queue = [(entry, entry_tree, [os.path.basename(entry)], True)]
    while queue:
        path, tree, chain, is_entry = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        for dotted, top, lineno in _imported(tree, module_level_only=not is_entry):
            if top in allowed:
                continue
            local = _local_path(dotted, root)
            if local:
                if local not in seen:
                    try:
                        sub = ast.parse(open(local, encoding='utf-8').read(), filename=local)
                    except SyntaxError as exc:
                        found.append(('<unparseable: %s>' % exc, 0, chain + [local]))
                        continue
                    queue.append((local, sub, chain + [os.path.relpath(local, root)], False))
                continue
            key = (top, path)
            if key not in reported:
                reported.add(key)
                found.append((dotted, lineno, chain))
    return found


print('The detector works')
# Prove it on synthetic files before trusting it on the real tree. The shape that
# broke CI — a module-level third-party import reached THROUGH a local module —
# is the one a naive checker misses.
import tempfile  # noqa: E402
# Built OUTSIDE scripts/ on purpose — see offenders(root=...).
with tempfile.TemporaryDirectory() as d:
    w = lambda n, s: open(os.path.join(d, n), 'w', encoding='utf-8').write(s)  # noqa: E731
    os.makedirs(os.path.join(d, 'pkg'))
    w(os.path.join('pkg', '__init__.py'), '')
    w(os.path.join('pkg', 'helper.py'),
      'import json\nimport yaml\n\n\ndef f():\n    import playwright\n')
    w('entry.py', 'import os\nfrom pkg import helper\n')
    w('direct.py', 'import os\nimport yaml\n')
    w('solo.py', 'import json\nimport zipfile\nfrom xml.etree import ElementTree\n')
    w('stubbed.py',
      'import sys, types\n'
      'try:\n    import yaml\nexcept ImportError:\n'
      '    sys.modules["yaml"] = types.ModuleType("yaml")\n'
      'from pkg import helper\n')

    def names(f):
        return sorted({g[0].split('.')[0]
                       for g in offenders(os.path.join(d, f), root=d)})

    check(names('direct.py') == ['yaml'], 'a direct third-party import is flagged')
    check(names('entry.py') == ['yaml'],
          "TRANSITIVITY: a local module's module-level third-party import is "
          'flagged through `from pkg import submodule`: %r' % names('entry.py'))
    got = offenders(os.path.join(d, 'entry.py'), root=d)
    check(got and len(got[0][2]) >= 2 and 'helper.py' in got[0][2][-1],
          'the report names the chain that reaches it, not just the module: %r'
          % (got[0][2] if got else None))
    check('playwright' not in names('entry.py'),
          'an import inside a function is NOT flagged (the documented limit)')
    check(names('solo.py') == [], 'a stdlib-only file is clean')
    check(names('stubbed.py') == [],
          "the repo's sys.modules stub pattern satisfies it, so the two suites "
          'that legitimately use it are not flagged: %r' % names('stubbed.py'))

print('\nEvery scripts/test_*.py is standard-library only')
tests = sorted(f for f in os.listdir(HERE)
               if f.startswith('test_') and f.endswith('.py'))
check(len(tests) > 50, 'found %d test suites to check' % len(tests))
bad = {}
for name in tests:
    found = offenders(os.path.join(HERE, name))
    if found:
        bad[name] = found
if bad:
    for name, found in sorted(bad.items()):
        for dotted, lineno, chain in found:
            print('        %s -> %s  (%s imports %r at line %d)'
                  % (name, dotted, chain[-1], dotted, lineno))
check(not bad,
      'no suite pulls in a third-party module (run-script-tests.yml installs none): '
      '%d offending suite(s)' % len(bad))

print('\nThe guard covers itself')
check(offenders(os.path.abspath(__file__)) == [],
      'this file is stdlib-only too, or it could not run in CI either')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nEvery test suite runs on the standard library alone.')
