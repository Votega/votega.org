"""Read the rows of a simple .xlsx worksheet with the standard library only.

Enough for the reapportionment office's block-equivalency workbooks (one sheet,
two columns, ~233k rows): it reads the shared-strings table and the first
worksheet's cell values, and nothing else (no styles, formulas or dates). It
exists so the seat-registry build and its tests need no openpyxl, which the
offline CI job does not install. Cells are returned as strings, or None for an
empty cell; a row's cells are placed by their column letter, so a blank cell in
the middle of a row does not shift the cells after it.
"""
import re
import zipfile

_ROW = re.compile(r"<row\b[^>]*>(.*?)</row>", re.S)
_CELL = re.compile(r'<c\b[^>]*?r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_VALUE = re.compile(r"<v>(.*?)</v>", re.S)
_INLINE = re.compile(r"<is>(.*?)</is>", re.S)
_SI = re.compile(r"<si>(.*?)</si>", re.S)
_TAG = re.compile(r"<[^>]+>")
_ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&"))


def _unescape(text):
    for ent, ch in _ENTITIES:
        text = text.replace(ent, ch)
    return text


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _first_sheet(z):
    names = sorted(n for n in z.namelist()
                   if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not names:
        raise ValueError("workbook has no worksheet")
    return names[0]


def read_rows(path):
    """Yield each row of the first worksheet as a list of str-or-None cells."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            strings = [_unescape(_TAG.sub("", si)) for si in _SI.findall(xml)]
        sheet = z.read(_first_sheet(z)).decode("utf-8")
    for row_xml in _ROW.findall(sheet):
        cells = {}
        for col, attrs, inner in _CELL.findall(row_xml):
            inner = inner or ""
            if 't="s"' in attrs:
                m = _VALUE.search(inner)
                val = strings[int(m.group(1))] if m else None
            elif 't="inlineStr"' in attrs:
                m = _INLINE.search(inner)
                val = _unescape(_TAG.sub("", m.group(1))) if m else None
            else:
                m = _VALUE.search(inner)
                val = _unescape(m.group(1)) if m else None
            cells[_col_index(col)] = val
        width = max(cells) + 1 if cells else 0
        yield [cells.get(i) for i in range(width)]
