#!/usr/bin/env python3
"""build_entity_pages.main() must report a degraded run, and must not let a degraded
run rewrite the lastmod baseline the next run is compared against.

Stdlib only; builders and file paths are stubbed so no site data is read.
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_entity_pages as b

PATCHED = (
    "LASTMOD_STATE_PATH", "ENTITIES_DIR", "ENTITY_URLS_PATH", "SERVED_ENTITY_URLS_PATH",
    "FEATURED_RACES_PATH", "SHARE_MANIFEST_PATH", "CATEGORY_BUILDERS",
    "build_directory_pages", "load", "plan_candidate_permalinks", "featured_races",
)


def run_main(prior, builders, directory=lambda p, n: 0):
    """Run main() against a temp dir; return (exit code, state file after, stdout)."""
    tmp = tempfile.mkdtemp()
    state = os.path.join(tmp, "lastmod.json")
    with open(state, "w", encoding="utf-8") as fh:
        json.dump(prior, fh)
    saved = {k: getattr(b, k) for k in PATCHED}
    try:
        b.LASTMOD_STATE_PATH = state
        b.ENTITIES_DIR = os.path.join(tmp, "entities")
        b.ENTITY_URLS_PATH = os.path.join(tmp, "u1.json")
        b.SERVED_ENTITY_URLS_PATH = os.path.join(tmp, "u2.json")
        b.FEATURED_RACES_PATH = os.path.join(tmp, "f.json")
        b.SHARE_MANIFEST_PATH = os.path.join(tmp, "share", "m.json")
        b.CATEGORY_BUILDERS = builders
        b.build_directory_pages = directory
        b.load = lambda name: {"records": [], "races": []}
        b.plan_candidate_permalinks = lambda *a: {}
        b.featured_races = lambda d: []
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = b.main()
        with open(state, encoding="utf-8") as fh:
            after = json.load(fh)
        return code, after, out.getvalue()
    finally:
        for k, v in saved.items():
            setattr(b, k, v)


def make_builder(n, key_prefix):
    def build(records, urls, prior, new_state):
        for i in range(n):
            new_state[f"{key_prefix}{i}"] = {"h": "x"}
        return n
    return build


def boom(records, urls, prior, new_state):
    raise RuntimeError("simulated failure")


PRIOR = {f"a{i}": {"h": "x"} for i in range(50)}
PRIOR.update({f"b{i}": {"h": "x"} for i in range(50)})


def test_regression_threshold():
    assert not b.state_regressed(0, 0)
    assert not b.state_regressed(0, 500)           # cold cache is not a regression
    assert not b.state_regressed(100, 100)
    assert not b.state_regressed(100, 90)          # exactly the limit
    assert b.state_regressed(100, 89)
    assert not b.state_regressed(100, 150)         # growth is fine


def test_healthy_run_updates_state():
    code, after, out = run_main(PRIOR, [("A", make_builder(50, "a")), ("B", make_builder(50, "b"))])
    assert code == 0
    assert len(after) == 100
    assert "degraded=no" in out and "failed=none" in out


def test_failed_category_exits_nonzero_and_keeps_baseline():
    code, after, out = run_main(PRIOR, [("A", make_builder(50, "a")), ("B", boom)])
    assert code == 2
    assert after == PRIOR, "a degraded run must not shrink the baseline"
    assert "failed=B" in out and "degraded=yes" in out


def test_silent_shrink_is_caught_even_without_an_exception():
    code, after, out = run_main(PRIOR, [("A", make_builder(50, "a")), ("B", make_builder(10, "b"))])
    assert code == 2
    assert after == PRIOR
    assert "failed=none" in out and "degraded=yes" in out


def test_directory_failure_counts():
    def bad_dir(prior, new_state):
        raise RuntimeError("dir")
    code, after, out = run_main(PRIOR, [("A", make_builder(50, "a")), ("B", make_builder(50, "b"))],
                                directory=bad_dir)
    assert code == 2 and "failed=Directory" in out


def test_cold_cache_is_healthy():
    code, after, out = run_main({}, [("A", make_builder(5, "a"))])
    assert code == 0 and len(after) == 5


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
