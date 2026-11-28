/*
 * Unit tests for assets/scripts/format-date.js, the one date formatter (#224).
 *
 * Run: node --test tests/js/*.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const { formatDate } = loadBrowserModules('assets/scripts/format-date.js').VoteGA;

// Runs `fn` with the viewer in another timezone; Node re-reads TZ when it is assigned.
function inZone(zone, fn) {
  const before = process.env.TZ;
  process.env.TZ = zone;
  try {
    return fn();
  } finally {
    if (before === undefined) delete process.env.TZ; else process.env.TZ = before;
  }
}

test('long form is the default and short form is on request', () => {
  assert.strictEqual(formatDate('2026-10-20'), 'October 20, 2026');
  assert.strictEqual(formatDate('2026-10-20', { style: 'long' }), 'October 20, 2026');
  assert.strictEqual(formatDate('2026-10-20', { style: 'short' }), 'Oct 20, 2026');
});

test('weekday and year options follow the style', () => {
  assert.strictEqual(formatDate('2026-11-03', { weekday: true }), 'Tuesday, November 3, 2026');
  assert.strictEqual(formatDate('2026-10-20', { style: 'short', year: false }), 'Oct 20');
  assert.strictEqual(formatDate('2026-11-03', { year: false }), 'November 3');
});

test('an invalid date returns an empty string instead of rolling over', () => {
  for (const bad of ['2026-13-45', '2026-02-30', '2026-00-10', '2026-10-00', '2027-02-29',
    '2026-02-30T12:00:00Z', '2026-10-20T99:99:00', '2026-10-20 junk', '2026-10', 'not-a-date',
    '10/20/2026', new Date('nope')]) {
    assert.strictEqual(formatDate(bad), '', String(bad));
  }
  assert.strictEqual(formatDate('2028-02-29'), 'February 29, 2028');
});

test('an absent value returns an empty string', () => {
  for (const none of [null, undefined, '']) assert.strictEqual(formatDate(none), '');
});

test('a bare date keeps its calendar day in every timezone', () => {
  for (const zone of ['America/New_York', 'Pacific/Honolulu', 'UTC', 'Pacific/Kiritimati']) {
    inZone(zone, () => {
      assert.strictEqual(formatDate('2026-01-01'), 'January 1, 2026', zone);
      assert.strictEqual(formatDate('2026-11-03', { style: 'short' }), 'Nov 3, 2026', zone);
    });
  }
});

test('a timestamp is shown on the viewer’s local day', () => {
  inZone('America/New_York', () => {
    assert.strictEqual(formatDate('2026-10-21T02:30:00Z'), 'October 20, 2026');
    assert.strictEqual(formatDate('2026-10-21T02:30:00.123456+00:00'), 'October 20, 2026');
    assert.strictEqual(formatDate('2026-10-21T00:00:00'), 'October 21, 2026');
    assert.strictEqual(formatDate(new Date('2026-10-21T02:30:00Z')), 'October 20, 2026');
  });
});

test('a non-US default locale does not leak into the output', () => {
  // Stand in for a British browser: any call that leaves the locale open gets en-GB.
  const real = Date.prototype.toLocaleDateString;
  Date.prototype.toLocaleDateString = function (locales, options) {
    const open = locales === undefined || (Array.isArray(locales) && !locales.length);
    return real.call(this, open ? 'en-GB' : locales, options);
  };
  try {
    assert.strictEqual(new Date(2026, 9, 20).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }),
      '20 Oct 2026', 'the stand-in works');
    assert.strictEqual(formatDate('2026-10-20', { style: 'short' }), 'Oct 20, 2026');
    assert.strictEqual(formatDate('2026-10-20'), 'October 20, 2026');
  } finally {
    Date.prototype.toLocaleDateString = real;
  }
});

// A stale cached page can run these without format-date.js; blank beats a TypeError.
test('shared modules do not throw when the formatter is not loaded', () => {
  const win = loadBrowserModules(
    'assets/scripts/html-escape.js',
    'assets/scripts/votega-votes-table.js',
    'assets/scripts/campaign-finance.js',
    'assets/scripts/departure-label.js'
  );
  assert.strictEqual(win.VotegaVotesTable.fmtDate('2026-04-03'), '—');
  assert.strictEqual(win.CampaignFinance.provenanceLine('the FEC', '2026-04-03'), '');
  assert.strictEqual(win.VotegaDeparture.longDate('2027-01-11'), '2027-01-11');
});

// The point of #224: pages stop growing their own date code.
test('no page or script formats a date on its own or leaves the locale open', () => {
  const files = [];
  const walk = (dir, ext, deep) => {
    for (const e of fs.readdirSync(path.join(REPO_ROOT, dir), { withFileTypes: true })) {
      const rel = path.posix.join(dir, e.name);
      if (e.isDirectory()) { if (deep) walk(rel, ext, deep); } else if (ext.test(e.name)) files.push(rel);
    }
  };
  walk('assets/scripts', /\.js$/, true);
  walk('_includes', /\.html$/, true);
  walk('_layouts', /\.html$/, true);
  walk('.', /\.html$/, false);

  const offenders = [];
  for (const rel of files) {
    if (rel === 'assets/scripts/format-date.js') continue;
    fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8').split('\n').forEach((line, i) => {
      const openLocale = /toLocale(Date|Time)String\(\s*(\)|\[\s*\]|undefined)/.test(line);
      // A weekday name on its own ("Monday") is the one relative label kept in place.
      const ownDate = /toLocaleDateString\(/.test(line) && !/'en-US', \{ weekday: 'long' \}/.test(line);
      if (openLocale || ownDate) offenders.push(`${rel}:${i + 1}`);
    });
  }
  assert.deepStrictEqual(offenders, []);
});
