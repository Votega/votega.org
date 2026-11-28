/*
 * format-date.js — the one date formatter for every page.
 *
 * Loaded sitewide and synchronously by _includes/head.html, so it is defined
 * before any page or module script runs. One formatter because local copies
 * drift: pages mixed "October 20, 2026" with "Oct 20, 2026", some followed the
 * browser's locale, and a date rendered one day off on one page and right on
 * another is the kind of error nobody reports.
 *
 *   VoteGA.formatDate(value)                        "October 20, 2026"  (prose)
 *   VoteGA.formatDate(value, { style: 'short' })    "Oct 20, 2026"      (tables, data)
 *   ... { weekday: true }                           "Tuesday, October 20, 2026"
 *   ... { year: false }                             "October 20" / "Oct 20"
 *
 * `value` is a bare calendar date ("2026-11-03"), an ISO timestamp or a Date.
 * Output is always en-US.
 *
 * A bare date is built from its parts rather than handed to `new Date(iso)`: the
 * string form is parsed as UTC midnight, which renders as the PREVIOUS day for
 * every viewer west of Greenwich — including all of Georgia. A timestamp is an
 * instant and shows on the viewer's local day; a caller that wants the calendar
 * date written in a timestamp passes String(value).slice(0, 10).
 *
 * Returns '' for null/undefined/'' and for anything that is not a real date
 * ("2026-13-45" is not February 2027), so callers can test the result and
 * choose their own fallback.
 */
(function (global) {
  'use strict';

  var ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})([T ]\d{2}:\d{2}.*)?$/;

  function toDate(value) {
    if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
    var m = ISO.exec(String(value));
    if (!m) return null;
    var y = +m[1], month = +m[2] - 1, d = +m[3];
    var day = new Date(y, month, d);
    // Date rolls out-of-range parts over (month 13, day 45), so check they survived.
    if (day.getFullYear() !== y || day.getMonth() !== month || day.getDate() !== d) return null;
    if (!m[4]) return day;
    var instant = new Date(String(value).replace(' ', 'T'));
    return isNaN(instant.getTime()) ? null : instant;
  }

  function formatDate(value, options) {
    if (!value) return '';
    var date = toDate(value);
    if (!date) return '';
    var opts = options || {};
    var length = opts.style === 'short' ? 'short' : 'long';
    var fields = { month: length, day: 'numeric' };
    if (opts.year !== false) fields.year = 'numeric';
    if (opts.weekday) fields.weekday = length;
    return date.toLocaleDateString('en-US', fields);
  }

  global.VoteGA = global.VoteGA || {};
  global.VoteGA.formatDate = formatDate;
})(window);
