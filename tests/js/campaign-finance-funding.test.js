/*
 * Unit tests for CampaignFinance.fundingBreakdownHtml()
 * (assets/scripts/campaign-finance.js).
 *
 * Run: node --test tests/js/
 *
 * This panel makes a claim the rest of the finance section does not: that the
 * rows account for every dollar raised. These cover the ways that claim can go
 * wrong on real FEC data — a receipt type with no component of its own, an
 * amended filing whose components overrun gross receipts, a source too small to
 * round to a whole percent — plus the absent-data paths, since `funding` is a
 * new key that every row of ga-fec-data.json lacks until the next regeneration.
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

// Shares as the table prints them, keyed by row label.
function sharesByLabel(html) {
  const out = {};
  const rowRe = /<tr><td><span class="funding-swatch"[^>]*><\/span>([^<]*)<\/td><td>([^<]*)<\/td><td>([^<]*)<\/td><\/tr>/g;
  for (const m of html.matchAll(rowRe)) out[m[1]] = { amount: m[2], share: m[3] };
  return out;
}

function barWidths(html) {
  return [...html.matchAll(/width:([\d.]+)%/g)].map(m => Number(m[1]));
}

test('renders nothing when there is no breakdown to show', () => {
  // Every candidate in ga-fec-data.json is in this state until the generator is
  // re-run, so the empty string is the common case, not an error path.
  assert.equal(CF.fundingBreakdownHtml({ totalRaised: 100 }), '');
  assert.equal(CF.fundingBreakdownHtml({ funding: { pac: 500 } }), '');
  assert.equal(CF.fundingBreakdownHtml({ totalRaised: 0, funding: { pac: 500 } }), '');
  assert.equal(CF.fundingBreakdownHtml({ totalRaised: 100, funding: { pac: 0 } }), '');
  assert.equal(CF.fundingBreakdownHtml({}), '');
  assert.equal(CF.fundingBreakdownHtml(undefined), '');
  assert.equal(CF.fundingBreakdownHtml(null), '');
});

test('orders sources largest first and shares them against receipts', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 1000000,
    funding: { individualItemized: 500000, pac: 300000, individualUnitemized: 200000 },
  });
  const labels = [...html.matchAll(/<\/span>([^<]*)<\/td>/g)].map(m => m[1]);
  assert.deepEqual(labels, [
    'Individuals ($200 and up)',
    'PACs and other committees',
    'Small donors (under $200)',
  ]);
  const shares = sharesByLabel(html);
  assert.equal(shares['PACs and other committees'].share, '30%');
  assert.equal(shares['Small donors (under $200)'].share, '20%');
});

test('sums the candidate’s own contributions and loans into one row', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 100000,
    funding: { candidateSelf: 25000, candidateLoans: 75000 },
  });
  const shares = sharesByLabel(html);
  assert.equal(shares['The candidate (contributions and loans)'].share, '100%');
  assert.equal(Object.keys(shares).length, 1);
});

test('puts receipts the named components miss into Other, so rows total 100%', () => {
  // Fuller's 2026 filing in miniature: receipts exceed the sum of the component
  // fields, and the gap is what the old panel left unexplained.
  const html = CF.fundingBreakdownHtml({
    totalRaised: 1000000,
    funding: { individualItemized: 700000, pac: 200000 },
  });
  const shares = sharesByLabel(html);
  assert.equal(shares['Other receipts'].share, '10%');
  const total = barWidths(html).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(total - 100) < 0.01, `bar should fill exactly: got ${total}%`);
});

test('ignores a rounding-crumb remainder rather than printing a 0% row', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 1000000,
    funding: { individualItemized: 999100, pac: 500 },
  });
  assert.ok(!/Other receipts/.test(html), 'a $400 gap is noise, not a funding source');
});

test('caps shares at 100% when components overrun gross receipts', () => {
  // An amended filing can leave the components summing past receipts. Dividing
  // by the smaller figure would print a 120% share and a bar segment wider than
  // the bar itself.
  const html = CF.fundingBreakdownHtml({ totalRaised: 1000, funding: { pac: 1200 } });
  assert.deepEqual(barWidths(html), [100]);
  assert.equal(sharesByLabel(html)['PACs and other committees'].share, '100%');
});

test('labels a source too small to round as <1% rather than 0%', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 1000000,
    funding: { individualItemized: 996000, pac: 3000, party: 1000 },
  });
  assert.equal(sharesByLabel(html)['Party committees'].share, '&lt;1%');
  // A sub-1% segment still has to be visible and hoverable in the bar.
  assert.ok(/class="funding-bar-seg"[^>]*background:#a16207/.test(html));
});

test('negative components never become a funding source', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 100000,
    funding: { individualItemized: 100000, pac: -5000 },
  });
  assert.ok(!/PACs and other committees/.test(html));
  assert.ok(barWidths(html).every(w => w >= 0));
});

test('states the denominator and the unitemized caveat', () => {
  const html = CF.fundingBreakdownHtml({
    totalRaised: 1846892.29,
    funding: { individualItemized: 900000, pac: 600000 },
  });
  // Matches the Total Raised card above it, which uses the same formatter.
  assert.ok(html.includes('Share of the ' + CF.fmtMoney(1846892.29) + ' raised this cycle'));
  assert.ok(/\$200 or less in total are not itemized/.test(html));
});
