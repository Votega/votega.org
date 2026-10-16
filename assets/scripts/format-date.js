/*
 * format-date.js — one long-form date formatter for every page.
 *
 * Extracted from the local copy in _includes/entity/race.html when
 * _includes/entity/candidate.html needed the same thing to print an election
 * date. A second copy would drift the same way the fifteen HTML escapers did
 * (see html-escape.js), and a date rendered one day off on one page and right
 * on another is the kind of error nobody reports.
 *
 * Takes an ISO calendar date ("2026-11-03") and returns "November 3, 2026".
 * The parts are split and passed to the Date constructor rather than handed to
 * `new Date(iso)`: the string form is parsed as UTC midnight, which renders as
 * the PREVIOUS day for every viewer west of Greenwich — including all of
 * Georgia. Returns '' for null/undefined/'' so callers can test the result.
 *
 * Usage — pages keep their existing local name, so call sites are untouched:
 *   const formatDate = VoteGA.formatDate;
 */
(function (global) {
  'use strict';

  function formatDate(iso) {
    if (!iso) return '';
    var parts = String(iso).split('-').map(Number);
    if (parts.length < 3 || parts.some(isNaN)) return '';
    return new Date(parts[0], parts[1] - 1, parts[2])
      .toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  }

  global.VoteGA = global.VoteGA || {};
  global.VoteGA.formatDate = formatDate;
})(window);
