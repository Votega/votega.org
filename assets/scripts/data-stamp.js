/*
 * data-stamp.js — one provenance stamp, one date format, for every page.
 *
 * Staleness is the primary failure mode for a civic-data site, but the
 * "last updated" line was only on 7 pages and appeared in three different
 * formats (raw ISO, long-form, and raw-plus-term-cycle). Both core journeys —
 * find-my-reps and elections — showed nothing at all.
 *
 * Usage:
 *   dataStamp.render(el, { updated: meta.generatedAt, source: 'Congress.gov API' });
 *   dataStamp.render(el, { updated: iso, source: 'x', extra: 'Term cycle: 2023-2027' });
 *
 * `updated` accepts an ISO datetime, an ISO date, or null. Anything unparseable
 * is passed through verbatim rather than rendered as "Invalid Date".
 *
 * See CODEBASE-REVIEW-2026-08-18.md finding 4.13.
 */
(function () {
  'use strict';

  // Parse as a *local* calendar date for date-only strings, so a stamp does not
  // read as the previous day for anyone west of UTC.
  function parse(value) {
    if (!value) return null;
    var dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
    if (dateOnly) {
      return new Date(+dateOnly[1], +dateOnly[2] - 1, +dateOnly[3]);
    }
    var d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatDate(value) {
    var d = parse(value);
    if (!d) return value ? String(value) : '';
    return d.toLocaleDateString('en-US', {
      month: 'long', day: 'numeric', year: 'numeric',
    });
  }

  function escape(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Renders into `el` (an element or an id). Returns false and leaves the
  // element empty when there is no date to show, so a page never prints a
  // dangling "Data last updated:" with nothing after it.
  function render(el, opts) {
    var node = typeof el === 'string' ? document.getElementById(el) : el;
    if (!node) return false;
    opts = opts || {};

    var when = formatDate(opts.updated);
    if (!when) { node.textContent = ''; return false; }

    var parts = ['Data last updated: ' + escape(when)];
    if (opts.source) parts.push('Source: ' + escape(opts.source));
    if (opts.extra) parts.push(escape(opts.extra));

    node.classList.add('data-stamp');
    node.innerHTML = parts.join(' &middot; ');
    return true;
  }

  window.dataStamp = { render: render, formatDate: formatDate };
})();
