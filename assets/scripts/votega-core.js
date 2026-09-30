// Shared VoteGA front-end helpers, loaded on every page from _includes/head.html
// (synchronously in <head>, so these are defined before any page's inline code
// runs). Add only tiny, page-agnostic helpers here.
(function () {
  // Base URL prefix for building absolute asset/data paths. The site is served at
  // the domain root (CNAME www.votega.org), so this is always '/'. Kept as a
  // function — the single home for a value that was copy-pasted into ~16 pages and
  // entity includes — so the ~93 call sites and the "resolve through getBasePath"
  // convention keep working, and a non-root deployment could restore the logic here.
  if (typeof window.getBasePath !== 'function') {
    window.getBasePath = function getBasePath() {
      return '/';
    };
  }

  // Portrait cache: swaps government-hosted portrait URLs (congress.gov,
  // legis.ga.gov) for the resized copies we host ourselves, produced by
  // scripts/fetch_candidate_images.py and listed in candidate-image-cache.json.
  // A URL that is not in the manifest (any non-government source, e.g. a campaign
  // site) is returned unchanged and stays hot-linked. See CLAUDE.md.
  //
  // Usage: await VotegaPortraits.load(getBasePath()) once during a page's data
  // load, then VotegaPortraits.src(url) synchronously at render time.
  if (!window.VotegaPortraits) {
    var _map = {};        // original URL -> repo-relative local path
    var _base = '/';
    var _loadPromise = null;

    window.VotegaPortraits = {
      // Fetch the manifest once. Non-fatal: on any failure the map stays empty
      // and src() falls back to the original URLs, so photos still load.
      load: function (basePath) {
        _base = basePath || '/';
        if (_loadPromise) return _loadPromise;
        var url = _base + 'assets/data/candidate-image-cache.json';
        _loadPromise = fetch(url)
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) { if (data && data.images) _map = data.images; })
          .catch(function () { /* keep _map empty; hot-links still work */ });
        return _loadPromise;
      },
      // Return the cached local URL for a portrait, or the original if uncached.
      src: function (url) {
        if (!url) return url;
        var local = _map[url];
        return local ? _base + local.replace(/^\//, '') : url;
      },
    };
  }
})();
