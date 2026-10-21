/*
 * entity-urls.js — resolve an entity id to its clean URL, with a shell fallback.
 *
 * The site's entities live at clean paths (/ga-legislators/<slug>/,
 * /races/<slug>/, /candidates/<slug>/ …) built by build_entity_pages.py, but a
 * lot of pages still render links to the legacy query-string shells that
 * predate them — ga-member.html?id=, race.html?id=, candidate.html?id=,
 * member.html?bioguideId=. Those shells are noindex + sitemap:false and exist
 * only to look the id up and location.replace() to the clean path, so every one
 * of those links costs the reader a second navigation and a blank flash. This
 * module is how a page renders the clean link directly.
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
 * Usage — load once per page, in parallel with whatever data you already fetch,
 * then resolve each link with the shell URL you would otherwise have emitted:
 *
 *   var maps = await VoteGA.entityUrls.load(basePath);
 *   var href = VoteGA.entityUrls.href(maps, 'ga-legislator', m.id,
 *                basePath + 'ga-member.html?id=' + encodeURIComponent(m.id));
 *
 * `kind` is a key of entity-urls.json: ga-legislator, us-congress, race,
 * candidate, federal-executive, justice, place. resolve() is the search-index
 * wrapper on top of href(), which picks the kind from a record's category.
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

  var inflight = null;
  var cached = null;

  // Memoized per page: several components on one page (a member list and a
  // race list, say) each call load() and share the single fetch.
  function load(base) {
    if (!inflight) {
      // Normalize the prefix rather than trusting the caller: site.baseurl is
      // '' while getBasePath() returns '/', and the naive concatenation turned
      // the latter into '//assets/data/entity-urls.json' -- protocol-relative,
      // so the browser resolved it against the host "assets" and the fetch
      // failed. That failure is indistinguishable from a missing map, so every
      // link silently kept its shell URL and the whole module looked inert.
      var prefix = String(base == null ? '' : base).replace(/\/+$/, '');
      inflight = fetch(prefix + '/assets/data/entity-urls.json')
        .then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; })
        .then(function (maps) { cached = maps; return maps; });
    }
    return inflight;
  }

  // href() against the maps load() cached, so a render function deep in a page
  // does not have to thread `maps` through every call. Await load() before
  // rendering: until it resolves this returns the fallback, which is correct
  // but costs the redirect this module exists to remove.
  function get(kind, id, fallback) {
    return href(cached, kind, id, fallback);
  }

  // The general resolver. `fallback` is the legacy shell URL the caller would
  // have emitted; it is returned whenever the clean path cannot be had, which
  // is a real state and not an edge case -- see the note above about the map
  // being a .gitignore'd build artifact.
  function href(maps, kind, id, fallback) {
    if (!maps || !kind || !id) return fallback;
    var clean = (maps[kind] || {})[id];
    return clean || fallback;
  }

  // Returns a path relative and WITHOUT a leading slash, matching what the
  // index already stores, because both callers build the href as
  // `base + '/' + url`.
  function resolve(rec, maps) {
    var url = (rec && rec.url) || '';
    var kind = MAP_FOR_CATEGORY[rec && rec.category];
    var id = kind ? idFromUrl(url) : null;
    var clean = href(maps, kind, id, null);
    return clean ? clean.replace(/^\//, '') : url;
  }

  // True for a search record whose page is retired (build_entity_pages.py lists those ids
  // under "retired" in entity-urls.json: a candidate not on the race's current ballot).
  // The index itself must keep them -- the page builders read it back (see the note at the
  // top) -- so search hides them here instead. A missing map hides nothing.
  function isRetired(rec, maps) {
    var kind = MAP_FOR_CATEGORY[rec && rec.category];
    var id = kind ? idFromUrl((rec && rec.url) || '') : null;
    var set = maps && maps.retired && maps.retired[kind];
    return !!(id && set && set[id]);
  }

  global.VoteGA = global.VoteGA || {};
  global.VoteGA.entityUrls = { load: load, href: href, get: get, resolve: resolve, isRetired: isRetired };
})(window);
