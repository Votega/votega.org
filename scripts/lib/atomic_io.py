#!/usr/bin/env python3
"""Crash-safe file writes for the build-time data generators in scripts/.

Every data writer used to do the naive thing:

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ...)

That opens the *real* output file for writing and streams into it. If the
process is interrupted mid-dump — an OOM kill, a runner torn down, a SIGKILL,
a bug that raises partway through serialization — the destination is left
truncated in place. Because these outputs are committed source files served by
the site (races.json, ga-bills.json, the members/votes blobs), a half-written
file can then be committed and shipped.

The fix is the standard write-temp-then-rename idiom: write the whole payload to
a temp file in the *same directory*, fsync it, then `os.replace()` it onto the
target. `os.replace` is atomic on POSIX and Windows, so a reader (or a crash)
ever only sees the complete old file or the complete new one — never a partial
write. Writing to the same directory guarantees the rename is a metadata-only
move on one filesystem rather than a cross-device copy.

Usage:

    from lib.atomic_io import write_json_atomic, atomic_write

    write_json_atomic(OUTPUT_FILE, output, indent=2)          # JSON convenience
    write_json_atomic(OUTPUT_FILE, output, separators=(",", ":"))

    with atomic_write(REVIEW_CSV, newline="") as f:            # anything else
        csv.writer(f).writerows(rows)
"""

import json
import os
import tempfile
from contextlib import contextmanager


@contextmanager
def atomic_write(path, mode="w", encoding="utf-8", newline=None):
    """Yield a file handle whose contents replace `path` atomically on success.

    Writes to a temp file in the same directory and `os.replace()`s it onto the
    target only after the block completes and the data is flushed to disk. If the
    block raises, the temp file is removed and the original `path` is untouched.
    Creates the parent directory if needed. Text mode by default; pass
    `newline=""` for csv writers, or `mode="wb"` for binary output.
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    # Same-directory temp so os.replace is an atomic intra-filesystem rename.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".swap")
    binary = "b" in mode
    try:
        open_kwargs = {} if binary else {"encoding": encoding, "newline": newline}
        with os.fdopen(fd, mode, **open_kwargs) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path, obj, *, ensure_ascii=False, **json_kwargs):
    """Serialize `obj` to `path` as JSON, atomically.

    Drop-in replacement for the `open(path,"w")` + `json.dump(obj, f, ...)` pair.
    `ensure_ascii` defaults to False to match every existing call site; all other
    keyword args (indent, separators, sort_keys, default, ...) pass through to
    json.dump unchanged.
    """
    with atomic_write(path) as f:
        json.dump(obj, f, ensure_ascii=ensure_ascii, **json_kwargs)
