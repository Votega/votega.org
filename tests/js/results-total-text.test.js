/*
 * Unit tests for ResultsContest.totalText() (assets/scripts/results-contest.js),
 * the line under a contest's title.
 *
 * Run: node --test tests/js/*.test.js
 *
 * Search Console read the December 1 runoff page, staged before any vote, as a
 * soft 404: "No results reported" on a page that had nothing to report yet.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const { ResultsContest } = loadBrowserModules('assets/scripts/results-contest.js');
const { totalText } = ResultsContest;
const UPCOMING = { status: 'upcoming', electionDay: 'December 1, 2026' };

test('before the election a contest says when its votes are reported', () => {
  assert.strictEqual(totalText({ totalVotes: 0 }, 'no-results', UPCOMING),
    'Votes are reported after polls close at 7:00 PM ET on December 1, 2026');
});

test('once counting has started, an uncounted contest still says so', () => {
  assert.strictEqual(
    totalText({ totalVotes: 0 }, 'no-results', { status: 'unofficial', electionDay: 'December 1, 2026' }),
    'No results reported');
});

test('with no election date, an upcoming contest does not invent one', () => {
  assert.strictEqual(totalText({ totalVotes: 0 }, 'no-results', { status: 'upcoming' }),
    'No results reported');
});

test('a counted contest shows its total with separators', () => {
  assert.strictEqual(totalText({ totalVotes: 19637 }, 'winner', UPCOMING), 'Total votes: 19,637');
});
