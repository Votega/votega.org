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

  function row(m) {
    var agenda = safeUrl(m.agendaUrl);
    var minutes = safeUrl(m.minutesUrl);
    var title = esc(m.title || 'Meeting');
    var links = [];
    if (agenda) links.push('<a href="' + esc(agenda) + '" target="_blank" rel="noopener">Agenda</a>');
    if (minutes) links.push('<a href="' + esc(minutes) + '" target="_blank" rel="noopener">Minutes</a>');
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

  function render(el, data) {
    var meetings = data && data.meetings;
    if (!meetings || !meetings.length) return false;
    var s = split(meetings, todayStr());
    var src = data.metadata && safeUrl(data.metadata.sourceUrl);
    var html = '<h3 class="sbm-heading">Board meetings</h3>';
    if (s.upcoming.length) {
      html += '<p class="sbm-sub">Upcoming</p><ul class="sbm-list">' + s.upcoming.map(row).join('') + '</ul>';
    }
    if (s.recent.length) {
      html += '<p class="sbm-sub">Recent</p><ul class="sbm-list">' + s.recent.map(row).join('') + '</ul>';
    }
    if (!s.upcoming.length && !s.recent.length) return false;
    var stamp = data.metadata && data.metadata.generatedAt ? fmtDate(data.metadata.generatedAt.slice(0, 10)) : '';
    html += '<p class="sbm-source">' + (stamp ? 'Meetings checked ' + esc(stamp) + '. ' : '') +
      (src ? '<a href="' + esc(src) + '" target="_blank" rel="noopener">All meetings on the board’s site &#8599;</a>' : '') + '</p>';
    el.innerHTML = html;
    el.hidden = false;
    return true;
  }

  function load(el) {
    var id = el.getAttribute('data-sb-meetings');
    if (!id || !/^\d+$/.test(id)) return;
    fetch(getBasePath() + 'assets/data/school-' + id + '-meetings.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) render(el, data); })
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
