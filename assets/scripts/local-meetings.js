/* Local-government meetings UI for /local/<slug>/ place pages.
 *
 * Renders the Meetings domain of a place: body-filter pills, an Upcoming/Past
 * split, a minutes-available filter, and deep-linkable bodies. Platform-agnostic
 * — it consumes assets/data/local-<slug>-meetings.json, whose schema is identical
 * regardless of the source platform (CivicPlus, CoreCode, …).
 *
 * Runs on the clean /local/<slug>/ entity URL, so it resolves the data file
 * through getBasePath() — a bare-relative fetch would 404 under the entity
 * directory (see CLAUDE.md). Requires html-escape.js (VoteGA.escapeHtml) and,
 * optionally, data-stamp.js (window.dataStamp) already loaded.
 *
 * Usage (from _includes/entity/place.html):
 *   LocalMeetings.init({ slug, placeName, sourceFallback,
 *                        containerId, controlsId, pillsId, minutesToggleId, sourceId });
 */
(function (global) {
  'use strict';

  function getBasePath() {
    return global.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
  }
  function esc(v) { return global.VoteGA.escapeHtml(v); }
  function bodySlug(name) {
    return (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }
  function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtDate(iso) {
    var p = (iso || '').split('-');
    if (p.length !== 3) return iso || '';
    return MONTHS[+p[1] - 1] + ' ' + (+p[2]) + ', ' + p[0];
  }

  function init(opts) {
    var slug = opts.slug;
    var sourceFallback = opts.sourceFallback || '';
    var container = document.getElementById(opts.containerId);
    var controls = document.getElementById(opts.controlsId);
    var pillsEl = document.getElementById(opts.pillsId);
    var minutesToggle = document.getElementById(opts.minutesToggleId);
    var sourceEl = document.getElementById(opts.sourceId);

    var state = { body: 'all', minutesOnly: false };
    var ALL = [];
    var BODIES = [];

    function meetingRow(m, showChip) {
      var links = [
        m.agendaUrl && '<a href="' + esc(m.agendaUrl) + '" target="_blank" rel="noopener">Agenda</a>',
        m.minutesUrl && '<a href="' + esc(m.minutesUrl) + '" target="_blank" rel="noopener">Minutes</a>',
        m.videoUrl && '<a href="' + esc(m.videoUrl) + '" target="_blank" rel="noopener">▶ Video</a>'
      ].filter(Boolean).join('');
      var chip = showChip ? '<span class="cm-body-chip">' + esc(m.body) + '</span>' : '';
      return '<li class="cm-row">' +
        '<span class="cm-date">' + fmtDate(m.date) + '</span>' + chip +
        '<span class="cm-title">' + esc(m.title || m.body || 'Meeting') + '</span>' +
        '<span class="cm-links">' + links + '</span></li>';
    }

    function section(title, rows, showChip, upcoming) {
      if (!rows.length) return '';
      return '<h2 class="cm-section-heading">' + title + ' (' + rows.length + ')</h2>' +
        '<ul class="cm-list ' + (upcoming ? 'cm-upcoming' : '') + '">' +
        rows.map(function (m) { return meetingRow(m, showChip); }).join('') + '</ul>';
    }

    function render() {
      var showChip = state.body === 'all';
      var rows = ALL;
      if (state.body !== 'all') rows = rows.filter(function (m) { return bodySlug(m.body) === state.body; });
      if (state.minutesOnly) rows = rows.filter(function (m) { return m.minutesUrl; });

      Array.prototype.forEach.call(document.querySelectorAll('.cm-pill'), function (p) {
        p.classList.toggle('active', p.dataset.body === state.body);
      });

      if (!rows.length) {
        container.innerHTML = '<p class="cm-empty">' +
          (state.minutesOnly
            ? 'No meetings with published minutes for this selection.'
            : 'No agendas posted.') + '</p>';
        return;
      }

      var today = todayStr();
      var upcoming = rows.filter(function (m) { return m.date >= today; })
        .sort(function (a, b) { return a.date.localeCompare(b.date); });
      var past = rows.filter(function (m) { return m.date < today; })
        .sort(function (a, b) { return b.date.localeCompare(a.date); });

      container.innerHTML =
        section('Upcoming', upcoming, showChip, true) +
        section('Past meetings', past, showChip, false);
    }

    function buildPills() {
      var counts = {};
      ALL.forEach(function (m) { var s = bodySlug(m.body); counts[s] = (counts[s] || 0) + 1; });
      var items = [{ slug: 'all', label: 'All', n: ALL.length }].concat(
        BODIES.map(function (b) { return { slug: bodySlug(b), label: b, n: counts[bodySlug(b)] || 0 }; }));

      pillsEl.innerHTML = items.map(function (it) {
        return '<button class="cm-pill" data-body="' + it.slug + '">' +
          esc(it.label) + ' <span class="cm-count">' + it.n + '</span></button>';
      }).join('');

      Array.prototype.forEach.call(pillsEl.querySelectorAll('.cm-pill'), function (btn) {
        btn.addEventListener('click', function () {
          state.body = btn.dataset.body;
          if (history.replaceState) {
            history.replaceState(null, '',
              state.body === 'all' ? location.pathname + location.search : '#' + state.body);
          }
          render();
        });
      });
    }

    function applyHash() {
      var h = (location.hash || '').replace(/^#/, '');
      if (h && BODIES.some(function (b) { return bodySlug(b) === h; })) state.body = h;
    }

    fetch(getBasePath() + 'assets/data/local-' + slug + '-meetings.json')
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        ALL = data.meetings || [];
        BODIES = data.bodies || [];
        if (!ALL.length) {
          container.innerHTML = '<p class="cm-empty">No agendas posted.</p>';
          return;
        }

        buildPills();
        applyHash();
        if (controls) controls.hidden = false;

        if (minutesToggle) {
          minutesToggle.addEventListener('change', function (e) {
            state.minutesOnly = e.target.checked;
            render();
          });
        }
        global.addEventListener('hashchange', function () { applyHash(); render(); });
        render();

        if (sourceEl) {
          var meta = data.metadata || {};
          var when = meta.generatedAt
            ? (global.dataStamp ? global.dataStamp.formatDate(meta.generatedAt) : meta.generatedAt)
            : null;
          var url = meta.sourceUrl || sourceFallback;
          sourceEl.innerHTML =
            'Aggregated from the ' +
            (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">official ' + esc(opts.placeName || 'source') + ' site</a>' : 'official source') +
            '.' + (when ? ' Updated ' + esc(when) + '.' : '');
        }
      })
      .catch(function (err) {
        if (global.console) console.error(err);
        container.innerHTML =
          '<p style="color:#c00;">Meeting data is temporarily unavailable.' +
          (sourceFallback
            ? ' You can view agendas and minutes directly on the ' +
              '<a href="' + esc(sourceFallback) + '" target="_blank" rel="noopener">official site</a>.'
            : '') + '</p>';
      });
  }

  global.LocalMeetings = { init: init };
})(window);
