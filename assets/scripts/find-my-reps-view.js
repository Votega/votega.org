/*
 * find-my-reps-view.js — turning a resolved location into the Find My Reps view.
 *
 * find-my-reps.html asks a voter where they live two ways (an address through
 * the shared address-lookup.js, or a county picker) and can also reuse a
 * location resolved earlier in the visit. All three arrive at the same thing: a
 * set of district numbers per chamber. Everything from there — expanding a
 * county into the districts it touches, matching districts to sitting members,
 * and building the markup — is pure string and array work with no page state,
 * so it lives here where it can be tested directly.
 *
 * Why arrays: the Census geocoder resolves exactly one district per chamber,
 * but a county touches many (Gwinnett 37 seats, Fulton 36), so the view works
 * in arrays throughout and the address path passes one-element ones. An empty
 * array means that chamber could not be determined and its section is omitted
 * rather than rendered as a false vacancy.
 *
 * No `document` here, at load time or inside: the page passes its data and its
 * URL helpers in, so this module is exercised under
 * tests/js/load-browser-module.js against plain objects, with no DOM and no
 * dependency tree. See tests/js/find-my-reps-view.test.js. That constraint is
 * also why escaping goes through VoteGA.escapeHtml (html-escape.js) rather than
 * the DOM round-trip the page used to do inline — which escaped `& < >` but not
 * quotes, while feeding `href="…"` and `src="…"`.
 */
'use strict';

(function () {
  // Historical roster entries kept only so earlier votes still attribute by id.
  var DEPARTED = { Resigned: 1, Removed: 1, Deceased: 1 };

  function esc(value) {
    return (typeof window !== 'undefined' && window.VoteGA && window.VoteGA.escapeHtml)
      ? window.VoteGA.escapeHtml(value)
      : (value == null ? '' : String(value))
          .replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
          });
  }

  function partyLetter(party) {
    var p = (party || '').toLowerCase();
    return p.indexOf('dem') === 0 ? 'D' : p.indexOf('rep') === 0 ? 'R' : 'I';
  }

  function chip(party) {
    if (!party) return '';
    var L = partyLetter(party);
    return '<span class="fmr-chip ' + L + '">' + L + '</span>';
  }

  // current-members.json carries "Last, First" on some records and split name
  // fields on others.
  function fedName(member) {
    if (member.firstName && member.lastName) return member.firstName + ' ' + member.lastName;
    var n = member.name || '', i = n.indexOf(', ');
    return i > -1 ? n.slice(i + 2) + ' ' + n.slice(0, i) : n;
  }

  // A federal member's chamber is on their most recent term, not the record.
  function fedChamber(member) {
    var terms = (member.terms && member.terms.item) || [];
    return terms.length ? terms[terms.length - 1].chamber : null;
  }

  // Same wording as the sample ballot's contest badge, so the site reads alike.
  function badge(opts) {
    return opts && opts.ambiguous
      ? ' <span class="fmr-badge fmr-badge-ambiguous">may not be your district</span>' : '';
  }

  /**
   * One rep row, or a "vacant" note when the seat has no sitting member. The
   * office heading is NOT here: a county can touch several districts in the same
   * chamber, so the heading belongs to the group (see repSection).
   */
  function repRow(member, opts) {
    opts = opts || {};
    if (!member) {
      return '<div class="fmr-repcard"><span class="fmr-photo fmr-photo-blank">—</span>'
        + '<div><div class="fmr-repname fmr-vacant">' + esc(opts.vacant || 'Seat currently vacant') + '</div>'
        + (opts.sub ? '<div class="fmr-repmeta">' + esc(opts.sub) + badge(opts) + '</div>' : '')
        + (opts.link ? '<div class="fmr-repmeta"><a href="' + esc(opts.link.href) + '" target="_blank" rel="noopener">'
            + esc(opts.link.label) + '</a></div>' : '')
        + '</div></div>';
    }
    var photo = opts.photo
      ? '<img class="fmr-photo" src="' + esc(opts.photo) + '" alt="" loading="lazy" />'
      : '<span class="fmr-photo fmr-photo-blank">👤</span>';
    return '<a class="fmr-repcard" href="' + esc(opts.href) + '">' + photo
      + '<div><div class="fmr-repname">' + esc(opts.name) + chip(opts.party) + '</div>'
      + '<div class="fmr-repmeta">' + esc(opts.sub || '') + badge(opts) + '</div></div></a>';
  }

  /**
   * A suspended member is shown as a vacant seat, linked to the Executive Order
   * that suspended them (the markdown link the roster keeps in statusNote). Only
   * an https URL is accepted, so a malformed note degrades to no link.
   */
  function suspendedSeat(m, d, sub, ambiguous) {
    var url = /\]\((https:\/\/[^)\s]+)\)/.exec(m.statusNote || '');
    return {
      sub: sub || 'District ' + d,
      ambiguous: !!ambiguous,
      vacant: 'Vacant',
      link: url ? { href: url[1], label: 'Member suspended by Executive Order' } : null,
    };
  }

  /** One office heading plus every row under it; nothing at all when empty. */
  function repSection(office, rows, note) {
    if (!rows.length) return '';
    return '<div><p class="fmr-office">' + esc(office) + '</p>'
      + (note ? '<p class="fmr-group-note">' + esc(note) + '</p>' : '')
      + rows.join('') + '</div>';
  }

  /**
   * The geocoder returns one district per chamber; the view works in arrays.
   * A null district becomes an empty array, which omits that section.
   */
  function normalizeAddressLoc(loc) {
    var one = function (v) { return v == null ? [] : [v]; };
    return {
      source: 'address',
      matchedAddress: loc.matchedAddress,
      county: loc.county,
      usHouse: one(loc.usHouse),
      stateSenate: one(loc.stateSenate),
      stateHouse: one(loc.stateHouse),
    };
  }

  /**
   * Every district a county touches, from the reapportionment office's own
   * county→district tables (ga-districts.js), ascending.
   *   maps — { usHouse, stateSenate, stateHouse }, each county→districts
   */
  function countyLoc(county, maps) {
    var pick = function (map) {
      return ((map && map[county]) || []).slice().sort(function (a, b) { return a - b; });
    };
    maps = maps || {};
    return {
      source: 'county',
      matchedAddress: null,
      county: county,
      usHouse: pick(maps.usHouse),
      stateSenate: pick(maps.stateSenate),
      stateHouse: pick(maps.stateHouse),
    };
  }

  // The ZIP table's expansion and share wording are shared with the candidate
  // finder (zip-districts.js), so the two pages cannot drift.
  function zipApi() {
    var z = typeof window !== 'undefined' && window.ZipDistricts;
    if (!z) throw new Error('zip-districts.js must load before find-my-reps-view.js');
    return z;
  }
  function shareLabel(share) { return zipApi().shareLabel(share); }

  /**
   * A bare ZIP in the same shape as countyLoc, plus `shares` for the row labels.
   *   entry — zips[zip] from ga-zip-districts.json, or undefined
   * Null when there is nothing to list (see ZipDistricts.expand), so the caller
   * says so rather than render an empty result.
   */
  function zipLoc(zip, entry) {
    var e = zipApi().expand(entry);
    if (!e) return null;
    return {
      source: 'zip',
      zip: zip,
      matchedAddress: null,
      city: e.city,
      counties: e.counties,
      usHouse: e.usHouse,
      stateSenate: e.stateSenate,
      stateHouse: e.stateHouse,
      shares: e.shares,
    };
  }

  /** County names for the picker, sorted. Empty when the tables are missing. */
  function countyNames(map) {
    return map ? Object.keys(map).sort() : [];
  }

  /**
   * A location persisted earlier this visit (voter-location.js), turned into
   * something renderable plus the label naming where it came from. Returns null
   * when there is nothing usable — no stored value, a source with no districts,
   * or a county the tables do not know — so the caller shows no banner rather
   * than an empty one.
   *
   * Only derived districts are ever stored, never the address, so `where`
   * describes districts or a county and the caller must not imply otherwise.
   */
  function carriedLocation(stored, maps) {
    if (!stored) return null;
    maps = maps || {};
    if (stored.source === 'address'
        && (stored.usHouse != null || stored.stateSenate != null || stored.stateHouse != null)) {
      var parts = [];
      if (stored.stateHouse  != null) parts.push('State House ' + stored.stateHouse);
      if (stored.stateSenate != null) parts.push('State Senate ' + stored.stateSenate);
      if (stored.usHouse     != null) parts.push('U.S. House ' + stored.usHouse);
      return { loc: normalizeAddressLoc(stored), where: parts.join(' · '), county: null };
    }
    if (stored.source === 'county' && stored.county
        && maps.stateHouse && maps.stateHouse[stored.county]) {
      return {
        loc: countyLoc(stored.county, maps),
        where: stored.county + ' County',
        county: stored.county,
      };
    }
    return null;
  }

  /**
   * The whole results view as a string.
   *   loc  — from normalizeAddressLoc / countyLoc / carriedLocation
   *   fed  — current-members.json
   *   ga   — ga-members.json
   *   urls — { fedHref(member), gaHref(member) }, supplied by the page because
   *          only it holds the clean entity-URL maps
   */
  function renderReps(loc, fed, ga, urls) {
    var fedHref = (urls && urls.fedHref) || function () { return '#'; };
    var gaHref  = (urls && urls.gaHref)  || function () { return '#'; };

    var fedGA = ((fed && fed.members) || []).filter(function (m) {
      return m.state === 'Georgia' && m.currentMember !== false;
    });
    var senators = fedGA.filter(function (m) { return fedChamber(m) === 'Senate'; })
      .sort(function (a, b) { return fedName(a).localeCompare(fedName(b)); });
    var gaSeated = ((ga && ga.members) || []).filter(function (m) { return !DEPARTED[m.status]; });

    var html = '';
    if (loc.matchedAddress) {
      html += '<p class="fmr-matched">Showing representatives for <strong>'
        + esc(loc.matchedAddress) + '</strong></p>';
    } else if (loc.source === 'county') {
      html += '<p class="fmr-matched">Showing every district that touches <strong>' + esc(loc.county)
        + ' County</strong>. Your own address falls in one district per chamber — enter it above to narrow this down.</p>';
    }

    var isZip = loc.source === 'zip';
    // "District 58", plus how much of the ZIP it covers when the location is one.
    var distSub = function (key, d) {
      var label = isZip && loc.shares && loc.shares[key] ? shareLabel(loc.shares[key][d]) : null;
      return 'District ' + d + (label ? ' · ' + label : '');
    };
    // A county or a ZIP that lists more than one district in a chamber cannot say
    // which is the voter's, so every row in that chamber carries the badge. One
    // district means that seat really is theirs. An address is exact: never badged.
    var multi = function (key) {
      return (isZip || loc.source === 'county') && (loc[key] || []).length > 1;
    };
    if (isZip) {
      var where = loc.counties && loc.counties.length
        ? 'This ZIP is in ' + loc.counties.join(', ') + (loc.counties.length > 1 ? ' counties. ' : ' County. ') : '';
      html += '<h2 class="fmr-zip-head">Districts touching ZIP ' + esc(loc.zip) + '</h2>'
        + '<p class="fmr-matched">' + esc(where) + 'A ZIP code can span several districts, and only a street address'
        + ' identifies the ones you actually vote in. Every district with residents in this ZIP is'
        + ' listed, in number order — enter your full address above to narrow it to yours.</p>';
    }

    html += repSection('U.S. Senate', senators.map(function (m) {
      return repRow(m, {
        name: fedName(m), party: m.partyName, sub: 'Georgia · U.S. Senator',
        photo: m.depiction && m.depiction.imageUrl, href: fedHref(m),
      });
    }));

    html += repSection('U.S. House', (loc.usHouse || []).map(function (d) {
      var m = fedGA.filter(function (x) {
        return fedChamber(x) === 'House of Representatives' && x.district === d;
      })[0];
      return repRow(m, m ? {
        name: fedName(m), party: m.partyName, sub: distSub('usHouse', d),
        photo: m.depiction && m.depiction.imageUrl, href: fedHref(m), ambiguous: multi('usHouse'),
      } : { sub: distSub('usHouse', d), ambiguous: multi('usHouse'), vacant: 'No sitting U.S. Representative found' });
    }));

    html += repSection('Georgia State Senate', (loc.stateSenate || []).map(function (d) {
      var m = gaSeated.filter(function (x) { return x.chamber === 'Senate' && x.district === d; })[0];
      if (m && m.status === 'Suspended') return repRow(null, suspendedSeat(m, d, distSub('stateSenate', d), multi('stateSenate')));
      return repRow(m, m ? {
        name: m.name, party: m.party,
        sub: distSub('stateSenate', d) + (m.status === 'Vacant' ? ' · Vacant' : ''),
        photo: m.imageUrl, href: gaHref(m), ambiguous: multi('stateSenate'),
      } : { sub: distSub('stateSenate', d), ambiguous: multi('stateSenate'), vacant: 'This Senate seat is currently vacant' });
    }));

    html += repSection('Georgia House of Representatives', (loc.stateHouse || []).map(function (d) {
      var m = gaSeated.filter(function (x) { return x.chamber === 'House of Representatives' && x.district === d; })[0];
      if (m && m.status === 'Suspended') return repRow(null, suspendedSeat(m, d, distSub('stateHouse', d), multi('stateHouse')));
      return repRow(m, m ? {
        name: m.name, party: m.party,
        sub: distSub('stateHouse', d) + (m.status === 'Vacant' ? ' · Vacant' : ''),
        photo: m.imageUrl, href: gaHref(m), ambiguous: multi('stateHouse'),
      } : { sub: distSub('stateHouse', d), ambiguous: multi('stateHouse'), vacant: 'This House seat is currently vacant' });
    }));

    return html;
  }

  var FindMyRepsView = {
    normalizeAddressLoc: normalizeAddressLoc,
    countyLoc: countyLoc,
    zipLoc: zipLoc,
    shareLabel: shareLabel,
    countyNames: countyNames,
    carriedLocation: carriedLocation,
    renderReps: renderReps,
    // Exposed for tests and for any page that needs one piece on its own.
    repRow: repRow,
    repSection: repSection,
    fedName: fedName,
    fedChamber: fedChamber,
    partyLetter: partyLetter,
  };

  if (typeof window !== 'undefined') window.FindMyRepsView = FindMyRepsView;
})();
