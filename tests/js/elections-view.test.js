/*
 * Unit tests for ElectionsView (assets/scripts/elections-view.js), the candidates
 * page's choices about what to show, and for the calendar links into that page.
 *
 * Run: node --test tests/js/*.test.js
 *
 * Both exist because of the week before the December 1, 2026 runoff: the voter
 * access card landed on an empty tab, and the November 3 view said no races were
 * on file when every race it could list had been certified.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const view = () => loadBrowserModules('assets/scripts/elections-view.js').ElectionsView;

const TABS = ['executive', 'us-house', 'ga-house'];
const FILTERS = {
  'executive': r => r.chamber === 'Governor',
  'us-house':  r => r.chamber === 'U.S. House',
  'ga-house':  r => r.chamber === 'Georgia House of Representatives',
};
const race = (chamber, phase, date) =>
  ({ chamber, activePhase: phase, phases: { [phase]: { electionDate: date } } });

const HD151 = race('Georgia House of Representatives', 'runoff', '2026-12-01');
const GOV_NOV = race('Governor', 'general', '2026-11-03');
const CD13_AUG = race('U.S. House', 'runoff', '2026-08-25');

test('the page opens on the first tab that has a race in the phase', () => {
  assert.strictEqual(view().firstTabWithRaces([HD151], 'runoff', TABS, FILTERS), 'ga-house');
});

test('with several tabs holding races, tab-bar order decides', () => {
  const races = [HD151, race('U.S. House', 'runoff', '2026-12-01')];
  assert.strictEqual(view().firstTabWithRaces(races, 'runoff', TABS, FILTERS), 'us-house');
});

test('a phase with no listable race keeps the first tab', () => {
  assert.strictEqual(view().firstTabWithRaces([HD151], 'general', TABS, FILTERS), 'executive');
});

test('a tab whose races for this election are all decided reads as decided', () => {
  assert.strictEqual(
    view().isDecidedTab([], [GOV_NOV], 'general', '2026-11-03', FILTERS.executive), true);
});

test('a tab that still lists a race does not read as decided', () => {
  assert.strictEqual(
    view().isDecidedTab([GOV_NOV], [GOV_NOV], 'general', '2026-11-03', FILTERS.executive), false);
});

test('an earlier certified runoff does not mark a later runoff tab decided', () => {
  assert.strictEqual(
    view().isDecidedTab([HD151], [CD13_AUG], 'runoff', '2026-12-01', FILTERS['us-house']), false);
});

test('a tab that never had a race in this election is not decided', () => {
  assert.strictEqual(
    view().isDecidedTab([], [GOV_NOV], 'general', '2026-11-03', FILTERS['us-house']), false);
});

// A redirect_from stub drops the query string, so a link through one loses its
// phase and tab and lands the reader on the defaults.
test('calendar links go straight to the candidates page, not through its redirect', () => {
  const page = fs.readFileSync(path.join(REPO_ROOT, 'elections.html'), 'utf8');
  const permalink = page.match(/^permalink:\s*(\S+)/m)[1];
  const calendar = JSON.parse(fs.readFileSync(
    path.join(REPO_ROOT, 'assets/data/ga-election-calendar.json'), 'utf8'));
  const links = calendar.elections.map(e => e.racesUrl).filter(Boolean);
  assert.ok(links.length > 0);
  for (const link of links) assert.strictEqual(link.split('?')[0], permalink, link);
});
