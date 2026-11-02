#!/usr/bin/env python3
"""Minimal read-only .xlsx reader, standard library only.

WHY THIS EXISTS INSTEAD OF openpyxl
-----------------------------------
scripts/test_*.py are offline invariant checks that CI runs with NO pip packages
installed — run-script-tests.yml says so in its header, and the one step that
needed pyyaml failed on every run it ever reached. A DOR digest parser that
imported openpyxl would therefore be untestable in CI, which is exactly where the
test earns its keep. An .xlsx is a zip of XML, so reading one needs nothing but
zipfile + ElementTree.

This is deliberately NOT a general xlsx library. It reads cell TEXT from the
first (or a named) worksheet and nothing else: no formulas, no styles, no dates,
no merged cells. Numbers come back as the string the file stores, because every
consumer here re-parses them anyway and a float round-trip is how a millage rate
turns into 11.272999999999999.

THE TRAPS IT HANDLES, each of which silently corrupts a naive reader:
  * Sparse rows. A row writes only the cells that have content, so the Nth <c>
    is NOT column N. Every cell carries its own ref ("D17"), and that ref is the
    only reliable column index. A reader that just appends in document order
    shifts whole rows left wherever a blank cell appears — and blanks are
    everywhere in the DOR files.
  * Shared strings. Most text is stored once in xl/sharedStrings.xml and
    referenced by index from cells marked t="s". Reading <v> literally yields the
    integer index instead of the string, so "APPLING" comes out as "17".
  * Rich text. A shared string can be split into <r><t> runs, so the value is the
    concatenation of every descendant <t>, not the first one.
  * Inline strings (t="inlineStr") keep their text in <is><t> rather than <v>.
  * Sheet order. The zip entry names (sheet1.xml, sheet2.xml) do not necessarily
    match workbook order, so the sheet is resolved through the workbook rels the
    way the format intends.

Streaming (iterparse + clear) because a DOR digest sheet is ~1,800 rows x 425
columns, about 770k cells.
"""

import os
import re
import zipfile
from xml.etree import ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RELNS = '{http://schemas.openxmlformats.org/package/2006/relationships}'
DOCREL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

_REF_RE = re.compile(r'^([A-Z]+)')


class XlsxError(Exception):
    """The file is not a workbook we can read. Raised loudly, never swallowed."""


def col_index(ref):
    """0-based column index from a cell ref: 'A1' -> 0, 'Z9' -> 25, 'AA1' -> 26.

    Bijective base-26 on the letter prefix. A ref with no letters is a malformed
    cell and raises rather than defaulting to column 0, which would overwrite the
    county name with whatever the stray cell held.
    """
    m = _REF_RE.match(ref or '')
    if not m:
        raise XlsxError('cell has no column letters in its ref: %r' % (ref,))
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text(el):
    """All <t> text under an element, joined — handles rich-text <r> runs."""
    return ''.join(t.text or '' for t in el.iter(NS + 't'))


def _shared_strings(zf):
    try:
        raw = zf.read('xl/sharedStrings.xml')
    except KeyError:
        return []  # a workbook can legitimately store every string inline
    return [_text(si) for si in ET.fromstring(raw).iter(NS + 'si')]


def _sheet_path(zf, sheet_name=None):
    """Resolve a worksheet's zip path through the workbook relationships."""
    try:
        wb = ET.fromstring(zf.read('xl/workbook.xml'))
        rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    except KeyError as exc:
        raise XlsxError('not an xlsx workbook: missing %s' % exc)

    targets = {r.get('Id'): r.get('Target') for r in rels.iter(RELNS + 'Relationship')}
    sheets = []
    for sh in wb.iter(NS + 'sheet'):
        tgt = targets.get(sh.get(DOCREL + 'id'))
        if tgt:
            sheets.append((sh.get('name'), tgt))
    if not sheets:
        raise XlsxError('workbook declares no worksheets')

    if sheet_name is None:
        name, tgt = sheets[0]
    else:
        match = [s for s in sheets if s[0] == sheet_name]
        if not match:
            raise XlsxError('no sheet named %r; have %r'
                            % (sheet_name, [s[0] for s in sheets]))
        name, tgt = match[0]

    tgt = tgt.lstrip('/')
    for cand in (tgt, 'xl/' + tgt):
        if cand in zf.namelist():
            return name, cand
    raise XlsxError('sheet %r points at %r, which is not in the zip' % (name, tgt))


def _open(path):
    """zipfile.ZipFile, but a non-zip becomes an XlsxError.

    Without this a caller handed a PDF, an HTML error page or a real old-format
    .xls gets zipfile.BadZipFile, which says nothing about what was expected.
    DOR serves these workbooks from a /download URL that can return an HTML
    error page with a 200, so this is a live failure mode, not a hypothetical.
    """
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise XlsxError('not an xlsx file (not a zip container): %s'
                        % os.path.basename(str(path)))


def sheet_names(path):
    with _open(path) as zf:
        wb = ET.fromstring(zf.read('xl/workbook.xml'))
        return [sh.get('name') for sh in wb.iter(NS + 'sheet')]


def rows(path, sheet_name=None):
    """Yield each row as a list of strings, '' for an empty cell.

    Rows come in document order. Each list is padded to its own last populated
    column only, so callers index by position and must tolerate a short row —
    see `padded_rows` for a rectangular view.
    """
    with _open(path) as zf:
        name, sheet = _sheet_path(zf, sheet_name)
        shared = _shared_strings(zf)
        with zf.open(sheet) as fh:
            for _, el in ET.iterparse(fh, events=('end',)):
                if el.tag != NS + 'row':
                    continue
                out = []
                for c in el.iter(NS + 'c'):
                    i = col_index(c.get('r'))
                    if i >= len(out):
                        out.extend([''] * (i + 1 - len(out)))
                    typ = c.get('t')
                    if typ == 's':
                        v = c.find(NS + 'v')
                        idx = int(v.text) if v is not None and v.text else -1
                        if not 0 <= idx < len(shared):
                            raise XlsxError('shared-string index %d out of range '
                                            'at cell %s' % (idx, c.get('r')))
                        out[i] = shared[idx]
                    elif typ == 'inlineStr':
                        out[i] = _text(c)
                    else:
                        v = c.find(NS + 'v')
                        out[i] = (v.text or '') if v is not None else ''
                yield out
                el.clear()


def padded_rows(path, sheet_name=None, width=None):
    """Like rows(), but every row padded to `width` (default: the header row's).

    The DOR files write no trailing empty cells, so the millage columns — which
    are the LAST four — simply vanish from a row whose levy is blank. Padding
    makes position indexing safe.
    """
    it = rows(path, sheet_name)
    try:
        header = next(it)
    except StopIteration:
        return
    w = width or len(header)
    yield header + [''] * max(0, w - len(header))
    for r in it:
        yield (r + [''] * max(0, w - len(r)))[:max(w, len(r))]
