/*
 * address-lookup.js — the chrome around a Census address lookup.
 *
 * Four pages ask a voter for an address and hand it to
 * SampleBallot.geocodeAddress: the sample ballot, find-my-reps, elections and
 * federal-reps. The geocoder itself was already shared; everything wrapped
 * around it was copied, and the copies drifted. Two of the four shipped without
 * the ZIP guard, two without an outcome event, one without a privacy note. The
 * drift is not hypothetical — the federal-reps copy was written by someone
 * reading the others and still missed two of them.
 *
 * What belongs here is the part that must never vary by page: refuse a bare ZIP
 * without calling the geocoder, hold a busy latch so a double-click cannot fire
 * two lookups, surface the geocoder's own error text, persist only the derived
 * districts, and report an outcome enum. What stays with the page is everything
 * downstream of a resolved location — each page does something completely
 * different with it — plus the copy that names a page-specific control.
 *
 * That last point is why `fallbackPhrase` is configuration rather than a
 * constant. "pick your county above" and "use the county filter below" are not
 * drift: they describe where that page's fallback control actually sits, and
 * unifying them would point voters at the wrong place.
 *
 * No `document` at load time and none inside either: the page passes its
 * elements in, so this module is exercised under tests/js/load-browser-module.js
 * against plain objects, with no DOM and no dependency tree. See
 * tests/js/address-lookup.test.js.
 */
'use strict';

(function () {
  // A ZIP alone cannot pin down a district -- one ZIP often spans several -- and
  // the geocoder answers only "not found" for it. Matching ZIP+4 too: the extra
  // four digits identify a delivery segment, not a district.
  var ZIP_RE = /^\d{5}(-\d{4})?$/;

  /**
   * What kind of thing did the voter type? Pure, so the decision to spend a
   * network request is testable on its own.
   * Returns { kind: 'empty' | 'zip' | 'ok', value } with `value` trimmed.
   */
  function classifyAddress(raw) {
    var value = String(raw == null ? '' : raw).trim();
    if (!value) return { kind: 'empty', value: '' };
    if (ZIP_RE.test(value)) return { kind: 'zip', value: value };
    return { kind: 'ok', value: value };
  }

  /**
   * The messages, in one place so wording cannot drift between pages while the
   * page-specific parts stay substitutable.
   *   subject        — 'your district' or 'your districts'
   *   fallbackPhrase — names this page's own fallback control
   */
  function messages(opts) {
    var subject = (opts && opts.subject) || 'your districts';
    var fallback = (opts && opts.fallbackPhrase) || '';
    var orFallback = fallback ? ', or ' + fallback : '';
    return {
      empty: 'Enter your address' + orFallback + '.',
      zip: 'A ZIP code alone isn’t enough to find ' + subject + '. '
         + 'Enter your full street address' + orFallback + '.',
      working: 'Looking up ' + subject + '…',
      unavailable: 'Address lookup is unavailable right now' + orFallback + '.',
      failed: 'That address could not be looked up' + orFallback + '.',
    };
  }

  /**
   * Wire an address lookup. Config:
   *   input          element-like with .value (required)
   *   button         element-like, disabled during a lookup (optional)
   *   setStatus(msg, isError)   how this page shows a message (required)
   *   onResolve(loc) what this page does with a resolved location (required).
   *                  May return an outcome string to replace 'success' -- a page
   *                  that got a location with no district of its own says so --
   *                  or a promise, which is awaited: a page that fetches and
   *                  renders before it is really done keeps the latch held, and
   *                  a failure in there is reported like any other.
   *   setBusy(bool)  optional; defaults to toggling `button.disabled`. Pages with
   *                  a second lookup button share one latch through this.
   *   subject, fallbackPhrase   copy, see messages()
   *   eventName      outcome event name; omit to report nothing
   *   eventParams    extra author-set enums merged into every event
   *   geocode        defaults to window.SampleBallot.geocodeAddress
   *   track          defaults to window.vgTrack
   *   save           defaults to window.VoterLocation.save
   *
   * Returns { run, isBusy, messages }.
   */
  function createAddressLookup(config) {
    var cfg = config || {};
    var msg = messages(cfg);
    var busy = false;

    function setBusy(value) {
      busy = value;
      if (typeof cfg.setBusy === 'function') cfg.setBusy(value);
      else if (cfg.button) cfg.button.disabled = value;
    }

    // Outcome only -- never the address, the coordinates or the resolved
    // district. Params are enums chosen by the caller, per _includes/track.html.
    function track(outcome) {
      if (!cfg.eventName) return;
      var fn = cfg.track || (typeof window !== 'undefined' ? window.vgTrack : null);
      if (typeof fn !== 'function') return;
      var params = { method: 'address', outcome: outcome };
      for (var k in (cfg.eventParams || {})) {
        if (Object.prototype.hasOwnProperty.call(cfg.eventParams, k)) {
          params[k] = cfg.eventParams[k];
        }
      }
      fn(cfg.eventName, params);
    }

    function geocoder() {
      if (typeof cfg.geocode === 'function') return cfg.geocode;
      var sb = (typeof window !== 'undefined') && window.SampleBallot;
      return sb && typeof sb.geocodeAddress === 'function' ? sb.geocodeAddress : null;
    }

    function saveLocation(loc) {
      if (cfg.save === false) return;
      var fn = typeof cfg.save === 'function'
        ? cfg.save
        : (typeof window !== 'undefined' && window.VoterLocation
            ? window.VoterLocation.save : null);
      // Districts and county only. voter-location.js never persists the address,
      // which is the promise the privacy note on each page makes.
      if (typeof fn === 'function') fn(loc);
    }

    function run() {
      // A second click while a lookup is in flight is a double-submit, not a
      // new question.
      if (busy) return Promise.resolve('busy');

      var parsed = classifyAddress(cfg.input ? cfg.input.value : '');
      if (parsed.kind === 'empty') {
        cfg.setStatus(msg.empty, true);
        return Promise.resolve('empty');
      }
      if (parsed.kind === 'zip') {
        // Returned before any request: the guard exists to not spend one.
        if (typeof cfg.onRefuse === 'function') cfg.onRefuse('zip_only');
        cfg.setStatus(msg.zip, true);
        track('zip_only');
        return Promise.resolve('zip_only');
      }

      var geocode = geocoder();
      if (!geocode) {
        if (typeof cfg.onRefuse === 'function') cfg.onRefuse('unavailable');
        cfg.setStatus(msg.unavailable, true);
        track('unavailable');
        return Promise.resolve('unavailable');
      }

      setBusy(true);
      cfg.setStatus(msg.working, false);

      return Promise.resolve()
        .then(function () { return geocode(parsed.value); })
        .then(function (loc) {
          saveLocation(loc);
          // Awaited, so a page that renders asynchronously holds the latch until
          // it has actually finished and its failures land in the catch below.
          return Promise.resolve(cfg.onResolve(loc, parsed.value));
        })
        .then(function (outcome) {
          return typeof outcome === 'string' ? outcome : 'success';
        })
        .catch(function (err) {
          if (typeof cfg.onReject === 'function') cfg.onReject(err);
          cfg.setStatus((err && err.message) || msg.failed, true);
          return 'error';
        })
        .then(function (outcome) {
          setBusy(false);
          track(outcome);
          return outcome;
        });
    }

    return {
      run: run,
      isBusy: function () { return busy; },
      messages: msg,
    };
  }

  var AddressLookup = {
    classifyAddress: classifyAddress,
    createAddressLookup: createAddressLookup,
    messages: messages,
    ZIP_RE: ZIP_RE,
  };

  if (typeof window !== 'undefined') window.AddressLookup = AddressLookup;
  if (typeof module !== 'undefined' && module.exports) module.exports = AddressLookup;
})();
