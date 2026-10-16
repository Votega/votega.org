/*
 * Unit tests for assets/scripts/address-lookup.js.
 *
 * Run: node --test tests/js/
 *
 * These cover the behaviours that drifted while four pages each kept their own
 * copy of this logic: refusing a bare ZIP without spending a request, holding a
 * busy latch, surfacing the geocoder's own message, persisting only derived
 * districts, and reporting an outcome enum that never carries the address.
 *
 * The module takes its elements as configuration rather than reaching for
 * `document`, so everything here runs against plain objects -- no DOM, no
 * dependency tree, same stance as the rest of tests/js.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const win = loadBrowserModules('assets/scripts/address-lookup.js');
const { classifyAddress, createAddressLookup, messages } = win.AddressLookup;

// A page's elements, reduced to what the module actually touches.
function harness(overrides = {}) {
  const calls = { status: [], tracked: [], saved: [], resolved: [], rejected: [], refused: [] };
  const input = { value: '' };
  const button = { disabled: false };
  const lookup = createAddressLookup(Object.assign({
    input,
    button,
    subject: 'your district',
    fallbackPhrase: 'pick your county below',
    eventName: 'reps_lookup',
    eventParams: { page: 'federal_reps' },
    setStatus: (m, isError) => calls.status.push([m, !!isError]),
    track: (name, params) => calls.tracked.push([name, params]),
    save: (loc) => calls.saved.push(loc),
    onResolve: (loc) => { calls.resolved.push(loc); },
    onReject: (err) => calls.rejected.push(err && err.message),
    onRefuse: (why) => calls.refused.push(why),
    geocode: async () => ({ source: 'address', county: 'Fulton', usHouse: 5 }),
  }, overrides));
  return { lookup, input, button, calls };
}

const lastStatus = calls => calls.status[calls.status.length - 1];
const lastEvent = calls => calls.tracked[calls.tracked.length - 1];

test('classifyAddress sorts input before any request is considered', () => {
  assert.deepEqual(classifyAddress(''), { kind: 'empty', value: '' });
  assert.deepEqual(classifyAddress('   '), { kind: 'empty', value: '' });
  assert.deepEqual(classifyAddress(null), { kind: 'empty', value: '' });
  assert.equal(classifyAddress('30303').kind, 'zip');
  assert.equal(classifyAddress('30303-1234').kind, 'zip');
  assert.equal(classifyAddress('  30303  ').kind, 'zip', 'surrounding space must not hide a ZIP');
  assert.equal(classifyAddress('123 Peachtree St NE, Atlanta, GA 30303').kind, 'ok');
  // A ZIP inside a real address is not a bare ZIP.
  assert.equal(classifyAddress('30303 Peachtree St').kind, 'ok');
  assert.equal(classifyAddress('123 Peachtree St NE').value, '123 Peachtree St NE');
  assert.equal(classifyAddress('  123 Main St  ').value, '123 Main St', 'value is trimmed');
});

test('a bare ZIP is refused without calling the geocoder', async () => {
  let called = 0;
  const { lookup, input, calls } = harness({ geocode: async () => { called++; return {}; } });
  input.value = '30303';

  assert.equal(await lookup.run(), 'zip_only');
  assert.equal(called, 0, 'the point of the guard is to not spend a request');
  assert.match(lastStatus(calls)[0], /ZIP code alone/);
  assert.equal(lastStatus(calls)[1], true, 'shown as an error');
  assert.deepEqual(lastEvent(calls), ['reps_lookup', { method: 'address', outcome: 'zip_only', page: 'federal_reps' }]);
  assert.deepEqual(calls.refused, ['zip_only'], 'the page is told, so it can clear a stale result');
  assert.equal(calls.resolved.length, 0);
});

test('ZIP+4 is refused too', async () => {
  let called = 0;
  const { lookup, input } = harness({ geocode: async () => { called++; return {}; } });
  input.value = '30303-1234';
  assert.equal(await lookup.run(), 'zip_only');
  assert.equal(called, 0);
});

test('empty input asks for an address and spends nothing', async () => {
  let called = 0;
  const { lookup, input, calls } = harness({ geocode: async () => { called++; return {}; } });
  input.value = '   ';
  assert.equal(await lookup.run(), 'empty');
  assert.equal(called, 0);
  assert.equal(calls.tracked.length, 0, 'an empty box is not an outcome worth recording');
  assert.equal(lastStatus(calls)[1], true);
});

test('a resolved address reaches the page, is saved, and reports success', async () => {
  const loc = { source: 'address', county: 'Fulton', usHouse: 5 };
  const { lookup, input, calls } = harness({ geocode: async () => loc });
  input.value = '123 Peachtree St NE, Atlanta, GA 30303';

  assert.equal(await lookup.run(), 'success');
  assert.deepEqual(calls.resolved, [loc]);
  assert.deepEqual(calls.saved, [loc], 'carried over for other pages this visit');
  assert.deepEqual(lastEvent(calls), ['reps_lookup', { method: 'address', outcome: 'success', page: 'federal_reps' }]);
});

test('no tracked parameter can carry what the voter typed', async () => {
  const { lookup, input, calls } = harness();
  input.value = '123 Peachtree St NE, Atlanta, GA 30303';
  await lookup.run();
  input.value = '30303';
  await lookup.run();
  const serialized = JSON.stringify(calls.tracked).toLowerCase();
  assert.ok(!serialized.includes('peachtree'), 'the address must never reach analytics');
  assert.ok(!serialized.includes('30303'), 'nor a ZIP the voter typed');
});

test('the page can override the outcome when a location has no district', async () => {
  const { lookup, input, calls } = harness({
    geocode: async () => ({ source: 'address', county: 'Fulton', usHouse: null }),
    onResolve: () => 'no_district',
  });
  input.value = '123 Peachtree St NE';
  assert.equal(await lookup.run(), 'no_district');
  assert.equal(lastEvent(calls)[1].outcome, 'no_district');
});

test("a geocoder failure surfaces the geocoder's own message", async () => {
  const { lookup, input, calls } = harness({
    geocode: async () => { throw new Error('That address does not appear to be in Georgia.'); },
  });
  input.value = '1600 Pennsylvania Ave';

  assert.equal(await lookup.run(), 'error');
  assert.equal(lastStatus(calls)[0], 'That address does not appear to be in Georgia.');
  assert.equal(lastStatus(calls)[1], true);
  assert.deepEqual(calls.rejected, ['That address does not appear to be in Georgia.']);
  assert.equal(lastEvent(calls)[1].outcome, 'error');
  assert.equal(calls.saved.length, 0, 'nothing to carry over from a failure');
});

test('a failure with no message falls back to page-aware copy', async () => {
  const { lookup, input, calls } = harness({ geocode: async () => { throw new Error(''); } });
  input.value = '123 Peachtree St NE';
  await lookup.run();
  assert.match(lastStatus(calls)[0], /could not be looked up.*pick your county below/);
});

test('the button is released after success and after failure', async () => {
  const ok = harness();
  ok.input.value = '123 Peachtree St NE';
  await ok.lookup.run();
  assert.equal(ok.button.disabled, false);
  assert.equal(ok.lookup.isBusy(), false);

  const bad = harness({ geocode: async () => { throw new Error('nope'); } });
  bad.input.value = '123 Peachtree St NE';
  await bad.lookup.run();
  assert.equal(bad.button.disabled, false, 'a failed lookup must not strand the button');
});

test('the busy latch refuses a second lookup already in flight', async () => {
  let calls = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const h = harness({ geocode: async () => { calls++; await gate; return { county: 'Fulton', usHouse: 5 }; } });
  h.input.value = '123 Peachtree St NE';

  const first = h.lookup.run();
  assert.equal(h.lookup.isBusy(), true);
  assert.equal(await h.lookup.run(), 'busy', 'a double-click is not a second question');
  release();
  await first;
  assert.equal(calls, 1);
  assert.equal(h.lookup.isBusy(), false, 'and the latch clears for the next real lookup');
});

test('setBusy lets a page with two buttons share one latch', async () => {
  const seen = [];
  const h = harness({ setBusy: v => seen.push(v) });
  h.input.value = '123 Peachtree St NE';
  await h.lookup.run();
  assert.deepEqual(seen, [true, false]);
  assert.equal(h.button.disabled, false, 'the default button handling steps aside');
});

test('an unavailable geocoder is reported, not thrown', async () => {
  const { lookup, input, calls } = harness({ geocode: null });
  input.value = '123 Peachtree St NE';
  assert.equal(await lookup.run(), 'unavailable');
  assert.match(lastStatus(calls)[0], /unavailable right now/);
  assert.deepEqual(calls.refused, ['unavailable']);
});

test('save can be switched off for a page that persists nothing', async () => {
  const { lookup, input, calls } = harness({ save: false });
  input.value = '123 Peachtree St NE';
  await lookup.run();
  assert.equal(calls.saved.length, 0);
});

test('a page that reports no event stays silent', async () => {
  const { lookup, input, calls } = harness({ eventName: null });
  input.value = '123 Peachtree St NE';
  await lookup.run();
  assert.equal(calls.tracked.length, 0);
});

test('copy keeps each page pointing at its own fallback control', () => {
  // Not drift: these name where that page's control actually sits. Unifying
  // them would send voters to the wrong part of the page.
  const below = messages({ subject: 'your district', fallbackPhrase: 'pick your county below' });
  const above = messages({ subject: 'your districts', fallbackPhrase: 'choose a county above' });
  assert.match(below.zip, /find your district\./);
  assert.match(below.zip, /pick your county below/);
  assert.match(above.zip, /find your districts\./);
  assert.match(above.zip, /choose a county above/);
  assert.equal(above.working, 'Looking up your districts…');

  // A page with no fallback control at all must not produce a dangling ", or ."
  const none = messages({ subject: 'your districts' });
  assert.equal(none.empty, 'Enter your address.');
  assert.match(none.zip, /Enter your full street address\.$/);
});

test('an async onResolve holds the latch until it finishes', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const h = harness({ onResolve: () => gate });
  h.input.value = '123 Peachtree St NE';

  const run = h.lookup.run();
  await new Promise(r => setImmediate(r));
  assert.equal(h.lookup.isBusy(), true, 'a page still rendering is not done');
  release();
  assert.equal(await run, 'success');
  assert.equal(h.lookup.isBusy(), false);
});

test('a failure while the page renders is reported like any other', async () => {
  // find-my-reps fetches two JSON files inside this step; a fetch that fails
  // must surface and be tracked, not disappear into a resolved lookup.
  const { lookup, input, calls } = harness({
    onResolve: async () => { throw new Error('Could not load member data.'); },
  });
  input.value = '123 Peachtree St NE';

  assert.equal(await lookup.run(), 'error');
  assert.equal(lastStatus(calls)[0], 'Could not load member data.');
  assert.equal(lastEvent(calls)[1].outcome, 'error');
});

test('an async onResolve can still name its own outcome', async () => {
  const { lookup, input, calls } = harness({ onResolve: async () => 'no_district' });
  input.value = '123 Peachtree St NE';
  assert.equal(await lookup.run(), 'no_district');
  assert.equal(lastEvent(calls)[1].outcome, 'no_district');
});
