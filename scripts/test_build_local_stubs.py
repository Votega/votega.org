"""Offline tests for scripts/build_local_stubs.py (no network, no PyYAML)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_local_stubs import build_stubs, letters  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def place(fips, name, county, typ='city', active='true', consolidated=''):
    return {'place_fips': fips, 'place_name': name, 'place_type': typ, 'county_fips': county,
            'consolidated_county_fips': consolidated, 'active': active}


def pc(fips, county, primary, share):
    return {'place_fips': fips, 'county_fips': county,
            'is_primary_county': 'true' if primary else 'false', 'population_share': str(share)}


COUNTIES = [{'county_fips': '13115', 'county_name': 'Floyd'},
            {'county_fips': '13067', 'county_name': 'Cobb'},
            {'county_fips': '13121', 'county_name': 'Fulton'},
            {'county_fips': '13089', 'county_name': 'DeKalb'}]
PLACES = [
    place('1366668', 'Rome', '13115'),
    place('1314108', 'Cave Spring', '13115'),
    place('1349756', 'Marietta', '13067'),
    place('1304000', 'Atlanta', '13121'),                      # in the registry
    place('1380000', 'Chamblee', '13089'),
    place('1300001', 'Old Town', '13115', active='false'),     # dissolved
    place('1300002', 'Athens-Clarke County unified government', '13059',
          typ='consolidated_government', consolidated='13059'),
    place('1300003', 'Edge City', '13067'),                    # spans Cobb/Fulton/DeKalb
]
PCS = [pc('1366668', '13115', True, 1), pc('1314108', '13115', True, 1),
       pc('1349756', '13067', True, 1), pc('1380000', '13089', True, 1),
       pc('1300003', '13067', True, 0.6), pc('1300003', '13121', False, 0.4),
       pc('1300003', '13089', False, 0)]                        # a zero-resident sliver


class Build(unittest.TestCase):
    def setUp(self):
        self.stubs, self.unmatched = build_stubs(PLACES, PCS, COUNTIES, {'atlanta', 'socialcircle'})
        self.by = {c['name']: c for c in self.stubs['counties']}

    def names(self, county):
        return [c['name'] for c in self.by[county]['cities']]

    def test_every_county_listed_with_slug(self):
        self.assertEqual(sorted(self.by), ['Cobb', 'DeKalb', 'Floyd', 'Fulton'])
        self.assertEqual(self.by['DeKalb']['slug'], 'dekalb')
        self.assertEqual(self.stubs['metadata']['count'], 4)

    def test_city_under_primary_county_sorted_by_name(self):
        self.assertEqual(self.names('Floyd'), ['Cave Spring', 'Rome'])

    def test_registry_city_not_stubbed_and_reported_unmatched_when_absent(self):
        self.assertNotIn('Atlanta', self.names('Fulton'))
        self.assertEqual(self.unmatched, {'socialcircle'})

    def test_inactive_and_consolidated_skipped(self):
        every = [c['name'] for county in self.stubs['counties'] for c in county['cities']]
        self.assertNotIn('Old Town', every)
        self.assertFalse([n for n in every if 'unified' in n])

    def test_multi_county_city_chips_skip_zero_share(self):
        self.assertIn('Edge City', self.names('Cobb'))
        self.assertEqual([c['name'] for c in self.by['Fulton']['alsoCities']], ['Edge City'])
        self.assertEqual(self.by['Fulton']['alsoCities'][0]['primaryCounty'], 'Cobb')
        self.assertEqual(self.by['DeKalb']['alsoCities'], [])   # share 0

    def test_city_count_matches(self):
        self.assertEqual(self.stubs['metadata']['cityCount'], 5)

    def test_letters_key(self):
        self.assertEqual(letters('City of Social Circle'), letters('Social Circle'))
        self.assertEqual(letters('LaFayette'), 'lafayette')
        self.assertEqual(letters('Fort Oglethorpe'), letters('fort-oglethorpe'))


class Committed(unittest.TestCase):
    """The committed _data/local_stubs.json must stay well-formed."""

    def test_committed_file(self):
        p = os.path.join(ROOT, '_data', 'local_stubs.json')
        if not os.path.exists(p):
            self.skipTest('no committed stubs file')
        d = json.load(open(p, encoding='utf-8'))
        self.assertEqual(len(d['counties']), 159)
        ids = [c['id'] for k in d['counties'] for c in k['cities']]
        self.assertEqual(len(ids), len(set(ids)), 'a city appears under two counties')
        self.assertEqual(d['metadata']['cityCount'], len(ids))
        for k in d['counties']:
            self.assertTrue(k['slug'] and k['name'] and k['fips'].startswith('13'))
        for forbidden in ('atlanta', 'savannah', 'carrollton'):
            self.assertNotIn(forbidden, [letters(c['name']) for k in d['counties'] for c in k['cities']])


if __name__ == '__main__':
    unittest.main()
