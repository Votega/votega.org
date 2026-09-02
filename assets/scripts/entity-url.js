/*
 * Rewrite legacy per-entity links to their clean URLs.
 *
 * Entity detail pages moved from query-string shells (ga-member.html?id=…,
 * member.html?bioguideId=…, race.html?id=…) to clean paths (/ga-legislators/…,
 * /us-congress/…, /races/…). Many hub pages still build the legacy links in
 * JavaScript; those legacy pages client-redirect to the clean URL, so nothing is
 * broken, but this script skips the redirect hop by rewriting the links in place.
 *
 * It runs site-wide but stays cheap: the id→URL map (assets/data/entity-urls.json)
 * is fetched only once, and only on pages that actually contain a legacy entity
 * link. Ids missing from the map (e.g. candidates, until phase 2) are left alone
 * and continue to work via the redirect.
 */
(function () {
  'use strict';

  var PATTERNS = [
    { type: 'ga-legislator', re: /(?:^|\/)ga-member\.html\?(?:[^#]*&)?id=([^&#]+)/, param: 'id' },
    { type: 'us-congress',   re: /(?:^|\/)member\.html\?(?:[^#]*&)?bioguideId=([^&#]+)/, param: 'bioguideId' },
    { type: 'race',          re: /(?:^|\/)race\.html\?(?:[^#]*&)?id=([^&#]+)/, param: 'id' }
  ];
  var LEGACY_SELECTOR =
    'a[href*="ga-member.html?id="], a[href*="member.html?bioguideId="], a[href*="race.html?id="]';

  var map = null, loading = null;

  function base() {
    return location.pathname.indexOf('/votega.org-TEST/') === 0 ? '/votega.org-TEST' : '';
  }

  function match(href) {
    for (var i = 0; i < PATTERNS.length; i++) {
      var m = href.match(PATTERNS[i].re);
      if (m) {
        var id;
        try { id = decodeURIComponent(m[1]); } catch (e) { id = m[1]; }
        return { type: PATTERNS[i].type, id: id, param: PATTERNS[i].param };
      }
    }
    return null;
  }

  function rewrite(a) {
    var href = a.getAttribute('href');
    if (!href) return;
    var info = match(href);
    if (!info || !map || !map[info.type]) return;
    var clean = map[info.type][info.id];
    if (!clean) return; // unknown id → leave legacy link (redirect handles it)

    var hash = '';
    var hi = href.indexOf('#');
    if (hi >= 0) { hash = href.slice(hi); href = href.slice(0, hi); }
    var q = href.split('?')[1] || '';
    var kept = q.split('&').filter(function (p) {
      return p && p.split('=')[0] !== info.param;
    });
    a.setAttribute('href', base() + clean + (kept.length ? '?' + kept.join('&') : '') + hash);
  }

  function sweep(root) {
    if (!map) return;
    var links = (root || document).querySelectorAll(LEGACY_SELECTOR);
    for (var i = 0; i < links.length; i++) rewrite(links[i]);
  }

  function ensureMap() {
    if (loading) return loading;
    loading = fetch(base() + '/assets/data/entity-urls.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (j) { map = j || {}; sweep(document); })
      .catch(function () { map = {}; });
    return loading;
  }

  function scan(root) {
    var r = root || document;
    if (r.querySelector && r.querySelector(LEGACY_SELECTOR)) {
      ensureMap().then(function () { sweep(r); });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(document); });
  } else {
    scan(document);
  }

  if (window.MutationObserver) {
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var nodes = muts[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          if (nodes[j].nodeType === 1) scan(nodes[j]);
        }
      }
    });
    var start = function () { obs.observe(document.body, { childList: true, subtree: true }); };
    if (document.body) start();
    else document.addEventListener('DOMContentLoaded', start);
  }
})();
