/*
 * Unit tests for assets/scripts/find-my-reps-view.js.
 *
 * Run: node --test tests/js/
 *
 * These cover what a voter on /find-my-reps depends on being right: that a
 * county expands to every district it touches, that an address resolves to
 * exactly one per chamber, that a chamber we could not determine is omitted
 * rather than shown as a vacancy, that a location carried over from another page
 * this visit is only honoured when it is actually usable, and that a quote in a
 * name or a URL cannot break out of the markup.
 *
 * The real county→district tables and the committed rosters are used rather than
 * fixtures, so a reapportionment update or a roster change that would break the
 * page breaks a test here first. Rendering into a real DOM is deliberately not
 * tested — same reasoning as votes-table.test.js.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const win = loadBrowserModules(
  'assets/scripts/html-escape.js',
  'assets/scripts/find-my-reps-view.js'
);
const View = win.FindMyRepsView;

const readJson = rel => JSON.parse(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8'));
const FED = readJson('assets/data/current-members.json');
const GA = readJson('assets/data/ga-members.json');

// ga-districts.js is a plain script of top-level consts, not a window module, so
// it is evaluated for its values rather than loaded through the stub window.
const MAPS = (() => {
  const src = fs.readFileSync(path.join(REPO_ROOT, 'assets/scripts/ga-districts.js'), 'utf8');
  // eslint-disable-next-line no-new-func
  return new Function(`${src}; return {
    usHouse: COUNTY_US_HOUSE_DISTRICTS,
    stateSenate: COUNTY_SENATE_DISTRICTS,
    stateHouse: COUNTY_HOUSE_DISTRICTS,
  };`)();
})();

const URLS = {
  fedHref: m => `/us-congress/${m.bioguideId}/`,
  gaHref: m => `/ga-legislators/${encodeURIComponent(m.id)}/`,
};

const countRows = html => (html.match(/class="fmr-repcard"/g) || []).length;
const countSections = html => (html.match(/class="fmr-office"/g) || []).length;

test('normalizeAddressLoc wraps one district per chamber', () => {
  const loc = View.normalizeAddressLoc({
    matchedAddress: '123 Peachtree St NE, ATLANTA, GA, 30303',
    county: 'Fulton', usHouse: 5, stateSenate: 39, stateHouse: 57,
  });
  assert.strictEqual(loc.source, 'address');
  assert.deepStrictEqual(loc.usHouse, [5]);
  assert.deepStrictEqual(loc.stateSenate, [39]);
  assert.deepStrictEqual(loc.stateHouse, [57]);
});

test('a district the geocoder could not resolve becomes an empty array', () => {
  const loc = View.normalizeAddressLoc({ county: 'Fulton', usHouse: 5, stateSenate: null, stateHouse: 57 });
  assert.deepStrictEqual(loc.stateSenate, []);
});

test('an unresolved chamber is omitted, not rendered as a vacancy', () => {
  const loc = View.normalizeAddressLoc({ matchedAddress: 'X', county: 'Fulton', usHouse: 5, stateSenate: null, stateHouse: 57 });
  const html = View.renderReps(loc, FED, GA, URLS);
  assert.strictEqual(countSections(html), 3, 'U.S. Senate + U.S. House + GA House');
  assert.ok(!/currently vacant/.test(html), 'no false vacancy for the missing chamber');
  assert.ok(!/Georgia State Senate/.test(html));
});

test('the address view renders both senators plus one row per chamber', () => {
  const loc = View.normalizeAddressLoc({
    matchedAddress: '123 Peachtree St NE, ATLANTA, GA, 30303',
    county: 'Fulton', usHouse: 5, stateSenate: 39, stateHouse: 57,
  });
  const html = View.renderReps(loc, FED, GA, URLS);
  assert.strictEqual(countSections(html), 4);
  assert.strictEqual(countRows(html), 5, 'two U.S. senators + three single-district seats');
  assert.match(html, /Showing representatives for/);
  assert.ok(!/currently vacant|No sitting/.test(html));
});

test('the U.S. House row names the member who actually holds that district', () => {
  const ga5 = FED.members.find(m => m.state === 'Georgia' && m.district === 5 && m.currentMember !== false);
  assert.ok(ga5, 'the roster carries a sitting GA-05 member');
  const html = View.renderReps(View.normalizeAddressLoc({ county: 'Fulton', usHouse: 5 }), FED, GA, URLS);
  assert.ok(html.includes(ga5.lastName), `expected ${ga5.lastName} in the GA-05 row`);
  assert.ok(html.includes(`/us-congress/${ga5.bioguideId}/`), 'and links their profile');
});

test('departed members never fill a seat', () => {
  const departed = GA.members.find(m => ['Resigned', 'Removed', 'Deceased'].includes(m.status));
  assert.ok(departed, 'the roster carries at least one departed member');
  const key = departed.chamber === 'Senate' ? 'stateSenate' : 'stateHouse';
  const loc = View.countyLoc('Fulton', MAPS);
  loc[key] = [departed.district];
  loc.usHouse = []; loc.stateSenate = key === 'stateSenate' ? loc.stateSenate : [];
  loc.stateHouse = key === 'stateHouse' ? loc.stateHouse : [];
  const html = View.renderReps(loc, FED, GA, URLS);
  assert.ok(!html.includes(departed.name), `${departed.name} (${departed.status}) must not be shown as the sitting member`);
});

test('countyLoc returns every district the county touches, ascending', () => {
  const loc = View.countyLoc('Bibb', MAPS);
  assert.strictEqual(loc.source, 'county');
  assert.deepStrictEqual(loc.stateHouse, MAPS.stateHouse.Bibb.slice().sort((a, b) => a - b));
  assert.deepStrictEqual(loc.usHouse, MAPS.usHouse.Bibb.slice().sort((a, b) => a - b));
  assert.ok(loc.stateHouse.length > 1, 'Bibb spans several state House districts');
});

test('a county the tables do not know yields no districts rather than throwing', () => {
  const loc = View.countyLoc('Atlantis', MAPS);
  assert.deepStrictEqual([loc.usHouse, loc.stateSenate, loc.stateHouse], [[], [], []]);
  assert.strictEqual(View.renderReps(loc, FED, GA, URLS).includes('fmr-office'), true,
    'the senators section still renders — they represent the whole state');
});

test('missing county tables (ga-districts.js absent) degrade quietly', () => {
  const loc = View.countyLoc('Bibb', null);
  assert.deepStrictEqual([loc.usHouse, loc.stateSenate, loc.stateHouse], [[], [], []]);
  assert.deepStrictEqual(View.countyNames(null), []);
});

test('every Georgia county resolves districts in all three chambers, and each matches a sitting member', () => {
  const counties = View.countyNames(MAPS.stateHouse);
  assert.strictEqual(counties.length, 159, 'Georgia has 159 counties');
  const empty = [];
  const unmatched = [];
  for (const county of counties) {
    const loc = View.countyLoc(county, MAPS);
    if (!loc.usHouse.length || !loc.stateSenate.length || !loc.stateHouse.length) empty.push(county);
    const html = View.renderReps(loc, FED, GA, URLS);
    if (/currently vacant|No sitting/.test(html)) unmatched.push(county);
    assert.match(html, /every district that touches/, `${county} should carry the county caveat`);
  }
  assert.deepStrictEqual(empty, [], 'counties with a chamber missing from the tables');
  assert.deepStrictEqual(unmatched, [], 'counties with a district no sitting member holds');
});

test('the county view renders a row per touching district plus both senators', () => {
  const loc = View.countyLoc('Gwinnett', MAPS);
  const expected = 2 + loc.usHouse.length + loc.stateSenate.length + loc.stateHouse.length;
  const html = View.renderReps(loc, FED, GA, URLS);
  assert.strictEqual(countRows(html), expected);
  assert.match(html, /narrow this down/, 'and tells the voter a county is not a district');
});

test('carriedLocation honours a stored address location and labels its districts', () => {
  const carried = View.carriedLocation(
    { source: 'address', county: 'Fulton', usHouse: 5, stateHouse: 57, stateSenate: 39 }, MAPS);
  assert.ok(carried);
  assert.deepStrictEqual(carried.loc.stateHouse, [57]);
  assert.strictEqual(carried.where, 'State House 57 · State Senate 39 · U.S. House 5');
  assert.strictEqual(carried.county, null, 'no county dropdown to preselect for an address');
});

test('carriedLocation preselects the county for a stored county location', () => {
  const carried = View.carriedLocation(
    { source: 'county', county: 'Bibb', usHouse: null, stateHouse: null, stateSenate: null }, MAPS);
  assert.ok(carried);
  assert.strictEqual(carried.county, 'Bibb');
  assert.strictEqual(carried.where, 'Bibb County');
  assert.ok(carried.loc.stateHouse.length > 1, 'and expands to the county overlap view');
});

test('carriedLocation rejects everything unusable instead of showing an empty banner', () => {
  for (const stored of [
    null,
    undefined,
    {},
    { source: 'address' },                                   // no districts at all
    { source: 'address', usHouse: null, stateHouse: null, stateSenate: null },
    { source: 'county' },                                    // no county
    { source: 'county', county: 'Atlantis' },                // unknown county
    { source: 'nonsense', usHouse: 5 },
  ]) {
    assert.strictEqual(View.carriedLocation(stored, MAPS), null, `should reject ${JSON.stringify(stored)}`);
  }
});

test('a stored county location is rejected when the tables are missing', () => {
  assert.strictEqual(View.carriedLocation({ source: 'county', county: 'Bibb' }, null), null);
});

test('a quote in a name or a URL cannot break out of the markup', () => {
  // The page used to escape by DOM round-trip, which leaves " and ' intact —
  // and these values land inside href="…" and src="…".
  const fed = { members: [{
    state: 'Georgia', currentMember: true, firstName: 'Earl L. "Buddy"', lastName: 'Carter',
    bioguideId: 'X" onerror="alert(1)', district: 1,
    depiction: { imageUrl: 'https://example.test/p.jpg" onload="alert(1)' },
    terms: { item: [{ chamber: 'House of Representatives' }] },
  }] };
  const html = View.renderReps(
    View.normalizeAddressLoc({ county: 'Chatham', usHouse: 1 }), fed, { members: [] },
    { fedHref: m => `/us-congress/${m.bioguideId}/`, gaHref: () => '#' });
  // Once the quote is entity-encoded the "onerror=" text is inert *inside* the
  // attribute value, so the property to assert is that no literal quote closed
  // the attribute early — not that the substring is absent.
  assert.ok(!html.includes('" onerror="'), 'no literal quote closes the href early');
  assert.ok(!html.includes('" onload="'), 'no literal quote closes the src early');
  assert.match(html, /&quot; onerror=&quot;/, 'the href quotes are entity-encoded');
  assert.match(html, /&quot; onload=&quot;/, 'the photo-URL quotes are entity-encoded');
  assert.ok(html.includes('Earl L. &quot;Buddy&quot; Carter'), 'while the name itself still reads');
});

test('party chips map party names to a single letter', () => {
  assert.strictEqual(View.partyLetter('Democratic'), 'D');
  assert.strictEqual(View.partyLetter('Republican'), 'R');
  assert.strictEqual(View.partyLetter('Independent'), 'I');
  assert.strictEqual(View.partyLetter(null), 'I');
});

test('fedName reads both roster name shapes, fedChamber the latest term', () => {
  assert.strictEqual(View.fedName({ firstName: 'Ada', lastName: 'Lovelace' }), 'Ada Lovelace');
  assert.strictEqual(View.fedName({ name: 'Lovelace, Ada' }), 'Ada Lovelace');
  assert.strictEqual(View.fedChamber({ terms: { item: [{ chamber: 'House of Representatives' }, { chamber: 'Senate' }] } }), 'Senate');
  assert.strictEqual(View.fedChamber({}), null);
});

test('an empty section renders nothing at all', () => {
  assert.strictEqual(View.repSection('U.S. House', []), '');
  assert.match(View.repSection('U.S. House', ['<a></a>']), /fmr-office/);
});

// --- ZIP lookup (ga-zip-districts.json) -------------------------------------

const ZIPS = readJson('assets/data/ga-zip-districts.json').zips;

test('shareLabel: 5% and over is "about X%", under is "a small part"', () => {
  assert.equal(View.shareLabel(0.50406), 'about 50% of this ZIP');
  assert.equal(View.shareLabel(0.05), 'about 5% of this ZIP');
  assert.equal(View.shareLabel(0.0499), 'a small part of this ZIP');
  assert.equal(View.shareLabel(0.01212), 'a small part of this ZIP');
  assert.equal(View.shareLabel(1), 'all of this ZIP');
  assert.equal(View.shareLabel(undefined), null);
});

test('zipLoc lists every district in the file, sorted ascending, none dropped', () => {
  const loc = View.zipLoc('30303', ZIPS['30303']);
  assert.equal(loc.source, 'zip');
  assert.deepEqual(loc.stateHouse, [56, 58, 59], 'the 1% sliver is still listed');
  assert.deepEqual(loc.stateSenate, [36]);
  assert.deepEqual(loc.usHouse, [5]);
  assert.deepEqual(loc.counties, ['Fulton']);
  // Every ZIP with districts: nothing the file lists is lost in the expansion.
  for (const [zip, entry] of Object.entries(ZIPS)) {
    const l = View.zipLoc(zip, entry);
    if (!l) { assert.ok(!['stateHouse', 'stateSenate', 'usHouse'].some(k => (entry[k] || []).length), zip); continue; }
    for (const k of ['stateHouse', 'stateSenate', 'usHouse']) {
      assert.equal(l[k].length, (entry[k] || []).length, zip + ' ' + k);
      assert.deepEqual(l[k], l[k].slice().sort((a, b) => a - b), zip + ' ' + k + ' ascending');
    }
  }
});

test('zipLoc is null for a po-box ZIP, an unknown ZIP, or one with no districts', () => {
  assert.equal(View.zipLoc('30164', ZIPS['30164']), null);
  assert.equal(View.zipLoc('00000', undefined), null);
  assert.equal(View.zipLoc('30303', { kind: 'standard', counties: null, usHouse: null, stateSenate: null, stateHouse: null }), null);
  assert.equal(View.zipLoc('30303', { kind: 'other', usHouse: [{ district: 5, share: 1 }] }).usHouse[0], 5, "'other' is treated like standard");
});

test('renderReps for a ZIP: heading, honest caveat, share labels, every district', () => {
  const html = View.renderReps(View.zipLoc('30303', ZIPS['30303']), FED, GA, {});
  assert.match(html, /Districts touching ZIP 30303/);
  assert.match(html, /only a street address/);
  assert.match(html, /District 58 · about 50% of this ZIP/);
  assert.match(html, /District 59 · about 48% of this ZIP/);
  assert.match(html, /District 56 · a small part of this ZIP/);
  assert.ok(html.indexOf('District 56') < html.indexOf('District 58') && html.indexOf('District 58') < html.indexOf('District 59'));
  // Other sources keep their old output.
  assert.doesNotMatch(View.renderReps(View.countyLoc('Fulton', {}), FED, GA, {}), /Districts touching ZIP|of this ZIP/);
});
