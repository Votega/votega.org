/*
 * Unit tests for ResultsContest.officeNote() / unmatchedNotes()
 * (assets/scripts/results-contest.js).
 *
 * Run: node --test tests/js/*.test.js
 *
 * These exist for one contest the vote numbers describe wrongly. The Atlantic
 * Judicial Circuit's District Attorney race on 3 November 2026 is a SPECIAL
 * PRIMARY with a 1 December runoff, called after the incumbent withdrew, with
 * Republican-only qualifying — so a card headed "District Attorney" on a page
 * headed "General Election Results" tells a voter the wrong thing about what
 * their vote decides.
 *
 * The note is matched by OFFICE NAME across a handover: the ballot preview
 * writes that name today, and on election night the whole results file is
 * rebuilt from the Secretary of State's CSV, which writes it again from a
 * different source. Case, dash style, doubled spaces and the CSV's trailing
 * "- Rep" / "- Dem" party suffix all drift across that boundary without
 * changing which office is meant, and a key that stops matching renders
 * nothing at all — indistinguishable from having configured no note. So the
 * normalisation is pinned here, and so is the unmatched-key report that makes
 * the silent case audible.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const { ResultsContest } = loadBrowserModules('assets/scripts/results-contest.js');
const { officeNote, unmatchedNotes, normalizeOffice } = ResultsContest;

const OFFICE = 'District Attorney - Atlantic Judicial Circuit';
const NOTES = {
  [OFFICE]: { label: 'Special Primary', text: 'Not a general election.' },
};

test('the note is found for the office as the preview spells it', () => {
  assert.deepStrictEqual(officeNote(NOTES, OFFICE),
    { label: 'Special Primary', text: 'Not a general election.' });
});

test('the key survives the spellings the handover can produce', () => {
  for (const variant of [
    'district attorney - atlantic judicial circuit',        // case
    'District Attorney — Atlantic Judicial Circuit',   // em dash
    'District Attorney – Atlantic Judicial Circuit',   // en dash
    'District  Attorney  -  Atlantic Judicial Circuit',     // doubled spaces
    'District Attorney - Atlantic Judicial Circuit - Rep',  // CSV party suffix
    'District Attorney - Atlantic Judicial Circuit - Dem',
    '  District Attorney - Atlantic Judicial Circuit  ',    // stray whitespace
  ]) {
    assert.ok(officeNote(NOTES, variant), `should match: ${variant}`);
  }
});

test('a different office gets no note', () => {
  // Not merely a miss: a note leaking onto the wrong card would misdescribe a
  // contest that is perfectly ordinary.
  assert.strictEqual(officeNote(NOTES, 'District Attorney - Columbia Judicial Circuit'), null);
  assert.strictEqual(officeNote(NOTES, 'District 70'), null);
  assert.strictEqual(officeNote(NOTES, 'US Senate'), null);
});

test('a bare string is a note with no label', () => {
  assert.deepStrictEqual(officeNote({ [OFFICE]: 'Just text.' }, OFFICE),
    { label: '', text: 'Just text.' });
});

test('nothing configured is not an error', () => {
  for (const notes of [null, undefined, {}, 'nonsense', 42]) {
    assert.strictEqual(officeNote(notes, OFFICE), null);
  }
  assert.strictEqual(officeNote(NOTES, ''), null);
  assert.strictEqual(officeNote(NOTES, null), null);
  assert.strictEqual(officeNote({ [OFFICE]: '' }, OFFICE), null);
  assert.strictEqual(officeNote({ [OFFICE]: { label: 'x' } }, OFFICE), null);
});

test('a key matching no office on the page is reported, not swallowed', () => {
  assert.deepStrictEqual(
    unmatchedNotes({ 'District Attorney - Nowhere Circuit': 'x' }, [OFFICE]),
    ['District Attorney - Nowhere Circuit']);
  // And a key that matches only by normalisation is NOT reported, or every
  // page would warn about a note that is in fact rendering correctly.
  assert.deepStrictEqual(unmatchedNotes(NOTES, [OFFICE + ' - Rep']), []);
  assert.deepStrictEqual(unmatchedNotes(null, [OFFICE]), []);
  assert.deepStrictEqual(unmatchedNotes(NOTES, []), [OFFICE]);
});

test('normalizeOffice does not collapse two genuinely different offices', () => {
  assert.notStrictEqual(
    normalizeOffice('District Attorney - Atlantic Judicial Circuit'),
    normalizeOffice('District Attorney - Columbia Judicial Circuit'));
  assert.notStrictEqual(normalizeOffice('District 7'), normalizeOffice('District 70'));
});
