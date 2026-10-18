/*
 * Unit tests for assets/scripts/zip-districts.js -- the ZIP table pieces shared by
 * Find My Reps and the candidate finder. Uses the committed ga-zip-districts.json.
 *
 * Run: node --test tests/js/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const load = () => loadBrowserModules('assets/scripts/zip-districts.js').ZipDistricts;
const TABLE = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'assets/data/ga-zip-districts.json'), 'utf8'));

test('shareLabel: 5% and over is "about X%", under is "a small part", all is "all"', () => {
  const Z = load();
  assert.equal(Z.shareLabel(0.50406), 'about 50% of this ZIP');
  assert.equal(Z.shareLabel(0.05), 'about 5% of this ZIP');
  assert.equal(Z.shareLabel(0.0499), 'a small part of this ZIP');
  assert.equal(Z.shareLabel(1), 'all of this ZIP');
  assert.equal(Z.shareLabel(null), null);
});

test('lookup: ok lists every district sorted ascending, none dropped, for every ZIP', () => {
  const Z = load();
  const l = Z.lookup('30303', TABLE);
  assert.equal(l.status, 'ok');
  assert.deepEqual(l.stateHouse, [56, 58, 59]);
  assert.deepEqual(l.stateSenate, [36]);
  assert.deepEqual(l.usHouse, [5]);
  assert.deepEqual(l.counties, ['Fulton']);
  assert.equal(l.shares.stateHouse[58], 0.50406);
  for (const [zip, entry] of Object.entries(TABLE.zips)) {
    const r = Z.lookup(zip, TABLE);
    if (r.status !== 'ok') { assert.equal(r.status, 'no-districts', zip); continue; }
    for (const k of ['usHouse', 'stateSenate', 'stateHouse']) {
      assert.equal(r[k].length, (entry[k] || []).length, zip + ' ' + k);
      assert.deepEqual(r[k], r[k].slice().sort((a, b) => a - b), zip);
    }
  }
});

test('lookup: PO-box ZIP, unknown ZIP, empty entry and a missing table are answers, not throws', () => {
  const Z = load();
  assert.equal(Z.lookup('30164', TABLE).status, 'no-districts');
  assert.equal(Z.lookup('00000', TABLE).status, 'unknown');
  assert.equal(Z.lookup('30303', null).status, 'unknown');
  assert.equal(Z.lookup('30303', { zips: { 30303: { kind: 'standard', usHouse: null, stateSenate: null, stateHouse: null } } }).status, 'no-districts');
  assert.equal(Z.lookup('30303', { zips: { 30303: { kind: 'other', usHouse: [{ district: 5, share: 1 }] } } }).status, 'ok');
});

test('load: lazy, memoised, built on the given base path, and a failure is not remembered', async () => {
  const Z = load();
  const urls = [];
  let ok = false;
  const f = async (url) => { urls.push(url); return ok ? { ok: true, json: async () => TABLE } : { ok: false }; };
  assert.deepEqual(urls, [], 'nothing fetched at load');
  await assert.rejects(Z.load('/', f), /unavailable/);
  ok = true;
  const t = await Z.load('/', f);
  assert.equal(t, TABLE);
  await Z.load('/', f);
  assert.deepEqual(urls, ['/assets/data/ga-zip-districts.json', '/assets/data/ga-zip-districts.json'], 'retried after failure, then cached');
});
