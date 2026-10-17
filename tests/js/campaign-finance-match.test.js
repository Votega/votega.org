/*
 * Unit tests for CampaignFinance.narrowFecMatches()
 * (assets/scripts/campaign-finance.js).
 *
 * Run: node --test tests/js/
 *
 * The case these pin: a sitting House member running for Senate holds two FEC
 * candidate ids in one cycle, both drawing on a single principal committee. Both
 * therefore carry the same totals and the same coverage date, so nothing in the
 * totals can separate them — and taking the first of the array sent Buddy
 * Carter's page to his House filing, which FEC.gov renders as "nothing filed"
 * for 2026 because every document of the cycle is filed under the Senate
 * candidacy. lastFileDate is what tells them apart. Mirrors
 * scripts/test_fec_preferred_filing.py on the Python side.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const win = loadBrowserModules(
  'assets/scripts/html-escape.js',
  'assets/scripts/campaign-finance.js'
);
const CF = win.CampaignFinance;

// One committee, one set of totals, two candidate registrations.
function dualFiler(overrides = {}) {
  const shared = {
    name: 'CARTER, EARL LEROY',
    totalRaised: 7300242.83,
    coverageEndDate: '2026-06-30T00:00:00',
    committeeId: 'C00543967',
  };
  return {
    candidates: {
      H4GA01039: { ...shared, office: 'H', lastFileDate: '2024-11-18', ...overrides.H },
      S6GA00374: { ...shared, office: 'S', lastFileDate: '2025-05-09', ...overrides.S },
    },
  };
}

test('picks the more recently filed of two candidacies sharing a committee', () => {
  const fec = dualFiler();
  assert.deepStrictEqual(
    CF.narrowFecMatches(fec, ['H4GA01039', 'S6GA00374'], 'Buddy Carter'),
    { id: 'S6GA00374', status: 'ok' }
  );
});

test('the pick does not depend on the order the ids arrive in', () => {
  const fec = dualFiler();
  assert.strictEqual(
    CF.narrowFecMatches(fec, ['S6GA00374', 'H4GA01039'], 'Buddy Carter').id,
    'S6GA00374'
  );
});

test('a filing with no date never outranks one that has a date', () => {
  const fec = dualFiler({ H: { lastFileDate: undefined } });
  assert.strictEqual(
    CF.narrowFecMatches(fec, ['H4GA01039', 'S6GA00374'], 'Buddy Carter').id,
    'S6GA00374'
  );
});

test('falls back to array order when no filing carries a date', () => {
  // ga-fec-data.json predates lastFileDate until the next weekly regeneration,
  // so the undated path has to keep behaving exactly as it did before.
  const fec = dualFiler({ H: { lastFileDate: undefined }, S: { lastFileDate: undefined } });
  assert.strictEqual(
    CF.narrowFecMatches(fec, ['H4GA01039', 'S6GA00374'], 'Buddy Carter').id,
    'H4GA01039'
  );
});

test('two different people sharing a surname stay ambiguous, not newest-wins', () => {
  // Separate committees, so the shared-committee branch must not fire at all —
  // guessing here is what once put another man's money on a candidate page.
  const fec = {
    candidates: {
      H8GA01111: { name: 'BROWN, JAMES M', office: 'H', committeeId: 'C00000001',
                   totalRaised: 10, coverageEndDate: '2026-06-30T00:00:00',
                   lastFileDate: '2026-01-01' },
      H8GA01222: { name: 'BROWN, TIMOTHY BEAU', office: 'H', committeeId: 'C00000002',
                   totalRaised: 20, coverageEndDate: '2026-06-30T00:00:00',
                   lastFileDate: '2026-02-01' },
    },
  };
  assert.deepStrictEqual(
    CF.narrowFecMatches(fec, ['H8GA01111', 'H8GA01222'], 'Chris Brown'),
    { id: null, status: 'ambiguous' }
  );
});
