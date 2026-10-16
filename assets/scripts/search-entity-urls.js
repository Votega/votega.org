/*
 * search-entity-urls.js — turn the search index's legacy URLs into clean ones.
 *
 * search-entities.json stores each entity's destination as a legacy
 * query-string URL ("ga-member.html?id=ocd-person/…"). That is not an oversight
 * to fix in the generator: scripts/build_entity_pages.py reads the committed
 * index back and recovers each entity's id by parsing that query string
 * (qs_id()), so the shell URL is load-bearing *as data*. Rewriting it to a
 * clean path starves every page builder — measured, 1,393 entity pages became
 * 47 — and the next index run, built off a map that no longer has them, flips
 * it back. So the index keeps the id-bearing URL and the clean path is resolved
 * here, at render time, where the redirect is what actually costs something.
 *
 * What it costs today: those shells are noindex + sitemap:false and exist only
 * to look the id up and location.replace() to the clean URL, so every search
 * click paid for a second navigation — 1,350 of 1,410 records, on the site's
 * main internal discovery path.
 *
 * assets/data/entity-urls.json is a .gitignore'd build artifact written by
 * build_entity_pages.py. When it is missing — a bare checkout, or a deploy
 * where entity generation failed, which deploy-pages.yml explicitly tolerates —
 * every record keeps its shell URL and still works, just with the redirect.
 * Never let a missing map produce a broken href.
 *
 * Shared by _includes/search.html (nav overlay) and search.html (search page),
 * which each had their own copy of the url normalization.
 *
 * Usage:
 *   VoteGA.entityUrls.load(base).then(function (maps) {
 *     records.map(function (r) {
 *       return { …r, url: base + '/' + VoteGA.entityUrls.resolve(r, maps) };
 *     });
 *   });
 */
(function (global) {
  'use strict';

  // Record category -> which map in entity-urls.json holds its ids. Keyed on
  // category rather than merging every map into one flat lookup, so a race id
  // can never resolve against, say, a place slug. Categories absent here
  // ("Local Government", "GA Executive") already ship clean URLs.
  var MAP_FOR_CATEGORY = {
    'GA Legislator': 'ga-legislator',
    'U.S. Congress': 'us-congress',
    'Race': 'race',
    'Candidate': 'candidate',
    'Federal Executive': 'federal-executive',
    'U.S. Supreme Court': 'justice',
  };

  // The id parameters the shells accept, in the order candidate.html's own
  // redirect prefers them: an incumbent with no candidate id of their own is
  // keyed by member id and resolves to their member profile.
  var ID_PARAMS = ['id', 'bioguideId', 'memberId'];

  function idFromUrl(url) {
    var q = String(url || '').indexOf('?');
    if (q < 0) return null;
    var params;
    try {
      params = new URLSearchParams(String(url).slice(q + 1));
    } catch (e) {
      return null;
    }
    for (var i = 0; i < ID_PARAMS.length; i++) {
      var v = params.get(ID_PARAMS[i]);
      if (v) return v;
    }
    return null;
  }

  function load(base) {
    return fetch((base || '') + '/assets/data/entity-urls.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  // Returns a path relative and WITHOUT a leading slash, matching what the
  // index already stores, because both callers build the href as
  // `base + '/' + url`.
  function resolve(rec, maps) {
    var url = (rec && rec.url) || '';
    var kind = MAP_FOR_CATEGORY[rec && rec.category];
    if (!kind || !maps) return url;
    var id = idFromUrl(url);
    if (!id) return url;
    var clean = (maps[kind] || {})[id];
    return clean ? clean.replace(/^\//, '') : url;
  }

  global.VoteGA = global.VoteGA || {};
  global.VoteGA.entityUrls = { load: load, resolve: resolve };
})(window);
