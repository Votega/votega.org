/*
 * Unit tests for the "older than usual" rule (assets/scripts/freshness.js) and the
 * local-meetings helper that feeds the local-government stamp.
 *
 * Run: node --test tests/js/*.test.js
 *
 * The rule is the thing most likely to cry wolf, so these pin the cases that must NOT
 * flag as hard as the ones that must: a quiet-but-checked dataset, a never-flag dataset,
 * an unknown key, an unparseable date.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules } = require('./load-browser-module');

const SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'assets/scripts/freshness.js'), 'utf8');

function withConfig(cfg) {
  // freshness.js reads window.VOTEGA_FRESHNESS at call time, so set it on the stub.
  const win = {};
  win.window = win;
  if (cfg) win.VOTEGA_FRESHNESS = cfg;
  new Function('window', SRC)(win);
  return win.VotegaFreshness;
}

const CFG = {
  windows: {
    'ga-bills': { window_days: 10 },
    'ga-members': { window_days: 3 },
    'supreme-court': { never: true },
  },
  checked: {},
};
const NOW = new Date(2026, 9, 21, 12);   // 21 Oct 2026, local

test('a stamp inside its window is not flagged', () => {
  const F = withConfig(CFG);
  const s = F.status('ga-bills', '2026-10-15', NOW);
  assert.strictEqual(s.stale, false);
  assert.strictEqual(s.ageDays, 6);
  assert.strictEqual(F.staleBadge('ga-bills', '2026-10-15', NOW), '');
});

test('a stamp past its window is flagged with an icon and the label', () => {
  const F = withConfig(CFG);
  const s = F.status('ga-bills', '2026-10-01', NOW);
  assert.strictEqual(s.stale, true);
  const html = F.staleBadge('ga-bills', '2026-10-01', NOW);
  assert.ok(html.includes('older than usual'));
  assert.ok(html.includes('fa-clock-rotate-left'), 'amber is never colour alone');
  assert.ok(html.includes('stale-flag'));
  assert.ok(html.includes('Normally refreshed within 10 days; this is 20 days old.'));
});

test('the window boundary: exactly window_days old is fine, one day more is stale', () => {
  const F = withConfig(CFG);
  assert.strictEqual(F.status('ga-bills', '2026-10-11', NOW).stale, false);   // 10 days
  assert.strictEqual(F.status('ga-bills', '2026-10-10', NOW).stale, true);    // 11 days
});

test('a recent check keeps a quiet dataset from reading as stale', () => {
  // The stamp only moves when content changes; the workflow records the day it looked.
  const F = withConfig({ ...CFG, checked: { 'ga-bills': '2026-10-20' } });
  const s = F.status('ga-bills', '2026-08-01', NOW);
  assert.strictEqual(s.stale, false);
  assert.strictEqual(s.ageDays, 1);
  assert.ok(F.checkedNote('ga-bills', '2026-08-01').includes('checked October 20, 2026'));
});

test('an old check does not rescue an old stamp, and an older check never overrides a newer stamp', () => {
  const F = withConfig({ ...CFG, checked: { 'ga-bills': '2026-09-01' } });
  assert.strictEqual(F.status('ga-bills', '2026-09-02', NOW).stale, true);
  // check older than the stamp: measure from the stamp, and say nothing about the check
  const G = withConfig({ ...CFG, checked: { 'ga-bills': '2026-10-01' } });
  assert.strictEqual(G.status('ga-bills', '2026-10-19', NOW).ageDays, 2);
  assert.strictEqual(G.checkedNote('ga-bills', '2026-10-19'), '');
});

test('a check the same day as the stamp adds no "checked" note', () => {
  const F = withConfig({ ...CFG, checked: { 'ga-bills': '2026-10-19' } });
  assert.strictEqual(F.checkedNote('ga-bills', '2026-10-19'), '');
});

test('never-flag datasets are never flagged, however old', () => {
  const F = withConfig(CFG);
  const s = F.status('supreme-court', '2020-01-01', NOW);
  assert.strictEqual(s.tracked, false);
  assert.strictEqual(s.stale, false);
  assert.strictEqual(F.suffix('supreme-court', '2020-01-01', NOW), '');
});

test('an unknown dataset key is never flagged', () => {
  const F = withConfig(CFG);
  assert.strictEqual(F.suffix('no-such-dataset', '2001-01-01', NOW), '');
});

test('a missing or unparseable stamp says nothing rather than flagging', () => {
  const F = withConfig(CFG);
  assert.strictEqual(F.status('ga-bills', null, NOW).stale, false);
  assert.strictEqual(F.status('ga-bills', 'not a date', NOW).stale, false);
  assert.strictEqual(F.suffix('ga-bills', undefined, NOW), '');
});

test('missing config degrades to no flags instead of throwing', () => {
  const F = withConfig(null);
  assert.strictEqual(F.suffix('ga-bills', '2000-01-01'), '');
});

test('date-only stamps are local calendar dates, not shifted a day', () => {
  const F = withConfig(CFG);
  // 2026-10-18 at local midnight vs NOW 21 Oct noon: 3 days, not 2 or 4.
  assert.strictEqual(F.status('ga-members', '2026-10-18', NOW).ageDays, 3);
  assert.strictEqual(F.status('ga-members', '2026-10-18', NOW).stale, false);
  assert.strictEqual(F.status('ga-members', '2026-10-17', NOW).stale, true);
});

test('latestMeetingDate ignores scheduled meetings and picks the newest past one', () => {
  const win = loadBrowserModules('assets/scripts/local-meetings.js');
  const LM = win.LocalMeetings;
  const d = new Date();
  const iso = (offset) => {
    const x = new Date(d.getFullYear(), d.getMonth(), d.getDate() + offset);
    return x.getFullYear() + '-' + ('0' + (x.getMonth() + 1)).slice(-2) + '-' + ('0' + x.getDate()).slice(-2);
  };
  assert.strictEqual(LM.latestMeetingDate([
    { date: iso(10) }, { date: iso(-3) }, { date: iso(-20) }, { date: null }, {},
  ]), iso(-3));
  assert.strictEqual(LM.latestMeetingDate([{ date: iso(5) }]), null);
  assert.strictEqual(LM.latestMeetingDate([]), null);
  assert.strictEqual(LM.latestMeetingDate(undefined), null);
});
