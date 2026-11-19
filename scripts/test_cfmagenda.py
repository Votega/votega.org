"""Offline tests for lib/cfmagenda.py (Haralson County's agenda-center.cfm).
Fixtures are trimmed copies of the real markup. Stdlib only."""
import os
import sys
import unittest
import urllib.parse
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib.cfmagenda import (parse_date, parse_fragment, discover_year_buttons,  # noqa: E402
                           type_sections, classify_files, fetch_cfmagenda_meetings)

BASE = 'https://example.gov/agenda-center.cfm'


def meeting(mid, date, title, files=()):
    inner = ''.join(
        '<div><a href="%s" target="_blank">Download File <img src="x.png"/></a>'
        '<a href="%s" target="_blank">%s</a></div>' % (h, h, t) for h, t in files)
    return ('<div class="agenda-meeting"><div class="agenda-meeting-details">'
            '<h3 class="agenda-date"><a href="download-package.cfm?id=%s" rel="nofollow">%s</a>'
            '</h3><em class="agenda-title">%s</em></div>'
            '<div class="agenda-meeting-buttons"></div>'
            '<div class="agenda-files" id="files%s">%s</div></div>'
            % (mid, date, title, mid, inner))


def button(year, tid):
    return ('<a href="" class="agenda-button" data-action="changeYear" data-year="%d" '
            'data-id="Type%s" data-type="%s">%d</a>' % (year, tid, tid, year))


PAGE = (
    '<div class="agenda-type">' + button(2026, '185') + button(2025, '185') +
    '<h2>Regular Meeting</h2><div id="Type185">' +
    meeting(2, 'Dec 15, 2026', 'Regular Meeting') +
    meeting(1, 'Nov 17, 2026', 'Regular Meeting',
            [('files/Meeting1_11.17.26 Regular Meeting Packet.pdf', 'Board Packet'),
             ('files/Meeting1_Quote.pdf', "Sheriff's Vehicle Quote")]) +
    '</div></div><div class="agenda-type">' + button(2026, '186') +
    '<h2>Regular Work Session</h2><div id="Type186">' +
    meeting(3, 'Sept 8, 2026', 'Regular Work Session - Cancelled',
            [('files/a.pdf', 'Agenda')]) + '</div></div>')

FRAG_2025 = (meeting(9, 'Dec 3, 2025', 'Regular Meeting',
                     [('files/Meeting9_120325 Agenda Regular Meeting.docx',
                       '120325 Agenda Regular Meeting.docx'),
                      ('files/Meeting9_HCBOC 120325 Minutes.docx', 'Minutes')]))


class Parse(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date('Nov 17, 2026'), '2026-11-17')
        self.assertEqual(parse_date('Sept 8, 2026'), '2026-09-08')
        self.assertIsNone(parse_date('TBD'))
        self.assertIsNone(parse_date('Feb 30, 2026'))

    def test_buttons_and_sections(self):
        self.assertEqual(discover_year_buttons(PAGE), {'185': [2026, 2025], '186': [2026]})
        secs = type_sections(PAGE)
        self.assertEqual([(t, n) for t, n, _ in secs],
                         [('185', 'Regular Meeting'), ('186', 'Regular Work Session')])

    def test_packet_is_agenda_and_unrelated_files_ignored(self):
        rows = parse_fragment(type_sections(PAGE)[0][2], BASE, 'Regular Meeting')
        by = {r['id']: r for r in rows}
        self.assertEqual(by['cfm-1']['agendaUrl'],
                         'https://example.gov/files/Meeting1_11.17.26%20Regular%20Meeting%20Packet.pdf')
        self.assertIsNone(by['cfm-1']['minutesUrl'])
        self.assertIsNone(by['cfm-2']['agendaUrl'])  # future, no files

    def test_cancelled_skipped_and_counted(self):
        stats = {}
        rows = parse_fragment(type_sections(PAGE)[1][2], BASE, 'Regular Work Session', stats)
        self.assertEqual(rows, [])
        self.assertEqual(stats['skippedCancelled'], 1)

    def test_bad_date_skipped_not_guessed(self):
        stats = {}
        rows = parse_fragment(meeting(5, 'sometime', 'Regular Meeting'), BASE, 'X', stats)
        self.assertEqual(rows, [])
        self.assertEqual(stats['skippedNoDate'], 1)

    def test_ambiguous_slot_left_empty_but_amended_loses(self):
        a, m = classify_files([('https://x/a1.pdf', 'Agenda'), ('https://x/a2.pdf', 'Agenda v2')])
        self.assertIsNone(a)
        a, m = classify_files([('https://x/a1.pdf', 'Agenda'),
                               ('https://x/a2.pdf', 'Amended Agenda')])
        self.assertEqual(a, 'https://x/a1.pdf')
        a, m = classify_files([('https://x/p.pdf', 'Packet'), ('https://x/a.pdf', 'Agenda'),
                               ('https://x/m.pdf', 'Minutes')])
        self.assertEqual((a, m), ('https://x/a.pdf', 'https://x/m.pdf'))


class Fetch(unittest.TestCase):
    def fetcher(self, fail_year=None):
        calls = []

        def fetch(url, timeout=None, label=None, data=None):
            calls.append(data)
            if data is None:
                return PAGE.encode()
            q = urllib.parse.parse_qs(data.decode())
            if fail_year and q['y'] == [str(fail_year)]:
                return None
            return FRAG_2025.encode() if q['t'] == ['185'] else b''
        fetch.calls = calls
        return fetch

    def test_older_years_posted_and_merged_newest_first(self):
        f = self.fetcher()
        meetings, bodies = fetch_cfmagenda_meetings(BASE, fetch=f, today=date(2026, 11, 19))
        self.assertEqual([m['date'] for m in meetings],
                         ['2026-12-15', '2026-11-17', '2025-12-03'])
        self.assertEqual(len(f.calls), 2)  # page + ONE POST (2025, type 185)
        q = urllib.parse.parse_qs(f.calls[1].decode(), keep_blank_values=True)
        self.assertEqual((q['y'], q['t']), (['2025'], ['185']))
        old = meetings[-1]
        self.assertTrue(old['minutesUrl'].endswith('Minutes.docx'))

    def test_past_meeting_without_agenda_or_minutes_dropped_future_kept(self):
        page = (button(2026, '185') + '<h2>Regular Meeting</h2><div id="Type185">' +
                meeting(1, 'Dec 15, 2026', 'Regular Meeting') +
                meeting(2, 'Oct 6, 2026', 'Regular Meeting',
                        [('files/q.pdf', 'Fire Dept Equip Needs Quote')]) +
                meeting(3, 'Nov 3, 2026', 'Regular Meeting', [('files/a.pdf', 'Agenda')]) +
                '</div>')
        got, _ = fetch_cfmagenda_meetings(BASE, fetch=lambda *a, **k: page.encode(),
                                          today=date(2026, 11, 19))
        self.assertEqual([m['id'] for m in got], ['cfm-1', 'cfm-3'])

    def test_failed_year_refuses_partial_history(self):
        self.assertEqual(fetch_cfmagenda_meetings(BASE, fetch=self.fetcher(fail_year=2025)),
                         (None, None))

    def test_no_documents_anywhere_is_layout_change(self):
        page = (button(2026, '185') + '<h2>Regular Meeting</h2><div id="Type185">' +
                meeting(1, 'Nov 17, 2026', 'Regular Meeting') + '</div>')
        self.assertEqual(fetch_cfmagenda_meetings(BASE, fetch=lambda *a, **k: page.encode()),
                         (None, None))


if __name__ == '__main__':
    unittest.main()
