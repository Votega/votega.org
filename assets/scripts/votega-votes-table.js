/*
 * votega-votes-table.js — one voting-history table for every legislator page.
 *
 * The GA and federal legislator entity pages render the same thing: a member's
 * roll calls as Date / Bill (+ title) / Motion / Vote, under a Yea-Nay-Other pie
 * chart. Both pages grew their own copy of that code, and the copies drifted —
 * two `.vote-table` stylesheets, two `buildVoteChart()` implementations differing
 * only by a stray comment and one sentence's punctuation, two date-desc sorts,
 * two `voteClass()` maps. Adding the search/filter row and the progressive
 * "Load more" paging to both pages would have made it four duplications.
 *
 * The data shapes already agree, which is why one module can serve both: a list
 * of { voteId, vote } against an index keyed by voteId carrying bill, title,
 * motionText, date and billUrl.
 *
 * This module owns the TABLE and the controls around it — nothing above them.
 * Each page still assembles its own panel, because what sits between the chart
 * and the table is genuinely page-specific: GA has session grouping, a
 * participation box, party loyalty and a scorecard link; the federal page has an
 * enacted-law connector and a chamber-dependent column set. Same division of
 * labour as campaign-finance.js, which hands race.html and candidate.html their
 * matchers, formatters and a provenance fragment and lets each build its panel.
 *
 * Two hooks carry every difference between the callers:
 *   showMotion — the federal page hides the Motion column for House members.
 *   billLink(meta, escapedBill) — overrides the bill-number anchor (GA points it
 *     at our own bill page; the federal page keeps the default off-site link)
 *   cell(meta) — extra HTML for the Bill cell: GA's record/text links, the federal
 *                page's "P.L. … / Official text (GPO) →" line.
 *
 * Exposed on window.VotegaVotesTable. Tested by tests/js/votes-table.test.js,
 * which evaluates this file against a stub window — so nothing here may touch
 * `document` at load time (inside functions is fine).
 */
window.VotegaVotesTable = (function () {
  'use strict';

  // Rows shown before the reader asks for more, and how many each ask adds. A
  // member has ~1,100 roll calls in a GA regular session (~5,000 DOM nodes), so
  // the table opens truncated; the step is larger than the opening slice because
  // a 25-row step would take ~44 clicks to reach the end of a session.
  var PAGE_INITIAL = 25;
  var PAGE_STEP    = 100;

  // Resolved per call, never at load time: html-escape.js may not have run yet
  // (and in the test harness it is loaded into the same stub global afterwards).
  // One escaper for the whole site — see html-escape.js for why that matters.
  function esc(value) {
    var g = typeof window !== 'undefined' ? window : {};
    if (g.VoteGA && g.VoteGA.escapeHtml) return g.VoteGA.escapeHtml(value);
    throw new Error('votega-votes-table.js requires html-escape.js (VoteGA.escapeHtml)');
  }

  // Lowercase and drop whitespace AND periods, so neither the query nor the field
  // it is matched against can lose a match to punctuation. Whitespace alone is not
  // enough: GA numbers its bills 'HB 32', but the federal record uses 'H.R. 5334'
  // and 'S.J.Res. 80', so a reader typing 'hr 5334' matched nothing until the dots
  // came out too.
  function normalizeQuery(s) {
    return String(s == null ? '' : s).toLowerCase().replace(/[\s.]+/g, '');
  }

  // The chart's three categories. Everything that is not a cast Yea or Nay —
  // Not Voting, Present, Absent, Excused — is "Other", so a filtered count can
  // be read against the figures above the table.
  function voteBucket(vote) {
    return vote === 'Yea' ? 'yea' : vote === 'Nay' ? 'nay' : 'other';
  }

  function voteClass(vote) {
    return 'vote-' + voteBucket(vote);
  }

  // Parses the components directly rather than handing an ISO string to Date():
  // '2026-01-01' parsed as UTC renders as Dec 31 for anyone west of UTC, which is
  // the bug data-stamp.js documents. Returns the em dash for an absent or
  // malformed value rather than the string "Invalid Date".
  function fmtDate(iso) {
    if (!iso) return '—';
    var parts = String(iso).slice(0, 10).split('-').map(Number);
    var y = parts[0], m = parts[1], d = parts[2];
    if (!y || !m || !d) return '—';
    return new Date(y, m - 1, d).toLocaleDateString('en-US',
      { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // Most recent first. Returns a new array — callers hold the unsorted list.
  function sortByDate(entries, index) {
    index = index || {};
    return entries.slice().sort(function (a, b) {
      var da = (index[a.voteId] || {}).date || '';
      var db = (index[b.voteId] || {}).date || '';
      return db.localeCompare(da);
    });
  }

  // Row predicate for the filter controls. `q` is matched against the bill
  // number, title and motion text together, all normalized the same way.
  function makeMatcher(filter, index) {
    filter = filter || {};
    index = index || {};
    var q = normalizeQuery(filter.q || '');
    var bucket = filter.vote || 'all';
    return function (entry) {
      if (bucket !== 'all' && voteBucket(entry.vote) !== bucket) return false;
      if (!q) return true;
      var meta = index[entry.voteId] || {};
      var hay = (meta.bill || '') + ' ' + (meta.title || '') + ' ' + (meta.motionText || '');
      return normalizeQuery(hay).indexOf(q) !== -1;
    };
  }

  function isFiltered(filter) {
    return !!(filter && ((filter.q && String(filter.q).length) || (filter.vote && filter.vote !== 'all')));
  }

  // How many rows are shown after one more ask. `step` is a row count or 'all'.
  function nextOffset(shown, total, step) {
    if (step === 'all') return total;
    return Math.min(shown + (step || PAGE_STEP), total);
  }

  function rowsHtml(entries, index, opts) {
    index = index || {};
    opts = opts || {};
    var showMotion = opts.showMotion !== false;
    var cell = typeof opts.cell === 'function' ? opts.cell : null;
    // billLink(meta, escapedBillNumber) -> the anchor HTML for the bill number.
    // The default sends the reader to the official record off-site; GA overrides
    // it to point at our own bill page, as its other panels do. The federal page
    // passes nothing and keeps the default.
    var billLinkFn = typeof opts.billLink === 'function' ? opts.billLink : null;
    return entries.map(function (entry) {
      var meta = index[entry.voteId] || {};
      var bill = esc(meta.bill || '—');
      var billLink = billLinkFn
        ? (billLinkFn(meta, bill) || bill)
        : (meta.billUrl
            ? '<a href="' + esc(meta.billUrl) + '" target="_blank" rel="noopener">' + bill + '</a>'
            : bill);
      // Two slots, because the callers decorate different ends of the cell: GA's
      // "[text]" link sits beside the bill number, the federal page's enacted-law
      // line sits below the title.
      var extra = cell ? (cell(meta) || '') : '';
      var after = typeof opts.cellAfter === 'function' ? (opts.cellAfter(meta) || '') : '';
      var billCell = (meta.title
        ? billLink + extra + '<br><span style="font-size:0.75rem;color:#555;font-weight:normal;">' + esc(meta.title) + '</span>'
        : billLink + extra) + after;
      var motionCell = showMotion ? '<td>' + esc(meta.motionText || '—') + '</td>' : '';
      return '<tr>\n'
        + '          <td>' + fmtDate(meta.date) + '</td>\n'
        + '          <td>' + billCell + '</td>\n'
        + '          ' + motionCell + '\n'
        + '          <td class="' + voteClass(entry.vote) + '">' + esc(entry.vote) + '</td>\n'
        + '        </tr>';
    }).join('');
  }

  // `key` identifies the table for the delegated paging handlers: a session id in
  // the GA all-sessions view, the selection otherwise.
  function tableHtml(entries, index, opts) {
    opts = opts || {};
    var shown = opts.shown == null ? entries.length : Math.min(opts.shown, entries.length);
    var motionHeader = opts.showMotion !== false ? '<th>Motion</th>' : '';
    return '\n        <div style="overflow-x:auto;">\n'
        + '        <table class="vote-table"' + (opts.key != null ? ' data-vote-table="' + esc(opts.key) + '"' : '') + '>\n'
        + '          <thead><tr><th>Date</th><th>Bill</th>' + motionHeader + '<th>Vote</th></tr></thead>\n'
        + '          <tbody>' + rowsHtml(entries.slice(0, shown), index, opts) + '</tbody>\n'
        + '        </table>\n'
        + '        </div>';
  }

  function filterRowHtml(opts) {
    opts = opts || {};
    var searchId = opts.searchId || 'voteSearch';
    var voteId = opts.voteId || 'voteResult';
    return '\n          <div class="vote-filter-row">\n'
        + '            <label for="' + esc(searchId) + '">Search</label>\n'
        + '            <input type="search" id="' + esc(searchId) + '" placeholder="' + esc(opts.placeholder || 'Bill number or title') + '" autocomplete="off">\n'
        + '            <label for="' + esc(voteId) + '">Vote</label>\n'
        + '            <select id="' + esc(voteId) + '">\n'
        + '              <option value="all">All</option>\n'
        + '              <option value="yea">Yea</option>\n'
        + '              <option value="nay">Nay</option>\n'
        + '              <option value="other">Other</option>\n'
        + '            </select>\n'
        + '          </div>';
  }

  // The count line under a table, with the two growth controls while rows remain.
  function footHtml(opts) {
    opts = opts || {};
    var total = opts.total || 0;
    if (!total) return '';
    var shown = Math.min(opts.shown == null ? total : opts.shown, total);
    var step = opts.pageStep || PAGE_STEP;
    var noun = 'vote' + (total === 1 ? '' : 's');
    var label = 'Showing ' + shown + ' of ' + total + (opts.filtered ? ' matching ' : ' ') + noun;
    if (shown >= total) return '<div class="vote-page-foot"><span>' + label + '</span></div>';
    var key = esc(opts.key == null ? '' : opts.key);
    return '<div class="vote-page-foot" data-vote-foot="' + key + '">'
        + '<span>' + label + '</span>'
        + '<button type="button" class="vote-page-btn" data-vote-page data-sid="' + key + '" data-step="page">Load ' + Math.min(total - shown, step) + ' more</button>'
        + '<button type="button" class="vote-page-btn" data-vote-page data-sid="' + key + '" data-step="all">Show all ' + total + '</button>'
        + '</div>';
  }

  function noMatchHtml() {
    return '<p class="vote-no-match">No votes match this search.\n'
        + '            <a href="#" data-clear-filters>Clear filters</a></p>';
  }

  // Yea / Nay / Other breakdown as an SVG pie with a legend. Handles the
  // single-slice (100%) case, which an arc path cannot draw.
  // Yea / Nay / Other breakdown as an SVG pie with a legend. The slice colors are
  // the chart's own (#16a34a / #dc2626 / #9ca3af), NOT the .vote-yea/.vote-nay text
  // colors — they are deliberately lighter than the table text.
  function chartHtml(yea, nay, other, total, opts) {
    opts = opts || {};
    if (total === 0) return '';
    var pct = function (n) { return Math.round((n / total) * 100); };

    var size = 88, cx = 44, cy = 44, r = 40;
    var COLORS = { yea: '#16a34a', nay: '#dc2626', other: '#9ca3af' };
    var slices = [
      { label: 'Yea', value: yea, color: COLORS.yea },
      { label: 'Nay', value: nay, color: COLORS.nay },
      { label: 'Other', value: other, color: COLORS.other },
    ].filter(function (s) { return s.value > 0; });

    // A single 100% slice cannot be drawn as an arc (start and end coincide), so
    // it is a plain circle.
    var svgPaths = '';
    if (slices.length === 1) {
      svgPaths = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + slices[0].color + '"/>';
    } else {
      var angle = -Math.PI / 2;
      slices.forEach(function (s) {
        var sweep = (s.value / total) * 2 * Math.PI;
        var end = angle + sweep;
        var x1 = (cx + r * Math.cos(angle)).toFixed(2);
        var y1 = (cy + r * Math.sin(angle)).toFixed(2);
        var x2 = (cx + r * Math.cos(end)).toFixed(2);
        var y2 = (cy + r * Math.sin(end)).toFixed(2);
        svgPaths += '<path d="M' + cx + ',' + cy + 'L' + x1 + ',' + y1
          + 'A' + r + ',' + r + ' 0 ' + (sweep > Math.PI ? 1 : 0) + ',1 ' + x2 + ',' + y2
          + 'Z" fill="' + s.color + '"/>';
        angle = end;
      });
    }

    var legendItems = slices.map(function (s) {
      return '<div style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;">'
        + '        <span style="width:11px;height:11px;border-radius:50%;background:' + s.color + ';flex-shrink:0;display:inline-block;"></span>'
        + '        <span>' + s.label + ': <strong>' + s.value + '</strong> <span style="color:#777;">(' + pct(s.value) + '%)</span></span>'
        + '      </div>';
    }).join('');

    var footnote = other > 0
      ? '<p style="font-size:0.72rem;color:#888;margin:0.5rem 0 0 0;">* Other includes Not Voting, Absent, and Excused</p>'
      : '';

    // The two pages had drifted to two wordings of this caption, identical but for
    // one sentence break. One wording now, overridable per caller.
    var caption = opts.caption == null
      ? "Most bills that reach a floor vote pass, so a chart weighted toward “Yea” is typical here and on other members' pages. It reflects which bills got a recorded vote, not this member's overall independence or party loyalty."
      : opts.caption;

    return '<div>'
        + '      <div style="display:flex;align-items:center;gap:1.25rem;margin:0.75rem 0 0.4rem 0;">'
        + '        <svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '" style="flex-shrink:0;">' + svgPaths + '</svg>'
        + '        <div style="display:flex;flex-direction:column;gap:0.45rem;">' + legendItems + footnote + '</div>'
        + '      </div>'
        + (caption ? '      <p style="font-size:0.72rem;color:#888;margin:0 0 1.25rem 0;max-width:32rem;">' + caption + '</p>' : '')
      + '    </div>';
  }

  // Wires the controls for one panel. Clicks are delegated to `tablesRoot`, so a
  // handler survives that element's innerHTML being re-rendered; the search and
  // select listeners are bound directly and must be re-mounted whenever the page
  // rebuilds the panel around them.
  function mountControls(opts) {
    opts = opts || {};
    var doc = (typeof window !== 'undefined' && window.document) || null;
    if (!doc) return;
    var search = opts.searchId ? doc.getElementById(opts.searchId) : null;
    var voteSel = opts.voteId ? doc.getElementById(opts.voteId) : null;
    var root = typeof opts.tablesRoot === 'string' ? doc.getElementById(opts.tablesRoot) : opts.tablesRoot;
    var debounce = opts.debounceMs == null ? 150 : opts.debounceMs;

    if (search && opts.onFilter) {
      var timer;
      search.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { opts.onFilter({ q: search.value, vote: voteSel ? voteSel.value : 'all' }); }, debounce);
      });
    }
    if (voteSel && opts.onFilter) {
      voteSel.addEventListener('change', function () {
        opts.onFilter({ q: search ? search.value : '', vote: voteSel.value });
      });
    }
    if (root) {
      root.addEventListener('click', function (ev) {
        var clear = ev.target.closest('[data-clear-filters]');
        if (clear) {
          ev.preventDefault();
          if (search) search.value = '';
          if (voteSel) voteSel.value = 'all';
          if (opts.onClear) opts.onClear();
          return;
        }
        var btn = ev.target.closest('[data-vote-page]');
        if (btn && opts.onGrow) opts.onGrow(btn.getAttribute('data-sid'), btn.getAttribute('data-step'));
      });
    }
  }

  return {
    PAGE_INITIAL: PAGE_INITIAL,
    PAGE_STEP: PAGE_STEP,
    normalizeQuery: normalizeQuery,
    voteBucket: voteBucket,
    voteClass: voteClass,
    fmtDate: fmtDate,
    sortByDate: sortByDate,
    makeMatcher: makeMatcher,
    isFiltered: isFiltered,
    nextOffset: nextOffset,
    rowsHtml: rowsHtml,
    tableHtml: tableHtml,
    filterRowHtml: filterRowHtml,
    footHtml: footHtml,
    noMatchHtml: noMatchHtml,
    chartHtml: chartHtml,
    mountControls: mountControls,
  };
})();
