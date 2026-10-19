/*
 * Unit tests for TopicIndex.groupIsStrong() (assets/scripts/topic-index.js).
 *
 * Run: node --test tests/js/*.test.js
 *
 * This one function decides what a resident sees FIRST on /local/topics/alpr/.
 * The keyword lexicon behind that page is deliberately recall-favoured — false
 * positives are tolerated so a real plate-reader contract is never missed — and
 * the page pays for that choice by ranking rather than hiding: a jurisdiction with
 * a named vendor or a spelled-out capability phrase is shown as a confirmed
 * mention, while a keyword-only one rides in a collapsed "possible mentions"
 * section, fully sourced.
 *
 * Getting the predicate wrong is quiet and expensive in both directions. Read as
 * strong when it is weak, and a facility-camera budget line is presented to the
 * public with the same weight as a Flock contract. Read as weak when it is strong,
 * and a real surveillance contract is buried in a collapsed section nobody opens.
 * Neither failure shows up as an error, so they are pinned here.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const win = loadBrowserModules(
  'assets/scripts/html-escape.js',
  'assets/scripts/topic-index.js'
);
const { groupIsStrong } = win.TopicIndex;

// Shape mirrors groupRows(): meetings keyed by "<date>|<body>", each carrying the
// confidence rolled up from its mentions ('high' wins within a meeting).
function group(confidences) {
  const meetings = {};
  confidences.forEach(function (c, i) {
    meetings['2026-0' + (i + 1) + '-01|Board of Commissioners'] = { confidence: c };
  });
  return { placeId: 'p', meetings: meetings, count: confidences.length };
}

test('a single vendor-named meeting makes the jurisdiction confirmed', () => {
  assert.strictEqual(groupIsStrong(group(['high'])), true);
});

test('keyword-only meetings stay in the possible tier', () => {
  assert.strictEqual(groupIsStrong(group(['medium'])), false);
  assert.strictEqual(groupIsStrong(group(['medium', 'medium', 'medium'])), false);
});

test('one high meeting among many weak ones confirms the jurisdiction', () => {
  // The case that matters most: a county with one real Flock contract and a pile
  // of incidental keyword hits must NOT be filed under "possible".
  assert.strictEqual(groupIsStrong(group(['medium', 'medium', 'high', 'medium'])), true);
});

test('confidence is compared exactly, not truthily', () => {
  // A missing, empty or unexpected value is NOT high. If a future generator emitted
  // 'low' or '', a truthy test would promote every such mention to confirmed.
  assert.strictEqual(groupIsStrong(group([''])), false);
  assert.strictEqual(groupIsStrong(group(['low'])), false);
  assert.strictEqual(groupIsStrong(group([undefined])), false);
  assert.strictEqual(groupIsStrong(group(['High'])), false);   // case-sensitive
  assert.strictEqual(groupIsStrong(group(['highest'])), false);
});

test('an empty or malformed group is weak, never a crash', () => {
  // draw() runs on filtered data, so an empty group is reachable; a throw here
  // would blank the whole list rather than degrade one row.
  assert.strictEqual(groupIsStrong(group([])), false);
  assert.strictEqual(groupIsStrong({}), false);
  assert.strictEqual(groupIsStrong({ meetings: null }), false);
  assert.strictEqual(groupIsStrong(undefined), false);
  assert.strictEqual(groupIsStrong(null), false);
});
