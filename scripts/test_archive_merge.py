"""Tests for lib/archive_merge.py and the archive: sub-block in build_place.
Offline, stdlib only (generate_place_meetings imports yaml, so that part is
skipped if PyYAML is absent)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from lib.archive_merge import merge_archive, carry_forward_history  # noqa: E402


def m(date, body='Board of Commissioners', **kw):
    d = {'body': body, 'date': date, 'id': kw.pop('id', date), 'title': body,
         'agendaUrl': None, 'minutesUrl': None, 'videoUrl': None,
         'hasPreviousVersions': False}
    d.update(kw)
    return d


class MergeTests(unittest.TestCase):
    def test_primary_wins_overlap_and_order_is_newest_first(self):
        p = [m('2026-02-10', agendaUrl='P')]
        a = [m('2026-02-10', agendaUrl='A'), m('2026-01-27'), m('2022-09-13')]
        out = merge_archive(p, a)
        self.assertEqual([x['date'] for x in out],
                         ['2026-02-10', '2026-01-27', '2022-09-13'])
        self.assertEqual(out[0]['agendaUrl'], 'P')

    def test_same_date_different_body_both_kept(self):
        p = [m('2026-02-10')]
        a = [m('2026-02-10', body='Planning Commission')]
        self.assertEqual(len(merge_archive(p, a)), 2)

    def test_body_key_is_case_and_space_insensitive(self):
        p = [m('2026-02-10', body='Board  of Commissioners')]
        a = [m('2026-02-10', body='board of commissioners')]
        self.assertEqual(len(merge_archive(p, a)), 1)

    def test_empty_archive(self):
        p = [m('2026-02-10')]
        self.assertEqual(merge_archive(p, None), p)

    def test_carry_forward_only_older_than_primary(self):
        p = [m('2026-02-10'), m('2026-03-10')]
        prev = [m('2026-03-10'), m('2026-02-10'), m('2026-01-27'), m('2022-09-13')]
        out = carry_forward_history(p, prev)
        self.assertEqual([x['date'] for x in out], ['2026-01-27', '2022-09-13'])
        self.assertEqual(carry_forward_history([], prev), [])


class BuildPlaceTests(unittest.TestCase):
    def setUp(self):
        try:
            import generate_place_meetings as g  # noqa: F401
        except ImportError:
            self.skipTest('PyYAML not installed')
        self.g = g

    def place(self, archive):
        cfg = {'platform': 'civicclerk', 'subdomain': 'x',
               'body_map': [{'match': 'Board of Commissioners',
                             'label': 'Board of Commissioners'}]}
        if archive:
            cfg['archive'] = {'platform': 'granicus', 'agendas_url': 'u',
                              'body_map': [{'match': 'Board of Commissioners',
                                            'label': 'Board of Commissioners'}]}
        return {'slug': 'x', 'name': 'X County', 'type': 'county', 'fips': '1',
                'domains': {'meetings': cfg}}

    def run_build(self, archive_rows, previous=()):
        g = self.g
        primary = [m('2026-02-10', body='Board of Commissioners')]

        def fake(cfg, previous=None):
            if cfg['platform'] == 'civicclerk':
                return [dict(x) for x in primary], ['Board of Commissioners']
            return archive_rows, None
        with mock.patch.object(g, 'fetch_meetings', fake), \
                mock.patch.object(g, 'load_previous', lambda s: list(previous)):
            return g.build_place(self.place(True))

    def test_archive_merged_and_body_scoped(self):
        out = self.run_build([
            m('2026-01-27', body='Board of Commissioners Public Hearing -- 8:00 A.M.'),
            m('2022-09-13'), m('2022-09-14', body='Some Other Board')])
        dates = [x['date'] for x in out['meetings']]
        self.assertEqual(dates, ['2026-02-10', '2026-01-27', '2022-09-13'])
        self.assertEqual(out['bodies'], ['Board of Commissioners'])
        self.assertEqual(out['metadata']['count'], 3)
        ids = [x['id'] for x in out['meetings']]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(ids[-1].startswith('granicus:'))

    def test_archive_outage_keeps_history(self):
        prev = [m('2026-02-10'), m('2025-05-06')]
        out = self.run_build(None, previous=prev)
        self.assertEqual([x['date'] for x in out['meetings']],
                         ['2026-02-10', '2025-05-06'])


if __name__ == '__main__':
    unittest.main()
