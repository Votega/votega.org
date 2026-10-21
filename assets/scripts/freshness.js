/*
 * freshness.js — the "older than usual" rule for "last updated" stamps.
 *
 * Guide p.17: if a dataset is older than its normal refresh, tint the stamp amber and
 * add "older than usual". The windows live in _data/data_freshness.yml (one place) and
 * reach the page through window.VOTEGA_FRESHNESS, written by _includes/head.html:
 *
 *   { windows: { "<dataset>": { window_days: 10 } | { never: true } },
 *     checked: { "<dataset>": "YYYY-MM-DD" } }
 *
 * A stamp means "the content last changed", not "the job last ran": several generators
 * deliberately keep an unchanged generatedAt so a quiet week commits nothing. That would
 * make a healthy but quiet dataset read as stale, so the workflows also record the day
 * they last checked the source (scripts/record_data_checked.py -> _data/freshness/) and
 * the rule measures from whichever of the two is newer.
 *
 * Datasets marked `never` (hand-maintained, event-driven, or closed) and datasets with no
 * entry are never flagged. Pure functions of their arguments plus the config global, so
 * tests/js/freshness.test.js runs the real file under node.
 */
(function (global) {
  'use strict';

  var DAY = 86400000;

  function config() {
    return global.VOTEGA_FRESHNESS || { windows: {}, checked: {} };
  }

  // Date-only strings are local calendar dates, so a stamp does not read as the
  // previous day west of UTC (same rule as data-stamp.js).
  function parse(value) {
    if (!value) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
    if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
    var d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function fmt(d) {
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  }

  // { tracked, stale, ageDays, windowDays, updated, checked }.
  // `tracked` is false for never-flag datasets and unknown keys; `stale` is only ever
  // true for a tracked dataset whose newest of (stamp, last check) is past its window.
  function status(key, updated, now) {
    var cfgv = config();
    var w = (cfgv.windows || {})[key];
    var out = { tracked: false, stale: false, ageDays: null, windowDays: null, updated: null, checked: null };
    if (!w || w.never || !w.window_days) return out;
    out.tracked = true;
    out.windowDays = w.window_days;
    out.updated = parse(updated);
    out.checked = parse((cfgv.checked || {})[key]);
    var newest = out.updated;
    if (out.checked && (!newest || out.checked > newest)) newest = out.checked;
    if (!newest) return out;                       // nothing to measure: say nothing
    out.ageDays = Math.floor(((now || new Date()) - newest) / DAY);
    out.stale = out.ageDays > w.window_days;
    return out;
  }

  // " · checked October 21, 2026" when the last check is a day or more newer than the
  // stamp, so a quiet dataset's old date is explained rather than left looking neglected.
  function checkedNote(key, updated) {
    var s = status(key, updated);
    if (!s.tracked || !s.checked || !s.updated) return '';
    return (s.checked - s.updated >= DAY) ? ' &middot; checked ' + fmt(s.checked) : '';
  }

  function staleBadge(key, updated, now) {
    var s = status(key, updated, now);
    if (!s.stale) return '';
    var tip = 'Normally refreshed within ' + s.windowDays + ' days; this is ' + s.ageDays + ' days old.';
    return ' <span class="stale-flag" title="' + tip + '">'
      + '<i class="fa-solid fa-clock-rotate-left" aria-hidden="true"></i> older than usual</span>';
  }

  // What a stamp appends after its date: the checked note, then the stale flag.
  function suffix(key, updated, now) {
    return checkedNote(key, updated) + staleBadge(key, updated, now);
  }

  global.VotegaFreshness = {
    status: status, checkedNote: checkedNote, staleBadge: staleBadge, suffix: suffix,
  };
})(window);
