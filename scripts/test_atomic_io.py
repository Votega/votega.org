#!/usr/bin/env python3
"""Offline checks for scripts/lib/atomic_io.py, which nearly every data writer uses.

What it promises: a write either fully replaces the target or leaves it as it was,
no temp file is left behind, and the result has the permissions a plain open() would
give it. Runs in a temp directory. Exits 0 on success, 1 on failure.

Usage:
  python scripts/test_atomic_io.py
"""

import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import atomic_write, write_json_atomic  # noqa: E402

failures = []
POSIX = os.name == "posix"


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def leftovers(directory):
    return sorted(n for n in os.listdir(directory) if n.startswith(".tmp-"))


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8", "newline": ""})) as f:
        return f.read()


def main():
    with tempfile.TemporaryDirectory() as d:
        print("writes")
        p = os.path.join(d, "out.json")
        write_json_atomic(p, {"name": "Café", "n": [1, 2]}, indent=2)
        check("JSON round-trips", json.loads(read(p)), {"name": "Café", "n": [1, 2]})
        check("non-ASCII is written as-is by default", "Café" in read(p), True)
        write_json_atomic(p, {"x": 1}, separators=(",", ":"))
        check("json.dump keyword args pass through", read(p), '{"x":1}')
        check("no temp file is left after a write", leftovers(d), [])

        nested = os.path.join(d, "a", "b", "c.json")
        write_json_atomic(nested, [])
        check("missing parent directories are created", os.path.exists(nested), True)

        csvp = os.path.join(d, "rows.csv")
        with atomic_write(csvp, newline="") as f:
            f.write("a,b\r\n")
        check("newline='' leaves line endings alone", read(csvp), "a,b\r\n")

        binp = os.path.join(d, "blob.bin")
        with atomic_write(binp, mode="wb") as f:
            f.write(b"\x00\xff")
        check("binary mode writes bytes", read(binp, "rb"), b"\x00\xff")

        print("failures leave the target untouched")
        write_json_atomic(p, {"keep": True})
        try:
            with atomic_write(p) as f:
                f.write('{"half": ')
                raise RuntimeError("simulated crash mid-write")
        except RuntimeError:
            pass
        check("the original survives an exception in the block", json.loads(read(p)), {"keep": True})
        check("the temp file is removed after an exception", leftovers(d), [])

        try:
            write_json_atomic(p, {"bad": object()})
        except TypeError:
            pass
        check("the original survives an unserialisable object", json.loads(read(p)), {"keep": True})
        check("no temp file after a failed serialisation", leftovers(d), [])

        try:
            with atomic_write(os.path.join(d, "never.json")) as f:
                f.write("x")
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            pass
        check("an interrupt never creates the target",
              os.path.exists(os.path.join(d, "never.json")), False)
        check("an interrupt leaves no temp file", leftovers(d), [])

        print("permissions")
        if POSIX:
            umask = os.umask(0o022)
            try:
                fresh = os.path.join(d, "fresh.json")
                write_json_atomic(fresh, {})
                check("a new file gets 0666 & ~umask, not mkstemp's 0600",
                      stat.S_IMODE(os.stat(fresh).st_mode), 0o644)
                os.chmod(fresh, 0o600)
                write_json_atomic(fresh, {"again": 1})
                check("rewriting a restricted file keeps it restricted",
                      stat.S_IMODE(os.stat(fresh).st_mode), 0o600)
            finally:
                os.umask(umask)
        else:
            print("  skip POSIX permission checks (not POSIX)")

    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
