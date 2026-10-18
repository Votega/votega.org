/*
 * zip-districts.js — a bare ZIP, answered from assets/data/ga-zip-districts.json.
 *
 * Find My Reps and the candidate finder both let a voter type a ZIP instead of
 * an address. What a ZIP can tell you is "the districts touching it", never "your
 * district", and the wording, the sort order and the never-hide-a-district rule
 * have to be the same on both pages -- so the table's load, its expansion and the
 * share label live here once, and each page keeps only what it does with the
 * result.
 *
 * No `document` at load or inside, and no page state: fetch is injectable, so
 * this is exercised under tests/js/load-browser-module.js. See
 * tests/js/zip-districts.test.js.
 */
'use strict';

(function () {
  var TABLE_PATH = 'assets/data/ga-zip-districts.json';
  var CHAMBERS = ['usHouse', 'stateSenate', 'stateHouse'];

  // A district's weight in a ZIP, as the voter should read it. The row is always
  // listed; this only changes the wording. Under 5% it is "a small part" because
  // a rounded 1% reads as noise, not because the district is dropped. A share of
  // exactly 1 is the whole ZIP, which "about 100%" would understate.
  var SMALL_SHARE = 0.05;
  function shareLabel(share) {
    if (typeof share !== 'number' || !isFinite(share)) return null;
    if (share >= 1) return 'all of this ZIP';
    if (share >= SMALL_SHARE) return 'about ' + Math.round(share * 100) + '% of this ZIP';
    return 'a small part of this ZIP';
  }

  /**
   * One table entry (zips[zip]) -> { city, counties[], usHouse[], stateSenate[],
   * stateHouse[], shares }, `shares` being chamber -> district -> share. Districts
   * are sorted ascending (the file ranks by share) and none are dropped. Null
   * when there is nothing to list: no entry, a po-box ZIP, or no districts.
   * A kind of 'other' (campus/government/military) is treated like 'standard'.
   */
  function expand(entry) {
    if (!entry || entry.kind === 'po-box') return null;
    var shares = { usHouse: {}, stateSenate: {}, stateHouse: {} };
    var out = {
      city: entry.city || null,
      counties: (entry.counties || []).map(function (c) { return c.name; }),
      shares: shares,
    };
    var any = false;
    CHAMBERS.forEach(function (key) {
      var rows = entry[key] || [];
      rows.forEach(function (r) { shares[key][r.district] = r.share; });
      out[key] = rows.map(function (r) { return r.district; })
        .sort(function (a, b) { return a - b; });
      if (out[key].length) any = true;
    });
    return any ? out : null;
  }

  /**
   * Look a ZIP up in a loaded table. Always an answer, never a throw:
   *   { status: 'ok', ...expand() } | { status: 'unknown' } | { status: 'no-districts' }
   * 'unknown' is a ZIP not in the file; 'no-districts' is a po-box ZIP (or an
   * entry with none), which the caller sends to the county picker / an address.
   */
  function lookup(zip, table) {
    var entry = table && table.zips && table.zips[zip];
    if (!entry) return { status: 'unknown' };
    var e = expand(entry);
    if (!e) return { status: 'no-districts' };
    e.status = 'ok';
    return e;
  }

  var pending = null;
  /**
   * The table, fetched lazily and once per page. `basePath` must come from the
   * page's getBasePath(): a bare-relative URL 404s on clean entity paths. A
   * failure is not remembered, so a retry can succeed.
   */
  function load(basePath, fetchFn) {
    if (!pending) {
      var f = fetchFn || (typeof fetch === 'function' ? fetch : null);
      if (!f) return Promise.reject(new Error('ZIP data unavailable'));
      pending = Promise.resolve(f(basePath + TABLE_PATH)).then(function (r) {
        if (!r.ok) throw new Error('Data file unavailable: ' + TABLE_PATH);
        return r.json();
      }).catch(function (err) { pending = null; throw err; });
    }
    return pending;
  }

  var ZipDistricts = {
    shareLabel: shareLabel,
    expand: expand,
    lookup: lookup,
    load: load,
    TABLE_PATH: TABLE_PATH,
    SMALL_SHARE: SMALL_SHARE,
  };

  if (typeof window !== 'undefined') window.ZipDistricts = ZipDistricts;
  if (typeof module !== 'undefined' && module.exports) module.exports = ZipDistricts;
})();
