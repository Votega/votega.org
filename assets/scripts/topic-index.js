/* Topic index page — renders the filterable jurisdiction list for
 * /local/topics/<topic>/ from assets/data/local-topics-<topic>.json.
 *
 * No map (that is a later build step); this is the list + filters. Base-path
 * aware (CLAUDE.md); needs html-escape.js (VoteGA.escapeHtml) loaded first.
 *
 *   TopicIndex.init({ topic: 'alpr', name: 'ALPR / surveillance', emoji: '📷' });
 */
(function (global) {
  'use strict';

  function getBasePath() {
    return (typeof global.getBasePath === 'function') ? global.getBasePath() : '/';
  }
  function esc(v) { return global.VoteGA.escapeHtml(v == null ? '' : String(v)); }

  function daysAgoISO(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  }

  // "flock" -> "Flock", "lpr camera" -> "LPR Camera" (matches local-subjects.js).
  function prettyTerm(term) {
    return term.split(' ').map(function (w) {
      return (w === 'lpr' || w === 'alpr' || w === 'slup')
        ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1);
    }).join(' ');
  }

  // Escape the excerpt, then wrap the first case-insensitive occurrence of the
  // matched term in <mark>. Escaping happens BEFORE any markup is inserted, so the
  // term (which came from PDF text) can never inject HTML.
  function highlightExcerpt(excerpt, term) {
    var safe = esc(excerpt);
    if (!term) return safe;
    var safeTerm = esc(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(new RegExp(safeTerm, 'i'), function (m) { return '<mark>' + m + '</mark>'; });
  }

  function qsRead() {
    var p = new URLSearchParams(global.location.search);
    return {
      type: p.get('type') || '',
      region: p.get('region') || '',
      vendor: p.get('vendor') || '',
      confidence: p.get('confidence') || '',
      context: p.get('context') || '',
      since: p.get('since') || '',
      sort: p.get('sort') || 'recent'
    };
  }

  function qsWrite(state) {
    var p = new URLSearchParams();
    Object.keys(state).forEach(function (k) {
      if (state[k] && !(k === 'sort' && state[k] === 'recent')) p.set(k, state[k]);
    });
    var qs = p.toString();
    global.history.replaceState(null, '', qs ? '?' + qs : global.location.pathname);
  }

  function opt(sel, value, label) {
    var o = document.createElement('option');
    o.value = value; o.textContent = label;
    sel.appendChild(o);
  }

  function init(cfg) {
    var listEl = document.getElementById('jurisdiction-list');
    if (!listEl) return;
    var els = {
      stats: document.getElementById('tiStats'),
      count: document.getElementById('tiCount'),
      nothing: document.getElementById('tiNothing'),
      nothingCount: document.getElementById('tiNothingCount'),
      nothingList: document.getElementById('tiNothingList'),
      coverage: document.getElementById('tiCoverage'),
      fallback: document.getElementById('tiFallback'),
      type: document.getElementById('tiType'),
      region: document.getElementById('tiRegion'),
      vendorField: document.getElementById('tiVendorField'),
      vendor: document.getElementById('tiVendor'),
      confidence: document.getElementById('tiConfidence'),
      context: document.getElementById('tiContext'),
      since: document.getElementById('tiSince'),
      sort: document.getElementById('tiSort'),
      csv: document.getElementById('tiCsv')
    };

    fetch(getBasePath() + 'assets/data/local-topics-' + cfg.topic + '.json')
      .then(function (r) { if (!r.ok) throw new Error('fetch failed'); return r.json(); })
      .then(function (data) { render(data); })
      .catch(function () {
        listEl.innerHTML = '';
        if (els.fallback) els.fallback.hidden = false;
      });

    function render(data) {
      var mentions = data.mentions || [];
      var md = data.metadata || {};

      // Region + vendor option lists from the data.
      var regions = {};
      mentions.forEach(function (m) { if (m.region) regions[m.region] = true; });
      Object.keys(regions).sort().forEach(function (r) { opt(els.region, r, r); });

      var vendors = (md.vendors || []).slice();
      if (vendors.length) {
        vendors.forEach(function (v) { opt(els.vendor, v, v); });
        els.vendorField.hidden = false;
      }

      // Stat bar.
      var recent = mentions.filter(function (m) { return m.date && m.date >= daysAgoISO(90); }).length;
      setStat('places', md.placesWithMentions);
      setStat('mentions', mentions.length);
      setStat('vendors', vendors.length);
      setStat('recent', recent);
      if (vendors.length) {
        var vw = els.stats.querySelector('[data-stat-wrap="vendors"]');
        if (vw) vw.hidden = false;
      }
      els.stats.hidden = false;

      // Coverage footer. Break the scanned count into counties and cities so
      // the ~537-city universe doesn't read as "we scan every city." Prefer the
      // counts the generator emits; fall back to deriving them from the data
      // (unique scanned places = mentions ∪ coveredNoMention, keyed by placeId).
      var countiesScanned = md.countiesScanned;
      var citiesScanned = md.citiesScanned;
      if (countiesScanned == null || citiesScanned == null) {
        var typeById = {};
        mentions.forEach(function (m) { if (m.placeId) typeById[m.placeId] = m.placeType; });
        (data.coveredNoMention || []).forEach(function (p) {
          if (p.placeId && !(p.placeId in typeById)) typeById[p.placeId] = p.placeType;
        });
        countiesScanned = 0;
        citiesScanned = 0;
        Object.keys(typeById).forEach(function (id) {
          if (typeById[id] === 'city') { citiesScanned++; } else { countiesScanned++; }
        });
      }
      els.coverage.innerHTML = 'Scanning ' + countiesScanned + ' of Georgia’s ' +
        (md.universeCounties || 0) + ' counties and ' + citiesScanned + ' of ~' +
        (md.universeCities || 0) + ' cities. ' +
        (md.generatedAt ? 'Last scan ' + esc(md.generatedAt.slice(0, 10)) + '. ' : '') +
        'Only jurisdictions with an automated agenda feed are scanned; a place we don’t yet cover is absent, not “nothing found.”';

      // Nothing-found list.
      var none = data.coveredNoMention || [];
      if (none.length) {
        els.nothingCount.textContent = none.length;
        els.nothingList.innerHTML = none.map(function (p) {
          return '<li><a href="' + getBasePath() + 'local/' + esc(p.placeId) + '/">' +
            esc(p.placeName) + '</a></li>';
        }).join('');
        els.nothing.hidden = false;
      }

      var state = qsRead();
      // Reflect query string into the controls.
      els.type.value = state.type;
      els.region.value = state.region;
      if (vendors.length) els.vendor.value = state.vendor;
      els.confidence.value = state.confidence;
      els.context.value = state.context;
      els.since.value = state.since;
      els.sort.value = state.sort;

      function current() {
        return {
          type: els.type.value, region: els.region.value,
          vendor: vendors.length ? els.vendor.value : '',
          confidence: els.confidence.value, context: els.context.value,
          since: els.since.value, sort: els.sort.value
        };
      }

      function filtered() {
        var s = current();
        var cutoff = s.since ? daysAgoISO(parseInt(s.since, 10)) : null;
        var rows = mentions.filter(function (m) {
          if (s.type && m.placeType !== s.type) return false;
          if (s.region && m.region !== s.region) return false;
          if (s.vendor && (m.vendors || []).indexOf(s.vendor) === -1) return false;
          if (s.confidence && m.confidence !== s.confidence) return false;
          if (s.context && m.context !== s.context) return false;
          if (cutoff && (!m.date || m.date < cutoff)) return false;
          return true;
        });
        if (s.sort === 'place') {
          rows.sort(function (a, b) {
            return a.placeName.localeCompare(b.placeName) || (b.date || '').localeCompare(a.date || '');
          });
        } else {
          rows.sort(function (a, b) {
            return (b.date || '').localeCompare(a.date || '') || a.placeName.localeCompare(b.placeName);
          });
        }
        return rows;
      }

      // Roll the flat mention rows up into one group per place, and within a place
      // one entry per MEETING (keyed on date+body, so two documents for the same
      // meeting collapse while a same-day work session vs board meeting stay
      // separate). Each meeting keeps its unique block quotes and source links.
      function groupRows(rows) {
        var byPlace = {};
        rows.forEach(function (m) {
          var g = byPlace[m.placeId] || (byPlace[m.placeId] = {
            placeId: m.placeId, placeName: m.placeName, placeType: m.placeType,
            region: m.region, vendors: {}, meetings: {}, latest: '', count: 0
          });
          g.count++;
          (m.vendors || []).forEach(function (v) { g.vendors[v] = true; });
          if ((m.date || '') > g.latest) g.latest = m.date || '';
          var key = (m.date || '') + '|' + (m.body || '');
          var mt = g.meetings[key] || (g.meetings[key] = {
            date: m.date, body: m.body, confidence: 'medium', context: null,
            tags: {}, terms: {}, excerpts: [], sources: {}
          });
          if (m.confidence === 'high') mt.confidence = 'high';
          // Context precedence: agenda-action > public-comment > unknown.
          if (m.context === 'agenda-action') mt.context = 'agenda-action';
          else if (m.context === 'public-comment' && mt.context !== 'agenda-action') mt.context = 'public-comment';
          else if (!mt.context && m.context) mt.context = m.context;
          (m.tags || []).forEach(function (t) { mt.tags[t] = true; });
          (m.terms || []).forEach(function (t) { mt.terms[t] = true; });
          (m.sourceUrl ? [m.sourceUrl] : []).forEach(function (u) { mt.sources[u] = true; });
          // Quote only government business (agenda-action) — matching the open
          // dataset's policy. Public-comment / unknown excerpts can name private
          // residents from sign-up rosters, so their verbatim quote is withheld;
          // the matched term, context chip, and source link below still render, so
          // voters still see WHAT surfaced and can open the source to read it.
          if (m.context === 'agenda-action' && m.excerpt &&
              !mt.excerpts.some(function (e) { return e.excerpt === m.excerpt; })) {
            mt.excerpts.push({ excerpt: m.excerpt, term: m.excerptTerm });
          }
        });
        return byPlace;
      }

      function meetingHtml(mt) {
        var confBadge = '';
        if (cfg.topic === 'alpr') {  // confidence only varies for ALPR
          var cls = mt.confidence === 'high' ? 'ti-conf-high' : 'ti-conf-med';
          var lbl = mt.confidence === 'high' ? 'Vendor-named / explicit' : 'Keyword only';
          confBadge = ' <span class="ti-badge ' + cls + '" title="' + esc(lbl) + '">' + esc(lbl) + '</span>';
        }
        var ctxBadge = '';
        if (mt.context === 'agenda-action') {
          ctxBadge = ' <span class="ti-badge ti-ctx-action" title="Came up as government business — an item, motion, resolution, or public hearing">Agenda item</span>';
        } else if (mt.context === 'public-comment') {
          ctxBadge = ' <span class="ti-badge ti-ctx-comment" title="Raised during public comment / citizen sign-up — not a government action">Public comment</span>';
        }
        var chips = Object.keys(mt.tags).map(function (t) { return t.replace(/-/g, ' '); });
        var evidence = Object.keys(mt.terms).map(prettyTerm).join(', ');
        var srcs = Object.keys(mt.sources);
        var srcHtml = srcs.length ? '<div class="ti-src">' + srcs.map(function (u, i) {
          var label = srcs.length > 1 ? 'Document ' + (i + 1) : 'Open agenda / minutes';
          return '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + label + ' ↗</a>';
        }).join(' · ') + '</div>' : '';
        return '<li class="ti-meeting">' +
          '<div class="ti-row-meta">' +
            (mt.date ? '<span class="ti-date">' + esc(mt.date) + '</span>' : '') +
            (mt.body ? ' <span class="ti-body">' + esc(mt.body) + '</span>' : '') +
            ctxBadge + confBadge +
          '</div>' +
          (chips.length ? '<div class="ti-tags">' + chips.map(function (v) {
            return '<span class="ti-tag">' + esc(v) + '</span>'; }).join('') + '</div>' : '') +
          mt.excerpts.map(function (e) {
            return '<blockquote class="ti-excerpt">' + highlightExcerpt(e.excerpt, e.term) + '</blockquote>';
          }).join('') +
          (evidence ? '<div class="ti-evidence">Matched: ' + esc(evidence) + '</div>' : '') +
          srcHtml +
        '</li>';
      }

      function groupHtml(g) {
        var meetings = Object.keys(g.meetings).map(function (k) { return g.meetings[k]; });
        meetings.sort(function (a, b) {
          return (b.date || '').localeCompare(a.date || '') || (a.body || '').localeCompare(b.body || '');
        });
        var vend = Object.keys(g.vendors).sort();
        var n = meetings.length;
        return '<li class="ti-group"><details>' +
          '<summary class="ti-group-head">' +
            '<span class="ti-place">' + esc(g.placeName) + '</span>' +
            '<span class="ti-badge ti-badge-type">' + esc(g.placeType) + '</span>' +
            '<span class="ti-group-count">' + n + (n === 1 ? ' meeting' : ' meetings') + '</span>' +
            (g.latest ? '<span class="ti-group-latest">latest ' + esc(g.latest) + '</span>' : '') +
            (g.region ? '<span class="ti-region">' + esc(g.region) + '</span>' : '') +
            (vend.length ? '<span class="ti-group-vendors">' + vend.map(function (v) {
              return '<span class="ti-tag">' + esc(v) + '</span>'; }).join('') + '</span>' : '') +
          '</summary>' +
          '<ul class="ti-meetings">' + meetings.map(meetingHtml).join('') + '</ul>' +
          '<div class="ti-group-link"><a href="' + getBasePath() + 'local/' + esc(g.placeId) +
            '/">View ' + esc(g.placeName) + ' &rarr;</a></div>' +
        '</details></li>';
      }

      function draw() {
        var rows = filtered();
        qsWrite(current());
        var groups = groupRows(rows);
        var ids = Object.keys(groups);
        var s = current();
        ids.sort(function (a, b) {
          if (s.sort === 'place') return groups[a].placeName.localeCompare(groups[b].placeName);
          return (groups[b].latest || '').localeCompare(groups[a].latest || '') ||
                 groups[a].placeName.localeCompare(groups[b].placeName);
        });
        els.count.innerHTML = rows.length + (rows.length === 1 ? ' mention' : ' mentions') +
          ' across ' + ids.length + ' jurisdiction' + (ids.length === 1 ? '' : 's') +
          (rows.length === mentions.length ? '' : ' (of ' + mentions.length + ')') +
          (ids.length ? ' &nbsp;<button type="button" class="ti-linkbtn" data-toggle="expand">Expand all</button>' +
            ' · <button type="button" class="ti-linkbtn" data-toggle="collapse">Collapse all</button>' : '');
        if (!rows.length) {
          listEl.innerHTML = '<li class="ti-empty">No mentions match these filters.</li>';
          return;
        }
        listEl.innerHTML = ids.map(function (id) { return groupHtml(groups[id]); }).join('');
      }

      // Expand / collapse all (event-delegated, since the buttons are re-rendered).
      els.count.addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('[data-toggle]') : null;
        if (!b) return;
        var open = b.getAttribute('data-toggle') === 'expand';
        Array.prototype.forEach.call(listEl.querySelectorAll('details'), function (d) { d.open = open; });
      });

      [els.type, els.region, els.vendor, els.confidence, els.context, els.since, els.sort]
        .forEach(function (c) { if (c) c.addEventListener('change', draw); });

      if (els.csv) els.csv.addEventListener('click', function () { exportCsv(filtered(), cfg.topic); });

      draw();
    }

    function setStat(name, val) {
      var el = els.stats.querySelector('[data-stat="' + name + '"]');
      if (el) el.textContent = (val == null ? 0 : val);
    }
  }

  function csvCell(v) {
    var s = (v == null ? '' : String(v));
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function exportCsv(rows, topic) {
    var cols = ['placeId', 'placeName', 'placeType', 'region', 'date', 'body',
      'confidence', 'context', 'vendors', 'terms', 'tags', 'excerpt', 'sourceUrl'];
    var lines = [cols.join(',')];
    rows.forEach(function (r) {
      lines.push(cols.map(function (c) {
        var v = r[c];
        if (Array.isArray(v)) v = v.join('; ');
        return csvCell(v);
      }).join(','));
    });
    var blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'votega-' + topic + '-mentions.csv';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  }

  global.TopicIndex = { init: init };
})(window);
