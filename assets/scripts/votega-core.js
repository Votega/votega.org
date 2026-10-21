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

  // Share button for entity pages. VotegaShare.html() returns the markup for a
  // button (entity JS templates are re-rendered with innerHTML, so the click is
  // delegated at the document and survives every re-render). Parameterised on
  // purpose: with no options it shares this page's canonical URL and title; a
  // caller can pass {url, title, text} to share something else (e.g. a bill link).
  // Uses the native share sheet where there is one, else copies the link.
  if (!window.VotegaShare) {
    var _meta = function (sel) {
      var el = document.querySelector(sel);
      return el ? (el.getAttribute('content') || el.getAttribute('href') || '') : '';
    };
    var _canonical = function () {
      var c = _meta('link[rel="canonical"]');
      if (c) return c;
      return window.location.origin + window.location.pathname; // never the query or hash
    };
    var _copy = function (text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
      }
      return new Promise(function (resolve, reject) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
        document.body.appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error('copy failed'));
      });
    };
    var _attr = function (v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); };

    var style = document.createElement('style');
    style.textContent =
      '.vg-share{display:inline-flex;align-items:center;gap:.4rem;margin:.25rem 0;padding:.3rem .8rem;' +
      'font:600 .85rem/1.2 var(--font-sans,inherit);color:var(--color-link);background:var(--color-surface);' +
      'border:1px solid var(--color-border);border-radius:999px;cursor:pointer}' +
      '.vg-share:hover{background:var(--color-surface-sunken)}' +
      '.vg-share:focus-visible{outline:2px solid var(--color-link);outline-offset:2px}';
    (document.head || document.documentElement).appendChild(style);

    window.VotegaShare = {
      // opts: {type, id, url, title, text, label}. type/id feed the share analytics event.
      html: function (opts) {
        opts = opts || {};
        var d = '';
        ['type', 'id', 'url', 'title', 'text'].forEach(function (k) {
          if (opts[k]) d += ' data-share-' + k + '="' + _attr(opts[k]) + '"';
        });
        return '<button type="button" class="vg-share" data-share' + d + '>' +
          '<i class="fa-solid fa-share-nodes" aria-hidden="true"></i>' +
          '<span class="vg-share-label" role="status">' + _attr(opts.label || 'Share') + '</span></button>';
      },
      share: function (btn) {
        var ds = btn.dataset;
        var url = ds.shareUrl || _canonical();
        var title = ds.shareTitle || _meta('meta[property="og:title"]') || document.title;
        var text = ds.shareText || _meta('meta[property="og:description"]') || '';
        var label = btn.querySelector('.vg-share-label');
        var track = function (method) {
          if (window.vgTrack) window.vgTrack('share', { type: ds.shareType || 'page', id: ds.shareId || '', method: method });
        };
        var flash = function (msg) {
          if (!label) return;
          var orig = label.getAttribute('data-orig') || label.textContent;
          label.setAttribute('data-orig', orig);
          label.textContent = msg;
          clearTimeout(btn._vgShareT);
          btn._vgShareT = setTimeout(function () { label.textContent = orig; }, 2200);
        };
        var fallback = function () {
          _copy(url).then(function () { track('copy'); flash('Link copied'); },
                          function () { flash('Copy failed'); });
        };
        if (navigator.share) {
          navigator.share({ url: url, title: title, text: text }).then(function () { track('native'); },
            function (err) { if (!err || err.name !== 'AbortError') fallback(); }); // a cancelled sheet is not an error
        } else {
          fallback();
        }
      },
    };
    document.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('[data-share]') : null;
      if (btn) { e.preventDefault(); window.VotegaShare.share(btn); }
    });
  }
})();
