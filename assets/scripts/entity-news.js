/*
 * entity-news.js — shared "In the News" module for VoteGA entity pages.
 *
 * Surfaces a single official's / candidate's tagged news items (from the GA news
 * hub's assets/data/ga-news.json) on their own profile page. Consumed by
 * _includes/entity/{federal-legislator,ga-legislator,candidate}.html.
 *
 * The news file tags items by vgId; entity pages know themselves by bioguideId
 * (federal), ocdPersonId (state) or candidateId (candidate). This module fetches
 * the (small, ~66 KB) news file, reverse-maps the page's id -> vgId via the
 * `entities` map's alt-ids (added by scripts/generate_ga_news.py), and returns
 * that person's items. It is pure — it does NOT touch tabs; each include reveals
 * or removes its own tab/section based on whether items came back.
 *
 * Exposed on window.EntityNews:
 *   load(ids)                      -> Promise<{vgId, name, items}>
 *   renderCards(items, opts)       -> HTML string (opts: {limit, hubHref, name})
 *   hubHref(base, vgId)            -> deep-link to the hub, pre-filtered
 *   basePath()                     -> '/', or '/votega.org-TEST/' on the test path
 */
window.EntityNews = (function () {
  'use strict';

  // Mirrors the getBasePath() helper the entity includes use for their own data.
  // A bare-relative fetch resolves under the entity directory on clean URLs
  // (/us-congress/<slug>/, /ga-legislators/<slug>/) and 404s — see CLAUDE.md.
  function basePath() {
    return window.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
  }

  var NEWS_URL = basePath() + 'assets/data/ga-news.json';

  var TOPIC_LABEL = {
    elections: 'Elections', ethics: 'Ethics', surveillance: 'Surveillance',
    budget: 'Budget', courts: 'Courts', education: 'Education', healthcare: 'Healthcare'
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function hubHref(base, vgId) {
    return base + 'ga-news.html?entity=' + encodeURIComponent(vgId);
  }

  // Cache the fetch so multiple mounts on one page (unlikely, but cheap to guard)
  // don't re-request.
  var _cache = null;
  function fetchNews() {
    if (_cache) return _cache;
    _cache = fetch(NEWS_URL)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .catch(function () { return null; });
    return _cache;
  }

  // Build { anyKnownId -> vgId } from the entities map's alt-ids.
  function reverseIndex(entities) {
    var idx = {};
    Object.keys(entities || {}).forEach(function (vg) {
      var e = entities[vg];
      if (e.bioguideId) idx[e.bioguideId] = vg;
      if (e.ocdPersonId) idx[e.ocdPersonId] = vg;
      (e.candidateIds || []).forEach(function (cid) { idx[cid] = vg; });
    });
    return idx;
  }

  function load(ids) {
    return fetchNews().then(function (data) {
      if (!data || !data.entities) return { vgId: null, name: null, items: [] };
      var idx = reverseIndex(data.entities);
      var vgId = null;
      [ids.bioguideId, ids.ocdPersonId, ids.candidateId].forEach(function (k) {
        if (!vgId && k && idx[k]) vgId = idx[k];
      });
      if (!vgId) return { vgId: null, name: null, items: [] };
      var items = (data.items || []).filter(function (it) {
        return (it.entityIds || []).indexOf(vgId) !== -1;
      });
      return { vgId: vgId, name: (data.entities[vgId] || {}).name || null, items: items };
    });
  }

  function topicTag(t) {
    return '<span class="en-topic">' + esc(TOPIC_LABEL[t] || t) + '</span>';
  }

  function card(it) {
    var topics = (it.topics || []).map(topicTag).join('');
    return '<article class="en-card">' +
      '<div class="en-meta"><span class="en-source">' + esc(it.source) + '</span>' +
      (fmtDate(it.publishedAt) ? '<span class="en-date">' + esc(fmtDate(it.publishedAt)) + '</span>' : '') +
      '</div>' +
      '<a class="en-headline" href="' + esc(it.url) + '" target="_blank" rel="noopener nofollow">' +
      esc(it.title) + '</a>' +
      (it.snippet ? '<p class="en-snippet">' + esc(it.snippet) + '</p>' : '') +
      (topics ? '<div class="en-topics">' + topics + '</div>' : '') +
      '</article>';
  }

  // opts: { limit=8, hubHref, name }
  function renderCards(items, opts) {
    opts = opts || {};
    var limit = opts.limit || 8;
    injectStyles();
    var shown = items.slice(0, limit);
    var html = '<div class="entity-news">' + shown.map(card).join('');
    if (opts.hubHref) {
      var more = items.length > limit ? (' (' + items.length + ' total)') : '';
      html += '<a class="en-seeall" href="' + esc(opts.hubHref) + '">' +
        'See all news about ' + esc(opts.name || 'this person') + more + ' &rarr;</a>';
    }
    html += '</div>';
    return html;
  }

  function injectStyles() {
    if (document.getElementById('entity-news-styles')) return;
    var css =
      '.entity-news{display:flex;flex-direction:column;gap:0}' +
      '.entity-news .en-card{padding:0.85rem 0;border-bottom:1px solid #eef1f5}' +
      '.entity-news .en-card:first-child{padding-top:0}' +
      '.entity-news .en-meta{display:flex;gap:0.5rem;align-items:center;margin-bottom:0.25rem}' +
      '.entity-news .en-source{font-size:0.72rem;font-weight:700;color:#1a2230}' +
      '.entity-news .en-source::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#1d4ed8;margin-right:0.4rem;vertical-align:1px}' +
      '.entity-news .en-date{font-size:0.72rem;color:#8b95a4;font-variant-numeric:tabular-nums}' +
      '.entity-news .en-headline{display:block;font-family:Georgia,"Times New Roman",serif;font-size:1.05rem;font-weight:600;line-height:1.3;color:#1a2230;text-decoration:none}' +
      '.entity-news .en-headline:hover{color:#1d4ed8;text-decoration:underline}' +
      '.entity-news .en-snippet{margin:0.3rem 0 0.4rem;color:#5b6675;font-size:0.85rem;line-height:1.45;max-width:70ch}' +
      '.entity-news .en-topics{display:flex;flex-wrap:wrap;gap:0.3rem}' +
      '.entity-news .en-topic{font-size:0.68rem;font-weight:600;color:#4338ca;border:1px solid rgba(67,56,202,0.35);border-radius:5px;padding:0.1rem 0.4rem}' +
      '.entity-news .en-seeall{display:inline-block;margin-top:0.9rem;font-size:0.85rem;font-weight:600;color:#1d4ed8;text-decoration:none}' +
      '.entity-news .en-seeall:hover{text-decoration:underline}';
    var style = document.createElement('style');
    style.id = 'entity-news-styles';
    style.textContent = css;
    document.head.appendChild(style);
  }

  return { load: load, renderCards: renderCards, hubHref: hubHref, basePath: basePath };
})();
