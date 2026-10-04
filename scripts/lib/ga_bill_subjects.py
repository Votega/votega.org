#!/usr/bin/env python3
"""Local/municipal subject inference for GA bills — shared by the bill producers.

Georgia bill titles follow 'Subject; detail; verb phrase', so the first segment
identifies the subject area. A bill with no topical subject tag but a locality in
that segment is local/municipal. This logic (and the county list) was lifted verbatim
from the original Open States bills producer so the SOAP producer tags local bills
identically; it is the runtime fallback under the frozen OS-subjects overlay
(assets/data/ga-bills-subjects-base.json)."""

import re

# All 159 Georgia counties (source: GA General Assembly reapportionment data,
# mirrored in assets/scripts/ga-districts.js).
GA_COUNTIES = {
    'Appling','Atkinson','Bacon','Baker','Baldwin','Banks','Barrow','Bartow',
    'Ben Hill','Berrien','Bibb','Bleckley','Brantley','Brooks','Bryan','Bulloch',
    'Burke','Butts','Calhoun','Camden','Candler','Carroll','Catoosa','Charlton',
    'Chatham','Chattahoochee','Chattooga','Cherokee','Clarke','Clay','Clayton',
    'Clinch','Cobb','Coffee','Colquitt','Columbia','Cook','Coweta','Crawford',
    'Crisp','Dade','Dawson','Decatur','DeKalb','Dodge','Dooly','Dougherty',
    'Douglas','Early','Echols','Effingham','Elbert','Emanuel','Evans','Fannin',
    'Fayette','Floyd','Forsyth','Franklin','Fulton','Gilmer','Glascock','Glynn',
    'Gordon','Grady','Greene','Gwinnett','Habersham','Hall','Hancock','Haralson',
    'Harris','Hart','Heard','Henry','Houston','Irwin','Jackson','Jasper',
    'Jeff Davis','Jefferson','Jenkins','Johnson','Jones','Lamar','Lanier',
    'Laurens','Lee','Liberty','Lincoln','Long','Lowndes','Lumpkin','Macon',
    'Madison','Marion','McDuffie','McIntosh','Meriwether','Miller','Mitchell',
    'Monroe','Montgomery','Morgan','Murray','Muscogee','Newton','Oconee',
    'Oglethorpe','Paulding','Peach','Pickens','Pierce','Pike','Polk','Pulaski',
    'Putnam','Quitman','Rabun','Randolph','Richmond','Rockdale','Schley',
    'Screven','Seminole','Spalding','Stephens','Stewart','Sumter','Talbot',
    'Taliaferro','Tattnall','Taylor','Telfair','Terrell','Thomas','Tift','Toombs',
    'Towns','Treutlen','Troup','Turner','Twiggs','Union','Upson','Walker',
    'Walton','Ware','Warren','Washington','Wayne','Webster','Wheeler','White',
    'Whitfield','Wilcox','Wilkes','Wilkinson','Worth',
}

# Matches any GA county name as a whole word. Longest-first so "Ben Hill" matches
# before "Hill".
_COUNTY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(GA_COUNTIES, key=len, reverse=True)) + r')\b'
)

# A county name alongside one of these in the first title segment marks a local bill
# (e.g. "Brooks County Development Authority", "Cobb Judicial Circuit").
_LOCAL_ENTITY_KW = {
    'Authority', 'Airport', 'Commission', 'Development', 'School',
    'Water', 'Recreation', 'Library', 'Housing', 'Transit',
    'Utility', 'Utilities', 'Circuit',
}


def infer_local_subject(title):
    """['Local / Municipal'] if the title's first segment names a GA locality, else []."""
    if not title or ';' not in title:
        return []
    first_seg = title.split(';')[0].strip().strip('"\'')

    if first_seg.startswith(('City of ', 'Town of ', 'County of ')):
        return ['Local / Municipal']
    for suffix in (', City of', ', Town of'):
        if first_seg.endswith(suffix):
            return ['Local / Municipal']
    for suffix in (', County', ' County'):
        if first_seg.endswith(suffix):
            return ['Local / Municipal']
    if _COUNTY_RE.search(first_seg) and any(kw in first_seg for kw in _LOCAL_ENTITY_KW):
        return ['Local / Municipal']
    if first_seg in GA_COUNTIES:
        return ['Local / Municipal']
    return []
