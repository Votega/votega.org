// voter-location.js
// Per-tab persistence of a resolved voter location so an address lookup on one page
// (e.g. the sample ballot) carries over to another (e.g. the elections/candidates
// finder) within the same visit.
//
// sessionStorage is the deliberate scope: it lives only in the current browser tab,
// is wiped when the tab closes, and never leaves the browser. We persist ONLY the
// derived county + district numbers — never the raw street address — to keep the
// site's promise that addresses aren't stored.
//
// Shape saved/returned:
//   { source, county, usHouse, stateHouse, stateSenate, savedAt }
// `source` is 'address' (exact districts) or 'county' (districts null → overlap view).
(function () {
  'use strict';
  const KEY = 'votega.voterLocation';

  function save(loc) {
    if (!loc) return;
    try {
      sessionStorage.setItem(KEY, JSON.stringify({
        source: loc.source || null,
        county: loc.county || null,
        usHouse: loc.usHouse ?? null,
        stateHouse: loc.stateHouse ?? null,
        stateSenate: loc.stateSenate ?? null,
        savedAt: Date.now(),
      }));
    } catch (_) { /* storage unavailable (private mode / quota) — skip silently */ }
  }

  function load() {
    try {
      const loc = JSON.parse(sessionStorage.getItem(KEY) || 'null');
      return loc && typeof loc === 'object' ? loc : null;
    } catch (_) { return null; }
  }

  function clear() {
    try { sessionStorage.removeItem(KEY); } catch (_) { /* ignore */ }
  }

  window.VoterLocation = { save, load, clear };
})();
