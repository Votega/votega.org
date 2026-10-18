/*
 * Unit tests for the ZIP path through assets/scripts/sample-ballot.js: a ZIP is a SET of
 * districts, so district contests inside it are included and flagged ambiguous (like a
 * county), contests outside it are dropped, and statewide ones always stay.
 *
 * Run: node --test tests/js/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const win = loadBrowserModules('assets/scripts/zip-districts.js', 'assets/scripts/sample-ballot.js');
const SB = win.SampleBallot;
const Z = win.ZipDistricts;
const TABLE = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'assets/data/ga-zip-districts.json'), 'utf8'));

const DATE = '2026-11-03';
const cand = [{ name: 'A Candidate', party: 'Democrat' }];
const phase = { electionDate: DATE, ballots: { Democrat: cand } };
const race = (id, level, chamber, district) =>
  ({ id, level, chamber, district, cycle: 2026, activePhase: 'general', phases: { general: phase } });

const RACES = [
  race('senate', 'federal', 'U.S. Senate', null),
  race('gov', 'state-executive', 'Governor', null),
  race('us-1', 'federal', 'U.S. House', 1),
  race('us-5', 'federal', 'U.S. House', 5),
  race('us-9', 'federal', 'U.S. House', 9),
  race('sen-10', 'state', 'Georgia State Senate', 10),
  race('sen-55', 'state', 'Georgia State Senate', 55),
  race('house-3', 'state', 'Georgia House of Representatives', 3),
  race('house-90', 'state', 'Georgia House of Representatives', 90),
];

function ballotFor(loc) {
  return SB.assembleBallot(loc, { races: RACES, measures: [], calendar: [], electionDate: DATE });
}
const ids = b => b.groups.flatMap(g => g.contests.map(c => c.id)).sort();

const FOUND = (usHouse, stateSenate, stateHouse, counties = []) =>
  ({ status: 'ok', usHouse, stateSenate, stateHouse, counties });

test('locationFromZip: carries districts per chamber and no county or exact district', () => {
  const loc = SB.locationFromZip('30303', FOUND([5], [10], [90]));
  assert.equal(loc.source, 'zip');
  assert.equal(loc.zip, '30303');
  assert.equal(loc.county, null);
  assert.equal(loc.usHouse, null);
  assert.deepEqual(loc.zipDistricts, { usHouse: [5], stateSenate: [10], stateHouse: [90] });
});

test('a ZIP keeps statewide races and only the districts touching it', () => {
  const b = ballotFor(SB.locationFromZip('30303', FOUND([5], [10], [90])));
  assert.deepEqual(ids(b), ['gov', 'house-90', 'sen-10', 'senate', 'us-5']);
});

test('a ZIP spanning several districts lists every one of them', () => {
  const b = ballotFor(SB.locationFromZip('30000', FOUND([1, 5], [10, 55], [3, 90])));
  assert.deepEqual(ids(b), ['gov', 'house-3', 'house-90', 'sen-10', 'sen-55', 'senate', 'us-1', 'us-5']);
});

test('district contests from a ZIP are flagged ambiguous; statewide ones are not', () => {
  const b = ballotFor(SB.locationFromZip('30303', FOUND([5], [10], [90])));
  const by = Object.fromEntries(b.groups.flatMap(g => g.contests).map(c => [c.id, c.ambiguous]));
  assert.equal(by['us-5'], true);
  assert.equal(by['house-90'], true);
  assert.equal(by.senate, false);
  assert.equal(by.gov, false);
  assert.equal(b.ambiguous, true);
});

test('an exact address still wins: no ambiguity, one district per chamber', () => {
  const loc = { source: 'address', county: 'Fulton', usHouse: 5, stateSenate: 10, stateHouse: 90 };
  const b = ballotFor(loc);
  assert.deepEqual(ids(b), ['gov', 'house-90', 'sen-10', 'senate', 'us-5']);
  assert.equal(b.ambiguous, false);
});

test('a local-scope measure applies when ANY county the ZIP touches is one of its counties', () => {
  const m = { scope: 'local', counties: ['Cobb'] };
  assert.equal(SB.measureApplies(m, SB.locationFromZip('30000', FOUND([1], [1], [1], ['Fulton', 'Cobb']))), true);
  assert.equal(SB.measureApplies(m, SB.locationFromZip('30000', FOUND([1], [1], [1], ['Fulton']))), false);
  assert.equal(SB.measureApplies({}, SB.locationFromZip('30000', FOUND([1], [1], [1]))), true);   // statewide
});

test('end to end against the committed ZIP table: every real ZIP yields only districts it touches', () => {
  const zip = Object.keys(TABLE.zips).find(z => {
    const f = Z.lookup(z, TABLE);
    return f.status === 'ok' && f.usHouse.length > 1;       // a ZIP that spans congressional districts
  });
  assert.ok(zip, 'the table has at least one multi-district ZIP');
  const found = Z.lookup(zip, TABLE);
  const loc = SB.locationFromZip(zip, found);
  const races = found.usHouse.concat([999]).map(d => race(`us-${d}`, 'federal', 'U.S. House', d));
  const b = SB.assembleBallot(loc, { races, measures: [], calendar: [], electionDate: DATE });
  assert.deepEqual(ids(b), found.usHouse.map(d => `us-${d}`).sort());     // 999 is not touched, so absent
});
