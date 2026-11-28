/*
 * Unit tests for assets/scripts/votega-votes-table.js.
 *
 * Run: node --test tests/js/
 *
 * These cover the pure logic and the markup fragments — the parts a reader of a
 * legislator page depends on being right: which rows match a search, how many are
 * shown, what the footer offers next, and that a bill title with a quote in it
 * cannot break out of its cell. Rendering into a real DOM is deliberately not
 * tested here; that would mean adding this repo's first JS dependency tree.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const win = loadBrowserModules(
  'assets/scripts/html-escape.js',
  'assets/scripts/format-date.js',
  'assets/scripts/votega-votes-table.js'
);
const VT = win.VotegaVotesTable;

// A small index in the shape both ga-votes-index.json and federal-member-votes.json
// use: { voteId: { bill, title, motionText, date, billUrl } }.
const INDEX = {
  v1: { bill: 'HB 1', title: 'Public order; penalties', motionText: 'PASSAGE', date: '2026-04-03', billUrl: 'https://www.legis.ga.gov/legislation/1' },
  v2: { bill: 'SB 33', title: 'Hemp farming act', motionText: 'Agree to House Substitute', date: '2026-03-12' },
  v3: { bill: 'HB 1112', title: 'Education; school zones', motionText: 'PASSAGE', date: '2026-02-01' },
  v4: { bill: 'HR 9', title: 'Honoring a citizen', motionText: 'ADOPT', date: null },
};
const ENTRIES = [
  { voteId: 'v1', vote: 'Yea' },
  { voteId: 'v2', vote: 'Nay' },
  { voteId: 'v3', vote: 'Not Voting' },
  { voteId: 'v4', vote: 'Yea' },
];

// Counts rows in the <tbody> only: the <thead> contributes a <tr> of its own, so a
// naive count of '<tr>' over the whole table is off by one.
function bodyRows(tableHtml) {
  const body = tableHtml.split('<tbody>')[1] || '';
  return (body.match(/<tr>/g) || []).length;
}

test('normalizeQuery lowercases and drops whitespace', () => {
  assert.strictEqual(VT.normalizeQuery('HB 1'), 'hb1');
  assert.strictEqual(VT.normalizeQuery('  hb   1  '), 'hb1');
  assert.strictEqual(VT.normalizeQuery(null), '');
  assert.strictEqual(VT.normalizeQuery(undefined), '');
});

test('normalizeQuery drops periods as well as whitespace', () => {
  // The federal record numbers bills 'H.R. 5334' and 'S.J.Res. 80'; a reader types
  // 'hr 5334'. Whitespace-only normalization (which suffices for GA's 'HB 32')
  // matched nothing there.
  assert.strictEqual(VT.normalizeQuery('H.R. 5334'), 'hr5334');
  assert.strictEqual(VT.normalizeQuery('hr 5334'), 'hr5334');
  assert.strictEqual(VT.normalizeQuery('S.J.Res. 80'), 'sjres80');
});

test('makeMatcher finds a federal bill number typed without its periods', () => {
  const index = {
    f1: { bill: 'H.R. 5334', title: 'An act', motionText: 'On Passage', date: '2026-04-03' },
    f2: { bill: 'S. 723', title: 'Another act', motionText: 'On Passage', date: '2026-04-02' },
  };
  const entries = [{ voteId: 'f1', vote: 'Yea' }, { voteId: 'f2', vote: 'Nay' }];
  assert.deepStrictEqual(entries.filter(VT.makeMatcher({ q: 'hr 5334' }, index)).map(e => e.voteId), ['f1']);
  assert.deepStrictEqual(entries.filter(VT.makeMatcher({ q: 's723' }, index)).map(e => e.voteId), ['f2']);
});

test('voteBucket collapses every non-Yea/Nay option to other', () => {
  assert.strictEqual(VT.voteBucket('Yea'), 'yea');
  assert.strictEqual(VT.voteBucket('Nay'), 'nay');
  for (const v of ['Not Voting', 'Present', 'Absent', 'Excused', 'Other', '', undefined]) {
    assert.strictEqual(VT.voteBucket(v), 'other', `expected ${v} to bucket as other`);
  }
});

test('voteClass maps to the stylesheet classes', () => {
  assert.strictEqual(VT.voteClass('Yea'), 'vote-yea');
  assert.strictEqual(VT.voteClass('Nay'), 'vote-nay');
  assert.strictEqual(VT.voteClass('Excused'), 'vote-other');
});

test('fmtDate formats ISO dates and datetimes alike', () => {
  assert.strictEqual(VT.fmtDate('2026-04-03'), 'Apr 3, 2026');
  assert.strictEqual(VT.fmtDate('2026-04-03T14:22:00'), 'Apr 3, 2026');
});

test('fmtDate returns an em dash rather than "Invalid Date"', () => {
  assert.strictEqual(VT.fmtDate(null), '—');
  assert.strictEqual(VT.fmtDate(''), '—');
  assert.strictEqual(VT.fmtDate('not-a-date'), '—');
});

test('fmtDate keeps the calendar date west of UTC', () => {
  // Parsed as UTC, 2026-01-01 renders as Dec 31 for anyone behind UTC — the bug
  // data-stamp.js documents. Must stay Jan 1.
  assert.strictEqual(VT.fmtDate('2026-01-01'), 'Jan 1, 2026');
});

test('sortByDate orders most recent first without mutating its input', () => {
  const input = ENTRIES.slice();
  const sorted = VT.sortByDate(input, INDEX);
  assert.deepStrictEqual(sorted.map(e => e.voteId), ['v1', 'v2', 'v3', 'v4']);
  assert.deepStrictEqual(input.map(e => e.voteId), ['v1', 'v2', 'v3', 'v4']);
  assert.notStrictEqual(sorted, input);
});

test('sortByDate puts dateless entries last rather than first', () => {
  const sorted = VT.sortByDate([{ voteId: 'v4', vote: 'Yea' }, { voteId: 'v3', vote: 'Nay' }], INDEX);
  assert.deepStrictEqual(sorted.map(e => e.voteId), ['v3', 'v4']);
});

test('makeMatcher finds a bill number regardless of spacing', () => {
  const m = VT.makeMatcher({ q: 'hb1' }, INDEX);
  const hits = ENTRIES.filter(m).map(e => e.voteId);
  assert.deepStrictEqual(hits, ['v1', 'v3']);   // HB 1 and HB 1112
  const spaced = VT.makeMatcher({ q: 'HB 1' }, INDEX);
  assert.deepStrictEqual(ENTRIES.filter(spaced).map(e => e.voteId), hits);
});

test('makeMatcher searches title and motion text too', () => {
  assert.deepStrictEqual(ENTRIES.filter(VT.makeMatcher({ q: 'hemp' }, INDEX)).map(e => e.voteId), ['v2']);
  assert.deepStrictEqual(ENTRIES.filter(VT.makeMatcher({ q: 'adopt' }, INDEX)).map(e => e.voteId), ['v4']);
});

test('makeMatcher filters by vote bucket, alone and combined with a query', () => {
  assert.deepStrictEqual(ENTRIES.filter(VT.makeMatcher({ vote: 'yea' }, INDEX)).map(e => e.voteId), ['v1', 'v4']);
  assert.deepStrictEqual(ENTRIES.filter(VT.makeMatcher({ vote: 'other' }, INDEX)).map(e => e.voteId), ['v3']);
  assert.deepStrictEqual(ENTRIES.filter(VT.makeMatcher({ q: 'hb1', vote: 'yea' }, INDEX)).map(e => e.voteId), ['v1']);
});

test('makeMatcher with no filter matches everything, nonsense matches nothing', () => {
  assert.strictEqual(ENTRIES.filter(VT.makeMatcher({}, INDEX)).length, ENTRIES.length);
  assert.strictEqual(ENTRIES.filter(VT.makeMatcher({ q: 'zzzznotabill' }, INDEX)).length, 0);
});

test('isFiltered reports whether any control is engaged', () => {
  assert.strictEqual(VT.isFiltered({}), false);
  assert.strictEqual(VT.isFiltered({ q: '', vote: 'all' }), false);
  assert.strictEqual(VT.isFiltered({ q: 'hb' }), true);
  assert.strictEqual(VT.isFiltered({ vote: 'nay' }), true);
});

test('nextOffset grows by the step and stops at the total', () => {
  assert.strictEqual(VT.nextOffset(25, 1109, 100), 125);
  assert.strictEqual(VT.nextOffset(1050, 1109, 100), 1109);
  assert.strictEqual(VT.nextOffset(25, 1109, 'all'), 1109);
  assert.strictEqual(VT.nextOffset(1109, 1109, 100), 1109);
});

test('rowsHtml renders one row per entry', () => {
  const html = VT.rowsHtml(ENTRIES, INDEX, {});
  assert.strictEqual((html.match(/<tr>/g) || []).length, ENTRIES.length);
  assert.ok(html.includes('vote-yea'));
  assert.ok(html.includes('vote-nay'));
});

test('rowsHtml omits the Motion cell when showMotion is false', () => {
  const withMotion = VT.rowsHtml([ENTRIES[0]], INDEX, { showMotion: true });
  const without = VT.rowsHtml([ENTRIES[0]], INDEX, { showMotion: false });
  assert.ok(withMotion.includes('PASSAGE'));
  assert.ok(!without.includes('PASSAGE'));
  assert.strictEqual((withMotion.match(/<td/g) || []).length, 4);
  assert.strictEqual((without.match(/<td/g) || []).length, 3);
});

test('rowsHtml places the cell() callback output in the Bill cell', () => {
  const html = VT.rowsHtml([ENTRIES[0]], INDEX, {
    cell: meta => meta.bill === 'HB 1' ? '<span class="law">P.L. 119-1</span>' : '',
  });
  assert.ok(html.includes('<span class="law">P.L. 119-1</span>'));
});

test('rowsHtml appends cellAfter() below the title, not beside the bill number', () => {
  const html = VT.rowsHtml([ENTRIES[0]], INDEX, {
    cell: () => '<i>beside</i>',
    cellAfter: () => '<span class="vote-law-cell">P.L. 119-1</span>',
  });
  const billCell = html.split('<td>')[2];
  assert.ok(billCell.indexOf('<i>beside</i>') < billCell.indexOf('Public order'),
    'cell() output belongs before the title');
  assert.ok(billCell.indexOf('vote-law-cell') > billCell.indexOf('Public order'),
    'cellAfter() output belongs after the title');
});

test('rowsHtml escapes a title that would otherwise break out of the cell', () => {
  const index = { x: { bill: 'HB <2>', title: 'Earl L. "Buddy" Carter & <script>', motionText: 'PASSAGE', date: '2026-04-03' } };
  const html = VT.rowsHtml([{ voteId: 'x', vote: 'Yea' }], index, {});
  assert.ok(html.includes('&quot;Buddy&quot;'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('&amp;'));
  assert.ok(!html.includes('<script>'));
});

test('tableHtml renders only the shown slice and tags the table with its key', () => {
  const html = VT.tableHtml(ENTRIES, INDEX, { key: '2025_26', shown: 2 });
  assert.strictEqual(bodyRows(html), 2);
  assert.ok(html.includes('data-vote-table="2025_26"'));
});

test('tableHtml shows every row when no slice is given', () => {
  const html = VT.tableHtml(ENTRIES, INDEX, {});
  assert.strictEqual(bodyRows(html), ENTRIES.length);
});

test('tableHtml drops the Motion header along with the cells', () => {
  assert.ok(!VT.tableHtml(ENTRIES, INDEX, { showMotion: false }).includes('<th>Motion</th>'));
  assert.ok(VT.tableHtml(ENTRIES, INDEX, {}).includes('<th>Motion</th>'));
});

test('footHtml offers both growth controls while rows remain', () => {
  const html = VT.footHtml({ key: 'k', total: 1109, shown: 25, pageStep: 100 });
  assert.ok(html.includes('Showing 25 of 1109 votes'));
  assert.ok(html.includes('Load 100 more'));
  assert.ok(html.includes('Show all 1109'));
});

test('footHtml never offers more rows than remain', () => {
  assert.ok(VT.footHtml({ key: 'k', total: 51, shown: 25, pageStep: 100 }).includes('Load 26 more'));
});

test('footHtml drops the buttons once everything is shown', () => {
  const html = VT.footHtml({ key: 'k', total: 40, shown: 40 });
  assert.ok(html.includes('Showing 40 of 40 votes'));
  assert.ok(!html.includes('vote-page-btn'));
});

test('footHtml says "matching" only when a filter is engaged', () => {
  assert.ok(VT.footHtml({ key: 'k', total: 37, shown: 25, filtered: true }).includes('of 37 matching votes'));
  assert.ok(VT.footHtml({ key: 'k', total: 37, shown: 25 }).includes('of 37 votes'));
});

test('footHtml renders nothing for an empty table', () => {
  assert.strictEqual(VT.footHtml({ key: 'k', total: 0, shown: 0 }), '');
});

test('footHtml singularises a one-vote table', () => {
  assert.ok(VT.footHtml({ key: 'k', total: 1, shown: 1 }).includes('1 of 1 vote<'));
});

test('chartHtml draws a circle, not an arc, for a single 100% slice', () => {
  const html = VT.chartHtml(10, 0, 0, 10, {});
  assert.ok(html.includes('<circle'));
  assert.ok(!html.includes('<path'));
  assert.ok(html.includes('(100%)'));
});

test('chartHtml draws arcs for a mixed breakdown and footnotes Other', () => {
  const html = VT.chartHtml(6, 3, 1, 10, {});
  assert.ok(html.includes('<path'));
  assert.ok(html.includes('Other includes Not Voting, Absent, and Excused'));
});

test('chartHtml omits the Other footnote when there is no Other', () => {
  assert.ok(!VT.chartHtml(6, 4, 0, 10, {}).includes('Other includes'));
});

test('chartHtml renders nothing with no votes', () => {
  assert.strictEqual(VT.chartHtml(0, 0, 0, 0, {}), '');
});

test('chartHtml uses the chart palette, not the table text colors', () => {
  // Regression guard: the pie slices use the success / danger / muted tokens, not the
  // .vote-yea and .vote-nay table text colors. An extraction of this function once
  // swapped in the text colors, which a snapshot diff of the rendered panel caught;
  // this keeps it caught here instead. Tokens go in through style="fill:var(...)".
  const html = VT.chartHtml(6, 3, 1, 10, {});
  assert.ok(html.includes('fill:var(--color-success)'), 'yea slice color');
  assert.ok(html.includes('fill:var(--color-danger)'), 'nay slice color');
  assert.ok(html.includes('fill:var(--color-text-muted)'), 'other slice color');
  assert.ok(!html.includes('vote-yea'), 'must not use the .vote-yea text color');
  assert.ok(!html.includes('vote-nay'), 'must not use the .vote-nay text color');
});

test('filterRowHtml wires its labels to the ids it was given', () => {
  const html = VT.filterRowHtml({ searchId: 'gaVoteSearch', voteId: 'gaVoteResult' });
  assert.ok(html.includes('for="gaVoteSearch"'));
  assert.ok(html.includes('id="gaVoteSearch"'));
  assert.ok(html.includes('for="gaVoteResult"'));
  assert.ok(html.includes('<option value="nay">Nay</option>'));
});

// -- The opt-in Type control (senators' pages) --------------------------------
// category is "C" (confirmation), "N" (other nomination vote) or absent.
const TYPED_INDEX = {
  c: { bill: null, title: 'Ann Alpha, to be a judge', motionText: 'On the Nomination', date: '2026-04-04', category: 'C' },
  n: { bill: null, title: 'Ann Alpha, to be a judge', motionText: 'On the Cloture Motion', date: '2026-04-03', category: 'N' },
  b: { bill: 'S. 5', title: 'A bill', motionText: 'On Passage of the Bill', date: '2026-04-02', category: null },
  o: { bill: 'S. 6', title: 'Another', motionText: 'On the Amendment', date: '2026-04-01' },
};
const TYPED = [
  { voteId: 'c', vote: 'Nay' }, { voteId: 'n', vote: 'Yea' },
  { voteId: 'b', vote: 'Yea' }, { voteId: 'o', vote: 'Nay' },
];
const typedIds = filter => TYPED.filter(VT.makeMatcher(filter, TYPED_INDEX)).map(e => e.voteId);

test('makeMatcher filters by nomination type', () => {
  assert.deepStrictEqual(typedIds({ type: 'all' }), ['c', 'n', 'b', 'o']);
  assert.deepStrictEqual(typedIds({ type: 'confirm' }), ['c']);
  assert.deepStrictEqual(typedIds({ type: 'nomination' }), ['c', 'n']);
  assert.deepStrictEqual(typedIds({ type: 'other' }), ['b', 'o']);
});

test('Type combines with Vote and Search', () => {
  assert.deepStrictEqual(typedIds({ type: 'nomination', vote: 'yea' }), ['n']);
  assert.deepStrictEqual(typedIds({ type: 'nomination', q: 'cloture' }), ['n']);
  assert.deepStrictEqual(typedIds({ type: 'confirm', vote: 'yea' }), []);
  assert.deepStrictEqual(typedIds({ type: 'other', vote: 'nay', q: 's6' }), ['o']);
});

test('isFiltered counts an engaged Type', () => {
  assert.strictEqual(VT.isFiltered({ type: 'all' }), false);
  assert.strictEqual(VT.isFiltered({ type: 'confirm' }), true);
});

test('makeMatcher takes an extra match for text the row does not hold', () => {
  const extraMatch = (entry, q) => entry.voteId === 'c' && q === 'zedzulu';
  const hits = filter => TYPED.filter(VT.makeMatcher(filter, TYPED_INDEX, { extraMatch })).map(e => e.voteId);
  assert.deepStrictEqual(hits({ q: 'Zed Zulu' }), ['c']);
  assert.deepStrictEqual(hits({ q: 'Zed Zulu', vote: 'yea' }), [], 'Vote still applies');
  assert.deepStrictEqual(hits({ q: 'bill' }), ['b'], 'the row text is still searched');
});

test('rowAfter adds a full-width line under only the rows that have one', () => {
  const rowAfter = (meta, entry) => (entry.voteId === 'c' ? '<i>more</i>' : '');
  const html = VT.rowsHtml(TYPED, TYPED_INDEX, { rowAfter });
  assert.strictEqual((html.match(/vote-extra-row/g) || []).length, 1);
  assert.ok(html.includes('<tr class="vote-extra-row"><td colspan="4"><i>more</i></td></tr>'));
  assert.ok(html.indexOf('vote-extra-row') < html.indexOf('On the Cloture Motion'), 'it follows its own row');
  assert.ok(VT.rowsHtml(TYPED, TYPED_INDEX, { rowAfter, showMotion: false }).includes('colspan="3"'));
  assert.ok(!VT.rowsHtml(TYPED, TYPED_INDEX, {}).includes('vote-extra-row'));
});

const TYPE_OPTS = {
  searchId: 's', voteId: 'v', typeId: 't', typeNoteId: 'tn', placeholder: 'Bill number, title or nominee',
  types: [
    { value: 'all', label: 'All votes (4)', description: 'Every vote.' },
    { value: 'confirm', label: 'Confirmation votes (1)', description: 'The final "vote".' },
  ],
};

test('filterRowHtml adds no Type control unless a caller asks for one', () => {
  const html = VT.filterRowHtml({ searchId: 'gaVoteSearch', voteId: 'gaVoteResult' });
  assert.ok(!html.includes('Type'));
  assert.ok(!html.includes('vote-type-note'));
  assert.ok(html.includes('<div class="vote-filter-row">'), 'the class a caller without Type always had');
  assert.strictEqual((html.match(/<select/g) || []).length, 1);
});

test('filterRowHtml places Type between Search and Vote, described below the row', () => {
  const html = VT.filterRowHtml(TYPE_OPTS);
  assert.ok(html.includes('<div class="vote-filter-row vote-filter-row-typed">'), 'stacks on a phone');
  assert.ok(html.indexOf('id="s"') < html.indexOf('id="t"'));
  assert.ok(html.indexOf('id="t"') < html.indexOf('id="v"'));
  assert.ok(html.includes('for="t">Type</label>'));
  assert.ok(html.includes('<option value="confirm">Confirmation votes (1)</option>'));
  assert.ok(html.includes('placeholder="Bill number, title or nominee"'));
  assert.ok(/id="tn"[^>]*>Every vote\.<\/p>/.test(html));
});

// A stub document: enough of an element to bind listeners and fire them.
function stubPanel(withType) {
  const el = value => {
    const handlers = {};
    return { value, textContent: '', addEventListener: (name, fn) => { handlers[name] = fn; }, fire: (name, ev) => handlers[name](ev) };
  };
  const els = { s: el(''), v: el('all'), root: el('') };
  if (withType) { els.t = el('all'); els.tn = el(''); }
  win.document = { getElementById: id => els[id] || null };
  const calls = [];
  let cleared = 0;
  VT.mountControls({
    searchId: 's', voteId: 'v', typeId: withType ? 't' : undefined, typeNoteId: 'tn',
    types: TYPE_OPTS.types, tablesRoot: 'root',
    onFilter: f => calls.push(f), onClear: () => { cleared++; },
  });
  return { els, calls, cleared: () => cleared };
}

test('the description follows the selected Type', () => {
  const { els, calls } = stubPanel(true);
  els.t.value = 'confirm';
  els.t.fire('change');
  assert.strictEqual(els.tn.textContent, 'The final "vote".');
  assert.deepStrictEqual(calls, [{ q: '', vote: 'all', type: 'confirm' }]);
  els.v.value = 'nay';
  els.v.fire('change');
  assert.deepStrictEqual(calls[1], { q: '', vote: 'nay', type: 'confirm' });
  delete win.document;
});

test('Clear filters resets Type and its description', () => {
  const { els, cleared } = stubPanel(true);
  els.s.value = 'x';
  els.v.value = 'nay';
  els.t.value = 'confirm';
  els.t.fire('change');
  els.root.fire('click', { preventDefault() {}, target: { closest: sel => (sel === '[data-clear-filters]' ? {} : null) } });
  assert.deepStrictEqual([els.s.value, els.v.value, els.t.value, els.tn.textContent], ['', 'all', 'all', 'Every vote.']);
  assert.strictEqual(cleared(), 1);
  delete win.document;
});

test('a panel without Type reports only Search and Vote', () => {
  const { els, calls } = stubPanel(false);
  els.v.value = 'yea';
  els.v.fire('change');
  assert.deepStrictEqual(calls, [{ q: '', vote: 'yea' }]);
  delete win.document;
});
