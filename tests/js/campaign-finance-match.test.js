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

/*
 * filingCommitteeNote(): say whose filing the figures come from when it is not
 * the candidate's own principal campaign committee.
 */

test('says nothing for a principal campaign committee', () => {
  assert.strictEqual(
    CF.filingCommitteeNote({ committeeId: 'C00543967', committeeDesignation: 'P',
                             committeeName: 'BUDDY CARTER FOR SENATE' }),
    ''
  );
});

test('says nothing for data generated before the designation was recorded', () => {
  assert.strictEqual(CF.filingCommitteeNote({ committeeId: 'C00543967' }), '');
  assert.strictEqual(CF.filingCommitteeNote(null), '');
});

test('names an unauthorized committee and warns the totals are not a campaign’s', () => {
  const note = CF.filingCommitteeNote({
    committeeId: 'C00901157',
    committeeName: 'BUILDING LASTING ALLIANCES FOR IMPACT AND RESULTS PAC',
    committeeDesignation: 'U',
  });
  assert.match(note, /BUILDING LASTING ALLIANCES FOR IMPACT AND RESULTS PAC/);
  assert.match(note, /not authorized by the candidate/);
  assert.match(note, /not a principal campaign committee/);
});

test('distinguishes an authorized committee from an unauthorized one', () => {
  const note = CF.filingCommitteeNote({ committeeName: 'X VICTORY FUND', committeeDesignation: 'A' });
  assert.match(note, /an authorized committee/);
  assert.ok(!/not authorized by the candidate/.test(note));
});

test('escapes the committee name', () => {
  const note = CF.filingCommitteeNote({ committeeName: 'A & B <PAC>', committeeDesignation: 'U' });
  assert.match(note, /A &amp; B &lt;PAC&gt;/);
  assert.ok(!/<PAC>/.test(note));
});

/*
 * noFilingHtml(): the empty state. "No filing found" plus a statewide search box
 * was what /us-congress/everton-blair-ga-13/ showed while FEC had his committee's
 * filings one click away.
 */

test('links the candidate’s own FEC page instead of a statewide search', () => {
  const html = CF.noFilingHtml({ fecUrl: 'https://www.fec.gov/data/candidate/H6GA13062/' }, 2026);
  assert.match(html, /candidate\/H6GA13062/);
  assert.match(html, /View their FEC candidate page/);
  assert.ok(!/Search FEC\.gov/.test(html));
});

test('falls back to a search only when there is no candidate id at all', () => {
  const html = CF.noFilingHtml(null, 2026);
  assert.match(html, /Search FEC\.gov/);
  assert.match(html, /election_year=2026/);
});

test('names the non-campaign committee FEC links, and links its filings', () => {
  const html = CF.noFilingHtml({
    fecUrl: 'https://www.fec.gov/data/candidate/H6GA13062/',
    relatedCommittee: {
      id: 'C00901157',
      name: 'BUILDING LASTING ALLIANCES FOR IMPACT AND RESULTS PAC',
      designation: 'U',
      fecUrl: 'https://www.fec.gov/data/committee/C00901157/',
    },
  }, 2026);
  assert.match(html, /No campaign committee is filing for this candidate/);
  assert.match(html, /BUILDING LASTING ALLIANCES FOR IMPACT AND RESULTS PAC/);
  assert.match(html, /which is not a campaign committee/);
  assert.match(html, /committee\/C00901157/);
  assert.match(html, /view its filings/);
  // and still offers the candidate page
  assert.match(html, /candidate\/H6GA13062/);
});

test('says plainly that no filing was found when no committee is known', () => {
  const html = CF.noFilingHtml({ fecUrl: 'https://www.fec.gov/data/candidate/H0GA01000/' }, 2026);
  assert.match(html, /No current FEC filing found/);
  assert.ok(!/not a campaign committee/.test(html));
});

test('escapes the related committee’s name and url', () => {
  const html = CF.noFilingHtml({
    relatedCommittee: { id: 'C1', name: 'A & B <PAC>', fecUrl: 'https://x/?a=1&b=2' },
  }, 2026);
  assert.match(html, /A &amp; B &lt;PAC&gt;/);
  assert.ok(!/<PAC>/.test(html));
});
