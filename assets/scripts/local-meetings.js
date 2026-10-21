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
 *   LocalMeetings.init({ slug, placeName, sourceFallback, botProtected,
 *                        containerId, controlsId, pillsId, minutesToggleId, sourceId });
 *
 * The source line says when the meetings were last checked and the most recent meeting
 * on file, so a resident can tell whether a meeting they expect should be there yet,
 * and flags the place "older than usual" past the local-government window
 * (_data/data_freshness.yml). A bot-protected place (the site cannot be scraped) is
 * flagged regardless of the date, since its data only moves by hand.
 */
(function (global) {
  'use strict';

  function getBasePath() {
    return '/';
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

  var PAGE_SIZE = 50;

  // Year (YYYY) of the newest meeting dated before `today`, or null when the place spans
  // fewer than two years (nothing to narrow) or has no past meetings.
  function defaultYear(meetings, today) {
    today = today || todayStr();
    var years = {}, newest = null;
    (meetings || []).forEach(function (m) {
      var v = m && typeof m.date === 'string' ? m.date.slice(0, 10) : '';
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return;
      years[v.slice(0, 4)] = true;
      if (v < today && (!newest || v > newest)) newest = v;
    });
    if (Object.keys(years).length < 2 || !newest) return null;
    return newest.slice(0, 4);
  }

  function init(opts) {
    var slug = opts.slug;
    var sourceFallback = opts.sourceFallback || '';
    var container = document.getElementById(opts.containerId);
    var controls = document.getElementById(opts.controlsId);
    var pillsEl = document.getElementById(opts.pillsId);
    var yearPillsEl = opts.yearPillsId ? document.getElementById(opts.yearPillsId) : null;
    var yearRowEl = opts.yearRowId ? document.getElementById(opts.yearRowId) : null;
    var minutesToggle = document.getElementById(opts.minutesToggleId);
    var sourceEl = document.getElementById(opts.sourceId);

    // `limit` caps how many past meetings are drawn (a place can have ~800); "Show more"
    // raises it. Any filter change starts over at PAGE_SIZE.
    var state = { body: 'all', year: 'all', minutesOnly: false, limit: PAGE_SIZE };
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

    function section(title, rows, showChip, upcoming, limit) {
      if (!rows.length) return '';
      var shown = limit ? rows.slice(0, limit) : rows;
      var more = rows.length - shown.length;
      return '<h2 class="cm-section-heading">' + title + ' (' + rows.length + ')</h2>' +
        '<ul class="cm-list ' + (upcoming ? 'cm-upcoming' : '') + '">' +
        shown.map(function (m) { return meetingRow(m, showChip); }).join('') + '</ul>' +
        (more > 0
          ? '<button type="button" class="cm-more" id="cmShowMore">Show ' + Math.min(PAGE_SIZE, more) +
            ' more <span class="cm-count">' + more + ' remaining</span></button>'
          : '');
    }

    function render() {
      var showChip = state.body === 'all';
      var rows = ALL;
      if (state.body !== 'all') rows = rows.filter(function (m) { return bodySlug(m.body) === state.body; });
      if (state.minutesOnly) rows = rows.filter(function (m) { return m.minutesUrl; });

      Array.prototype.forEach.call(pillsEl.querySelectorAll('.cm-pill'), function (p) {
        p.classList.toggle('active', p.dataset.body === state.body);
      });
      if (yearPillsEl) {
        Array.prototype.forEach.call(yearPillsEl.querySelectorAll('.cm-pill'), function (p) {
          p.classList.toggle('active', p.dataset.year === state.year);
        });
      }

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
      // The year filter narrows the PAST list only: a meeting scheduled for early next year
      // is still the next one a resident wants, whichever year is selected.
      if (state.year !== 'all') {
        past = past.filter(function (m) { return (m.date || '').slice(0, 4) === state.year; });
      }

      if (!upcoming.length && !past.length) {
        container.innerHTML = '<p class="cm-empty">' +
          (state.minutesOnly
            ? 'No meetings with published minutes for this selection.'
            : 'No agendas posted for this selection.') + '</p>';
        return;
      }

      container.innerHTML =
        section('Upcoming', upcoming, showChip, true, 0) +
        section('Past meetings', past, showChip, false, state.limit);
      var moreBtn = document.getElementById('cmShowMore');
      if (moreBtn) {
        moreBtn.addEventListener('click', function () { state.limit += PAGE_SIZE; render(); });
      }
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
          state.limit = PAGE_SIZE;
          if (history.replaceState) {
            history.replaceState(null, '',
              state.body === 'all' ? location.pathname + location.search : '#' + state.body);
          }
          render();
        });
      });
    }

    function buildYearPills() {
      if (!yearPillsEl) return;
      var counts = {};
      ALL.forEach(function (m) {
        var y = (m.date || '').slice(0, 4);
        if (y) counts[y] = (counts[y] || 0) + 1;
      });
      var years = Object.keys(counts).sort().reverse();
      // Only a useful control when the place spans more than one year.
      if (years.length < 2) { if (yearRowEl) yearRowEl.hidden = true; return; }
      if (yearRowEl) yearRowEl.hidden = false;

      var items = [{ year: 'all', label: 'All', n: ALL.length }].concat(
        years.map(function (y) { return { year: y, label: y, n: counts[y] }; }));
      yearPillsEl.innerHTML = items.map(function (it) {
        return '<button class="cm-pill" data-year="' + it.year + '">' +
          esc(it.label) + ' <span class="cm-count">' + it.n + '</span></button>';
      }).join('');

      Array.prototype.forEach.call(yearPillsEl.querySelectorAll('.cm-pill'), function (btn) {
        btn.addEventListener('click', function () { state.year = btn.dataset.year; state.limit = PAGE_SIZE; render(); });
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
        buildYearPills();
        // A long history opens on the year of the most recent past meeting, not all ~800 rows.
        // "All" is still one click away.
        var yr = defaultYear(ALL);
        if (yearPillsEl && yearRowEl && !yearRowEl.hidden && yr) state.year = yr;
        applyHash();
        if (controls) controls.hidden = false;

        if (minutesToggle) {
          minutesToggle.addEventListener('change', function (e) {
            state.minutesOnly = e.target.checked;
            state.limit = PAGE_SIZE;
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
          var fresh = '';
          var F = global.VotegaFreshness;
          if (when && F) {
            fresh = F.suffix('local-government', meta.generatedAt);
            // A site we cannot scrape never refreshes on its own: flag it outright.
            if (opts.botProtected && fresh.indexOf('stale-flag') === -1) {
              fresh += ' <span class="stale-flag" title="This site blocks automated access, so its meetings are updated by hand."><i class="fa-solid fa-clock-rotate-left" aria-hidden="true"></i> older than usual</span>';
            }
          }
          var latest = latestMeetingDate(ALL);
          sourceEl.innerHTML =
            'Aggregated from the ' +
            (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">official ' + esc(opts.placeName || 'source') + ' site</a>' : 'official source') +
            '.' + (when ? ' Checked ' + esc(when) + fresh + '.' : '') +
            (latest ? ' Most recent meeting on file: ' + esc(global.dataStamp ? global.dataStamp.formatDate(latest) : latest) + '.' : '');
        }
      })
      .catch(function (err) {
        if (global.console) console.error(err);
        container.innerHTML =
          '<p style="color:var(--color-text-secondary);">We’re working to link agendas and minutes to this ' +
          'page for ease of viewing and navigation. You can always view agendas and ' +
          'minutes directly on the ' +
          (sourceFallback
            ? '<a href="' + esc(sourceFallback) + '" target="_blank" rel="noopener">official site</a>'
            : 'official site') +
          '.</p>';
      });
  }

  // Newest meeting dated today or earlier (YYYY-MM-DD), or null. Later dates are scheduled
  // meetings, not ones that have happened, so they do not answer "is the last one here?".
  function latestMeetingDate(meetings) {
    var d = new Date();
    var today = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
    var best = null;
    (meetings || []).forEach(function (m) {
      var v = m && m.date;
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v)) {
        v = v.slice(0, 10);
        if (v <= today && (!best || v > best)) best = v;
      }
    });
    return best;
  }

  global.LocalMeetings = { init: init, latestMeetingDate: latestMeetingDate, defaultYear: defaultYear };
})(window);
