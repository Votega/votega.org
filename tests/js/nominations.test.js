/*
 * Unit tests for assets/scripts/votega-nominations.js: the nomination Type filter
 * on senators' Voting History, its definitions, and the en bloc nominee lists.
 *
 * Run: node --test tests/js/
 *
 * Two of these read the committed data on purpose: every motion a nomination row can
 * show must have a definition, and every en bloc row must be able to find its list.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadBrowserModules, REPO_ROOT } = require('./load-browser-module');

const win = loadBrowserModules(
  'assets/scripts/html-escape.js',
  'assets/scripts/format-date.js',
  'assets/scripts/votega-votes-table.js',
  'assets/scripts/votega-nominations.js'
);
const NOM = win.VotegaNominations;
const VT = win.VotegaVotesTable;
const readData = name => JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'assets', 'data', name), 'utf8'));

const row = extra => Object.assign(
  { bill: null, title: 't', motionText: 'On the Nomination', date: '2026-01-01', category: 'C', nomineeCount: 1 }, extra);
const LABEL = 'En bloc: 2 nominations, including Ann Alpha';
const INDEX = {
  S119_1_00526: row({ title: LABEL, nomineeCount: 2 }),
  S119_1_00525: row({ title: LABEL, motionText: 'On the Cloture Motion', category: 'N', nomineeCount: 2 }),
  S119_1_00001: row({}),
  S119_1_00002: row({ category: null, nomineeCount: null, bill: 'S. 5', motionText: 'On the Amendment' }),
};
const ENTRIES = Object.keys(INDEX).map(voteId => ({ voteId, vote: 'Nay' }));
const BOTH = ['S119_1_00525', 'S119_1_00526'];
const LIST = [
  { pn: 'PN55-25', name: 'Ann Alpha', state: 'Ohio', position: 'Ambassador to Greece', title: 'Ann Alpha, of Ohio, to be Ambassador to Greece' },
  { pn: 'PN18', name: "Zed O'Zulu", state: 'District of Columbia', position: 'Solicitor', title: "Zed O'Zulu, of the District of Columbia, to be Solicitor" },
];
const DOC = { metadata: { congress: 119 }, batches: { b: LIST }, votes: { S119_1_00526: 'b', S119_1_00525: 'b' }, pending: [] };

const okFetch = doc => () => Promise.resolve({ ok: true, json: () => Promise.resolve(doc) });

function quietly(fn) {
  const seen = [];
  const warn = console.warn;
  console.warn = (...a) => seen.push(a.join(' '));
  const done = () => { console.warn = warn; };
  const out = fn(seen);
  if (out && out.then) return out.finally(done);
  done();
  return out;
}

test('type options carry counts, and an empty option is not offered', () => {
  const opts = NOM.typeOptions(ENTRIES, INDEX);
  assert.deepStrictEqual(opts.map(o => o.label),
    ['All votes (4)', 'Confirmation votes (2)', 'All nomination votes (3)', 'Legislation and other (1)']);
  assert.ok(opts.every(o => o.description));
  const noOther = NOM.typeOptions(ENTRIES.slice(0, 3), INDEX).map(o => o.value);
  assert.deepStrictEqual(noOther, ['all', 'confirm', 'nomination']);
});

test('the control is offered only to a record with a nomination vote', () => {
  assert.strictEqual(NOM.hasNominations(ENTRIES, INDEX), true);
  assert.strictEqual(NOM.hasNominations([ENTRIES[3]], INDEX), false);
});

test('chart caption and scope note name what the chart covers', () => {
  assert.strictEqual(NOM.chartCaption('confirm'),
    'Counts are roll calls, not nominees. One en bloc vote can cover many nominees.');
  assert.strictEqual(NOM.chartCaption('nomination'), NOM.chartCaption('confirm'));
  assert.strictEqual(NOM.chartCaption('all'), null);
  assert.strictEqual(NOM.chartCaption('other'), null);
  assert.strictEqual(NOM.scopeNote('confirm', 228, false), 'The breakdown above covers all 228 confirmation votes.');
  assert.strictEqual(NOM.scopeNote('nomination', 490, true),
    'The breakdown above covers all 490 nomination votes, not the filtered list.');
  assert.strictEqual(NOM.scopeNote('all', 938, true), 'The breakdown above covers all 938 votes, not the filtered list.');
});

test('every nomination motion in the data has a legend definition', () => {
  const index = readData('federal-votes-index.json');
  const at = name => index.metadata.sliceFormat.indexOf(name);
  assert.ok(at('category') > 0, 'the index carries category');
  const nomination = index.rows.filter(r => r[at('category')]);
  assert.ok(nomination.length > 0);
  const motions = [...new Set(nomination.map(r => index.motions[r[at('motion')]]))];
  assert.deepStrictEqual(motions.filter(m => !NOM.definitionFor(m)), []);
});

test('every en bloc row in the data finds a complete list or is pending', () => {
  const index = readData('federal-votes-index.json');
  const doc = readData('federal-en-bloc-nominees.json');
  const at = name => index.metadata.sliceFormat.indexOf(name);
  let enBloc = 0;
  index.rows.forEach((r, i) => {
    if (!(r[at('nomineeCount')] > 1)) return;
    enBloc++;
    const id = index.voteIds[i];
    const list = NOM.listFor(doc, id, { nomineeCount: r[at('nomineeCount')] });
    assert.ok(list || doc.pending.includes(id), id);
  });
  assert.ok(enBloc > 0 || index.metadata.congress !== 119);
});

test('the legend lists only terms this record shows, plus the filter options', () => {
  const html = NOM.legendHtml(ENTRIES, INDEX);
  assert.ok(html.startsWith('<details'));
  assert.ok(!/<details[^>]*\sopen/.test(html));
  assert.ok(html.includes('What do these terms mean?'));
  assert.ok(html.includes('fa-solid'));
  for (const label of ['All votes', 'Confirmation votes', 'All nomination votes', 'Legislation and other']) {
    assert.ok(html.includes(label), label);
  }
  assert.ok(html.includes('Shown as: On the Cloture Motion'));
  assert.ok(!html.includes('Motion to table'), 'absent from this record');
  assert.ok(!html.includes('En bloc resolution'), 'absent from this record');
  assert.ok(!html.includes('did not cast a vote'), 'this record has no Not Voting');
  const more = NOM.legendHtml(
    [{ voteId: 'r', vote: 'Not Voting' }],
    { r: row({ bill: 'S.Res. 377', motionText: 'On the Resolution', category: 'N', nomineeCount: null }) });
  assert.ok(more.includes('En bloc resolution'));
  assert.ok(more.includes('did not cast a vote'));
  assert.ok(!more.includes('Shown as: On the Nomination'));
});

test('a nomination motion with no definition is left out and logged', () => {
  quietly(seen => {
    const html = NOM.legendHtml([{ voteId: 'p', vote: 'Yea' }, { voteId: 'q', vote: 'Yea' }], {
      p: row({ motionText: 'On the Point of Order', category: 'N' }),
      q: row({ motionText: 'On the Amendment', category: null }),
    });
    assert.ok(!html.includes('Point of Order'));
    assert.strictEqual(seen.length, 1, 'legislation motions are not logged');
    assert.ok(seen[0].includes('On the Point of Order'));
  });
});

test('links: Congress.gov nomination pages, with and without a part number', () => {
  assert.strictEqual(NOM.nominationUrl(119, 'PN55-25'), 'https://www.congress.gov/nomination/119th-congress/55/25');
  assert.strictEqual(NOM.nominationUrl(119, 'PN18'), 'https://www.congress.gov/nomination/119th-congress/18');
  assert.strictEqual(NOM.nominationUrl(121, 'PN1'), 'https://www.congress.gov/nomination/121st-congress/1');
  assert.strictEqual(NOM.nominationUrl(119, 'junk"><'), null);
  assert.strictEqual(NOM.senateVoteUrl('S119_1_00526'),
    'https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00526.htm');
  assert.strictEqual(NOM.senateVoteUrl('H2026_0001'), null);
});

test('a list is complete or not shown at all', () => {
  assert.strictEqual(NOM.listFor(DOC, 'S119_1_00526', INDEX.S119_1_00526), LIST);
  assert.strictEqual(NOM.listFor(DOC, 'S119_1_00526', { nomineeCount: 3 }), null);
  assert.strictEqual(NOM.listFor(DOC, 'S119_2_00001', { nomineeCount: 2 }), null);
  assert.strictEqual(NOM.listFor(null, 'S119_1_00526', { nomineeCount: 2 }), null);
});

test('search finds a nominee who is not first in a batch, by name, state or position', async () => {
  const loader = NOM.createLoader('u', okFetch(DOC));
  await loader.load();
  const extraMatch = NOM.extraMatcher(loader, INDEX);
  for (const q of ["o'zulu", 'district of columbia', 'solicitor']) {
    const hits = ENTRIES.filter(VT.makeMatcher({ q }, INDEX, { extraMatch })).map(e => e.voteId);
    assert.deepStrictEqual(hits.sort(), BOTH, q);
  }
  const html = NOM.rowHtml('S119_1_00526', INDEX.S119_1_00526, loader, 'solicitor');
  const matched = html.slice(html.indexOf('Matched nominee'), html.indexOf('<details'));
  assert.ok(matched.includes('Zulu'));
  assert.ok(!matched.includes('Ann Alpha'), 'only the one that matched is named');
});

test('boilerplate in a title does not match every batch', () => {
  assert.deepStrictEqual(NOM.matchNominees(LIST, 'tobe'), []);
});

test('an en bloc row offers its list, the caveat and the official roll call', () => {
  const loader = NOM.createLoader('u', okFetch(DOC));
  const html = NOM.rowHtml('S119_1_00526', INDEX.S119_1_00526, loader, '');
  assert.ok(html.includes('<summary>Show all 2 nominations</summary>'));
  assert.ok(html.includes('data-nominees="S119_1_00526"'));
  const after = html.split('</details>')[1];
  assert.ok(after.includes('The Senate took one vote on this whole group. A senator&rsquo;s vote does not show a view on any one nominee.'),
    'the caveat is outside the <details>, so it is always visible');
  assert.ok(after.includes('vote_119_1_00526.htm'));
  assert.strictEqual(NOM.rowHtml('S119_1_00001', INDEX.S119_1_00001, loader, ''), '', 'a single nomination is unchanged');
});

test('a Voteview en bloc row shows no list, only that names are pending', () => {
  const meta = row({ title: 'En bloc', nomineeCount: null });
  const html = NOM.rowHtml('S119_2_00300', meta, null, '');
  assert.strictEqual(NOM.isEnBloc(meta), true);
  assert.ok(!html.includes('<details'));
  assert.ok(html.includes('not available yet'));
  assert.ok(html.includes('vote_119_2_00300.htm'));
});

test('the nominee list links each name to Congress.gov and escapes the source text', () => {
  const html = NOM.listHtml([
    LIST[0],
    { pn: 'PN2', name: '<img src=x>', state: 'Ohio', position: 'a "b"', title: '<img src=x>, of Ohio, to be a "b"' },
    { pn: 'PN3', name: null, state: null, position: null, title: 'Air Force nominations <b>' },
  ], 119);
  assert.strictEqual((html.match(/<li>/g) || []).length, 3);
  assert.ok(html.includes('<a href="https://www.congress.gov/nomination/119th-congress/55/25" target="_blank" rel="noopener">Ann Alpha</a>, of Ohio, to be Ambassador to Greece'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<b>'));
  assert.ok(html.includes('&quot;b&quot;'));
});

test('the file is fetched only when asked, and once', async () => {
  let calls = 0;
  const loader = NOM.createLoader('u', () => { calls++; return okFetch(DOC)(); });
  NOM.rowHtml('S119_1_00526', INDEX.S119_1_00526, loader, 'ann');
  NOM.extraMatcher(loader, INDEX)(ENTRIES[0], 'ann');
  assert.strictEqual(calls, 0);
  await Promise.all([loader.load(), loader.load()]);
  await loader.load();
  assert.strictEqual(calls, 1);
});

test('a failed load leaves the page working, and can be retried', () => quietly(async () => {
  let calls = 0;
  const loader = NOM.createLoader('u', () => (++calls === 1 ? Promise.resolve({ ok: false, status: 404 }) : okFetch(DOC)()));
  assert.strictEqual(await loader.load(), null);
  assert.strictEqual(loader.failed(), true);
  const extraMatch = NOM.extraMatcher(loader, INDEX);
  const hits = ENTRIES.filter(VT.makeMatcher({ q: 'ann alpha' }, INDEX, { extraMatch })).map(e => e.voteId);
  assert.deepStrictEqual(hits.sort(), BOTH, 'the label is still searchable');
  const html = NOM.rowHtml('S119_1_00526', INDEX.S119_1_00526, loader, '');
  assert.ok(html.includes('vote_119_1_00526.htm'));
  assert.strictEqual(NOM.searchStatus(loader, ENTRIES, INDEX, 'ann'),
    'En bloc nominee names could not be loaded, so this search does not cover them.');
  assert.ok(await loader.load());
  assert.strictEqual(loader.failed(), false);
  assert.strictEqual(NOM.searchStatus(loader, ENTRIES, INDEX, 'ann'), '');
}));

test('a file of the wrong shape counts as a failed load', () => quietly(async () => {
  const loader = NOM.createLoader('u', okFetch({ nothing: true }));
  assert.strictEqual(await loader.load(), null);
  assert.strictEqual(loader.failed(), true);
}));

test('search says when some names are not available yet', async () => {
  const index = Object.assign({ S119_2_00300: row({ title: 'En bloc', nomineeCount: null }) }, INDEX);
  const entries = ENTRIES.concat({ voteId: 'S119_2_00300', vote: 'Yea' });
  const loader = NOM.createLoader('u', okFetch(DOC));
  assert.strictEqual(NOM.searchStatus(loader, entries, index, 'ann'), 'Loading en bloc nominee names…');
  await loader.load();
  assert.strictEqual(NOM.searchStatus(loader, entries, index, 'ann'),
    'Names for 1 en bloc vote are not available yet, so this search does not cover it.');
  assert.strictEqual(NOM.searchStatus(loader, entries, index, ''), '');
});
