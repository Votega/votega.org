/*
 * Unit tests for VoteGA.billsResolve (assets/scripts/ga-bills-resolve.js).
 *
 * Bill numbers restart each General Assembly, so an identifier names a bill only
 * within a biennium. These pin the three rules that keep a link from opening the
 * wrong bill: legislationId wins and never falls back to the number, anchors carry
 * the session, and a bare link is recognised as ambiguous.
 *
 * Run: node --test tests/js/*.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const R = loadBrowserModules('assets/scripts/ga-bills-resolve.js').VoteGA.billsResolve;

// The overlap the rollover creates: the same number in two bienniums.
const live = [
  { legislationId: 900, identifier: 'HB 943', session: '2027_28' },
  { legislationId: 901, identifier: 'HB 1', session: '2027_28' },
  { legislationId: 902, identifier: 'HB 1EX', session: '2027_ss' },
];
const frozen = [
  { legislationId: 100, identifier: 'HB 943', session: '2025_26' },
  { legislationId: 101, identifier: 'SR 9EX', session: '2026_ss' },
];

test('tag and biennium convert both ways', () => {
  assert.strictEqual(R.tagToBiennium('2025_26'), '2025-2026');
  assert.strictEqual(R.tagToBiennium('1999_00'), '1999-2000');
  assert.strictEqual(R.tagToBiennium('2025_27'), null);
  assert.strictEqual(R.toTag('2025-2026'), '2025_26');
  assert.strictEqual(R.toTag('2025_26'), '2025_26');
  assert.strictEqual(R.toTag('2025-2027'), null);
  assert.strictEqual(R.toTag(''), null);
});

test('a session id finds its frozen biennium, special sessions included', () => {
  const tags = ['2025_26'];
  assert.strictEqual(R.tagForSession('2025_26', tags), '2025_26');
  assert.strictEqual(R.tagForSession('2026_ss', tags), '2025_26');
  assert.strictEqual(R.tagForSession('2027_28', tags), null);
  assert.strictEqual(R.tagForSession('2027_ss', tags), null);
  assert.strictEqual(R.tagForSession('2026_ss', []), null);
  assert.strictEqual(R.tagForSession('nonsense', tags), null);
});

test('anchors carry the session, so a reused number cannot share one', () => {
  assert.strictEqual(R.anchorId(live[0]), 'bill-2027_28-HB943');
  assert.strictEqual(R.anchorId(frozen[0]), 'bill-2025_26-HB943');
  assert.notStrictEqual(R.anchorId(live[0]), R.anchorId(frozen[0]));
  assert.strictEqual(R.anchorId({ identifier: 'HB 5' }), 'bill-x-HB5');
  assert.strictEqual(R.legacyAnchorId('HB 943'), 'bill-HB943');
});

test('legislationId matches on the id alone', () => {
  assert.strictEqual(R.findBill(frozen, { legislationId: '100', identifier: 'HB 943' }), frozen[0]);
  assert.strictEqual(R.findBill(live, { legislationId: 900 }), live[0]);
});

test('a legislationId the file does not carry is a miss, never the same number', () => {
  // The 2025-26 HB 943 (id 100) asked of the 2027 file: HB 943 exists there, but it is another bill.
  assert.strictEqual(R.findBill(live, { legislationId: 100, identifier: 'HB 943' }), null);
});

test('a bare identifier resolves inside the file it is given', () => {
  assert.strictEqual(R.findBill(live, { identifier: 'hb943' }), live[0]);
  assert.strictEqual(R.findBill(frozen, { identifier: 'HB 943' }), frozen[0]);
  assert.strictEqual(R.findBill(live, { identifier: 'SR 9EX' }), null);
});

test('a named session narrows a bare identifier and never widens it', () => {
  const dup = [
    { legislationId: 1, identifier: 'HR 5', session: '2025_26' },
    { legislationId: 2, identifier: 'HR 5', session: '2026_ss' },
  ];
  assert.strictEqual(R.findBill(dup, { identifier: 'HR 5', session: '2026_ss' }), dup[1]);
  assert.strictEqual(R.findBill(dup, { identifier: 'HR 5' }), dup[0]);
  assert.strictEqual(R.findBill(dup, { identifier: 'HR 5', session: '2099_ss' }), null);
});

test('only an identifier with nothing else is a bare link', () => {
  assert.strictEqual(R.isBareLink({ identifier: 'HB 943' }), true);
  assert.strictEqual(R.isBareLink({ identifier: 'HB 943', legislationId: '100' }), false);
  assert.strictEqual(R.isBareLink({ identifier: 'HB 943', session: '2026_ss' }), false);
  assert.strictEqual(R.isBareLink({ identifier: 'HB 943', biennium: '2025-2026' }), false);
  assert.strictEqual(R.isBareLink({}), false);
});
