#!/usr/bin/env python3
"""Municode Meetings cells with both an HTML view and a PDF (Columbus, GA).

The agenda cell lists "Agenda (HTML)" first; the PDF is the citable document, and
hrefs arrive HTML-escaped (&amp;), which must be decoded.

Run: python scripts/test_teammunicode_links.py      (no network)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.teammunicode import _cell

PDF = 'https://x.blob.core.usgovcloudapi.net/columga-pubu/MEET-Agenda-1.pdf'
HTML = 'https://meetings.municode.com/adaHtmlDocument/index?cc=COLUMGA&amp;me=1&amp;ip=False'
failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


both = '<td class="views-field-field-agendas"><a href="%s">HTML</a><a href="%s">PDF</a></td>' % (HTML, PDF)
check('pdf preferred', _cell(both, 'field-agendas'), PDF)
only_html = '<td class="views-field-field-agendas"><a href="%s">HTML</a></td>' % HTML
check('html unescaped when it is all there is', _cell(only_html, 'field-agendas'),
      'https://meetings.municode.com/adaHtmlDocument/index?cc=COLUMGA&me=1&ip=False')
check('empty cell', _cell('<td class="views-field-field-agendas"> </td>', 'field-agendas'), None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
