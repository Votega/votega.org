/* School-board meetings for the board panels on /local/<slug>/ (phase 3e).
 *
 * Progressive enhancement: every <div data-sb-meetings="<GOSA district id>"> emitted
 * by _includes/entity/school-boards.html is filled from
 * assets/data/school-<id>-meetings.json (scripts/generate_school_meetings.py).
 * The panel stays hidden until that file exists and holds meetings, so a district
 * with no meetings source, or one the generator has not produced yet, shows nothing
 * rather than an error. Same schema as local-<slug>-meetings.json.
 *
 * Resolves the data file through getBasePath(): on the clean /local/<slug>/ URL a
 * bare-relative fetch would 404 under the entity directory (see CLAUDE.md).
 */
(function (global) {
  'use strict';

  var UPCOMING_MAX = 5;
  var RECENT_MAX = 8;
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function getBasePath() { return '/'; }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function fmtDate(iso) {
    var p = (iso || '').split('-');
    if (p.length !== 3) return iso || '';
    return MONTHS[+p[1] - 1] + ' ' + (+p[2]) + ', ' + p[0];
  }

  // Only ever link to the platform's own host; the data file is ours, but a link is
  // a link and this keeps a malformed row from producing a javascript: href.
  function safeUrl(u) {
    return typeof u === 'string' && /^https:\/\//i.test(u) ? u : null;
  }

  // Georgia Commons summary pages, keyed by the Simbli meeting id we already hold
  // (scripts/generate_georgia_commons_links.py). Only their own host is linked.
  var GC_HOST = /^https:\/\/georgiacommons\.org\//;
  var GC_LABEL = 'AI-written summary from Georgia Commons, based on the posted minutes';

  function gcUrl(m, gc) {
    var hit = gc && m && m.id != null ? gc[String(m.id)] : null;
    return hit && typeof hit.url === 'string' && GC_HOST.test(hit.url) ? hit.url : null;
  }

  function row(m, gc) {
    var agenda = safeUrl(m.agendaUrl);
    var minutes = safeUrl(m.minutesUrl);
    var summary = gcUrl(m, gc);
    var title = esc(m.title || 'Meeting');
    var links = [];
    if (agenda) links.push('<a href="' + esc(agenda) + '" target="_blank" rel="noopener">Agenda</a>');
    if (minutes) links.push('<a href="' + esc(minutes) + '" target="_blank" rel="noopener">Minutes</a>');
    if (summary) {
      links.push('<a class="sbm-gc" href="' + esc(summary) + '" target="_blank" rel="noopener" title="' +
        esc(GC_LABEL) + '" aria-label="' + esc(GC_LABEL + ' (opens in a new tab)') +
        '">Summary <span class="sbm-ai">(AI)</span> &#8599;</a>');
    }
    return '<li class="sbm-row"><span class="sbm-date">' + esc(fmtDate(m.date)) +
      (m.time ? ' <span class="sbm-time">' + esc(m.time) + '</span>' : '') + '</span>' +
      '<span class="sbm-title">' + title + '</span>' +
      '<span class="sbm-links">' + (links.length ? links.join(' &middot; ') :
        '<span class="sbm-none">No documents posted</span>') + '</span></li>';
  }

  // Newest first in the file. Upcoming is shown soonest first; past is newest first.
  function split(meetings, today) {
    var up = [], past = [];
    (meetings || []).forEach(function (m) {
      if (!m || typeof m.date !== 'string') return;
      (m.date >= today ? up : past).push(m);
    });
    up.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    return { upcoming: up.slice(0, UPCOMING_MAX), recent: past.slice(0, RECENT_MAX) };
  }

  // gc: {<meeting id>: {url, date}} for this district, or null.
  function render(el, data, gc) {
    var meetings = data && data.meetings;
    if (!meetings || !meetings.length) return false;
    var s = split(meetings, todayStr());
    var src = data.metadata && safeUrl(data.metadata.sourceUrl);
    var toRow = function (m) { return row(m, gc); };
    var html = '<h3 class="sbm-heading">Board meetings</h3>';
    if (s.upcoming.length) {
      html += '<p class="sbm-sub">Upcoming</p><ul class="sbm-list">' + s.upcoming.map(toRow).join('') + '</ul>';
    }
    if (s.recent.length) {
      html += '<p class="sbm-sub">Recent</p><ul class="sbm-list">' + s.recent.map(toRow).join('') + '</ul>';
    }
    if (!s.upcoming.length && !s.recent.length) return false;
    var anySummary = s.recent.concat(s.upcoming).some(function (m) { return !!gcUrl(m, gc); });
    var stamp = data.metadata && data.metadata.generatedAt ? fmtDate(data.metadata.generatedAt.slice(0, 10)) : '';
    html += '<p class="sbm-source">' + (stamp ? 'Meetings checked ' + esc(stamp) + '. ' : '') +
      (src ? '<a href="' + esc(src) + '" target="_blank" rel="noopener">All meetings on the board’s site &#8599;</a>' : '') + '</p>';
    if (anySummary) {
      html += '<p class="sbm-source">Summaries are AI-written by <a href="https://georgiacommons.org/" ' +
        'target="_blank" rel="noopener">Georgia Commons</a> from the minutes the board posted, and can be wrong; ' +
        'they appear once a board posts its minutes. Check the minutes for the official record.</p>';
    }
    el.innerHTML = html;
    el.hidden = false;
    return true;
  }

  // One fetch per page however many board panels it has. A missing or broken sidecar
  // only means no summary links; it never blocks the meetings themselves.
  var gcPromise = null;
  function loadGc() {
    if (!gcPromise) {
      gcPromise = fetch(getBasePath() + 'assets/data/georgia-commons-meetings.json')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { return (d && d.districts) || {}; })
        .catch(function () { return {}; });
    }
    return gcPromise;
  }

  function load(el) {
    var id = el.getAttribute('data-sb-meetings');
    if (!id || !/^\d+$/.test(id)) return;
    var meetings = fetch(getBasePath() + 'assets/data/school-' + id + '-meetings.json')
      .then(function (r) { return r.ok ? r.json() : null; });
    Promise.all([meetings, loadGc()])
      .then(function (res) { if (res[0]) render(el, res[0], res[1][id] || null); })
      .catch(function () { /* no data yet: the panel stays hidden */ });
  }

  function init() {
    var els = document.querySelectorAll('[data-sb-meetings]');
    for (var i = 0; i < els.length; i++) load(els[i]);
  }

  global.SchoolBoardMeetings = { init: init, split: split, render: render, safeUrl: safeUrl };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
