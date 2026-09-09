/* "On recent agendas" — subject areas + a Data-Center Watch for a /local/<slug>/
 * place page, from the enrichment sidecar local-<slug>-meetings-enriched.json
 * (Legistar places today). Renders nothing when no enriched file exists, so it is
 * safe to call on every place. Base-path aware (see CLAUDE.md); needs
 * html-escape.js (VoteGA.escapeHtml) loaded first.
 *
 *   LocalSubjects.init({ slug, containerId });
 */
(function (global) {
  'use strict';

  function getBasePath() {
    return '/';
  }
  function esc(v) { return global.VoteGA.escapeHtml(v); }

  // Strip the leading "Commission District(s): …" boilerplate Legistar puts on
  // land-use item titles, and collapse whitespace.
  function cleanTitle(t) {
    return (t || '').replace(/^\s*Commission District\(s\):[^A-Za-z]*/i, '').replace(/\s+/g, ' ').trim();
  }

  function chip(label, n) {
    return '<span class="sub-chip">' + esc(label.replace(/-/g, ' ')) +
      ' <span class="sub-n">' + n + '</span></span>';
  }

  // Prettify matched ALPR terms for display: "lpr camera" -> "LPR Camera",
  // "flock" -> "Flock", "safer city" -> "Safer City". LPR/ALPR stay all-caps.
  function prettyTerms(terms) {
    return terms.map(function (term) {
      return term.split(' ').map(function (w) {
        return (w === 'lpr' || w === 'alpr')
          ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1);
      }).join(' ');
    }).join(', ');
  }

  function init(opts) {
    var container = document.getElementById(opts.containerId);
    if (!container) return;

    fetch(getBasePath() + 'assets/data/local-' + opts.slug + '-meetings-enriched.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.summary) return;  // no enriched data for this place — render nothing
        var s = d.summary;
        var html = '';

        // ALPR / surveillance leads, matching the hub badge's prominence. Each
        // citation carries the concrete vendor/capability terms that fired.
        var alpr = s.alprItems || [];
        if (alpr.length) {
          html += '<div class="sub-alpr"><strong>📷 ALPR / surveillance on recent agendas</strong><ul>';
          alpr.slice(0, 6).forEach(function (it) {
            var t = esc(cleanTitle(it.title)).slice(0, 150);
            var terms = (it.terms && it.terms.length)
              ? ' <span class="sub-alpr-terms">(' + esc(prettyTerms(it.terms)) + ')</span>' : '';
            html += '<li>' +
              (it.date ? '<span class="sub-date">' + esc(it.date) + '</span> ' : '') + t + terms +
              (it.sourceUrl ? ' <a href="' + esc(it.sourceUrl) + '" target="_blank" rel="noopener">source ↗</a>' : '') +
              '</li>';
          });
          html += '</ul></div>';
        }

        var dc = s.dataCenterItems || [];
        if (dc.length) {
          html += '<div class="sub-dc"><strong>🏭 Data centers on recent agendas</strong><ul>';
          dc.slice(0, 6).forEach(function (it) {
            var t = esc(cleanTitle(it.title)).slice(0, 150);
            html += '<li>' +
              (it.date ? '<span class="sub-date">' + esc(it.date) + '</span> ' : '') + t +
              (it.sourceUrl ? ' <a href="' + esc(it.sourceUrl) + '" target="_blank" rel="noopener">source ↗</a>' : '') +
              '</li>';
          });
          html += '</ul></div>';
        }

        var lu = s.landUseItems || [];
        if (lu.length) {
          html += '<div class="sub-lu"><strong>🏗️ Land use on recent agendas</strong><ul>';
          lu.slice(0, 6).forEach(function (it) {
            var t = esc(cleanTitle(it.title)).slice(0, 150);
            var tags = (it.tags && it.tags.length)
              ? ' <span class="sub-lu-tags">(' + esc(it.tags.join(', ').replace(/-/g, ' ')) + ')</span>' : '';
            html += '<li>' +
              (it.date ? '<span class="sub-date">' + esc(it.date) + '</span> ' : '') + t + tags +
              (it.sourceUrl ? ' <a href="' + esc(it.sourceUrl) + '" target="_blank" rel="noopener">source ↗</a>' : '') +
              '</li>';
          });
          html += '</ul></div>';
        }

        var totals = s.topicTotals || {};
        var top = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; }).slice(0, 8);
        if (top.length) {
          html += '<div class="sub-chips">' + top.map(function (tg) { return chip(tg, totals[tg]); }).join('') + '</div>';
        }

        if (!html) return;
        container.innerHTML =
          '<h2 class="po-heading" style="margin-top:2rem;">On recent agendas</h2>' +
          '<p class="place-intro">Subjects that appeared on this government’s recent meeting agendas, ' +
          'from the published agenda data. ALPR, data-center, and land-use items link to their source.</p>' + html;
        container.hidden = false;
      })
      .catch(function () { /* no enrichment — leave the section hidden */ });
  }

  global.LocalSubjects = { init: init };
})(window);
