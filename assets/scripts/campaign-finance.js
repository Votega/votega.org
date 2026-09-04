/*
 * campaign-finance.js — shared campaign-finance lookup for VoteGA.
 *
 * Single source of truth for matching a candidate to their campaign-finance
 * filing, across the two sources the site uses:
 *   • Federal races → FEC (assets/data/ga-fec-data.json)
 *   • State races   → GA Ethics Commission PeachFile (assets/data/ga-campaign-finance.json)
 *
 * Consumed by candidate.html (full profile section) and race.html (compact
 * side-by-side cards). The GA matching mirrors find_filers() in
 * scripts/report_ga_finance_matches.py and tools/ga-finance-overrides-editor.html —
 * keep those in step. Exposed on window.CampaignFinance.
 */
window.CampaignFinance = (function () {
  'use strict';

  // Resolve data URLs against the site root, not the current page. Bare-relative
  // paths only work on the legacy root pages (/race.html, /candidate.html); on
  // the clean entity URLs (/races/<slug>/, /ga-legislators/<slug>/) a relative
  // 'assets/data/…' fetch resolves under the entity directory and 404s, which
  // surfaced as "Finance data unavailable" on every entity-page finance tab.
  // Mirrors the getBasePath() helper the entity includes use for their own data.
  function basePath() {
    return window.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
  }
  const FEC_DATA_URL   = basePath() + 'assets/data/ga-fec-data.json';
  const GA_FINANCE_URL = basePath() + 'assets/data/ga-campaign-finance.json';

  const PEACHFILE_SEARCH = 'https://peachfile.ethics.ga.gov/public/cf/publiccandidate';

  // FEC cycle comes from ga-fec-data.json's own metadata.cycle (set by
  // generate_fec_data.py from races.json) rather than a hardcoded year, so a
  // new cycle is a data change, not a code one — same principle as the GA/
  // PeachFile branch below, which already reads data.metadata.cycle. Falls
  // back to an unfiltered search link when the cycle isn't known yet (e.g.
  // ga-fec-data.json failed to load).
  function fecSearchUrl(cycle) {
    return cycle
      ? `https://www.fec.gov/data/candidates/?state=GA&election_year=${cycle}`
      : 'https://www.fec.gov/data/candidates/?state=GA';
  }
  function cycleLabelFor(cycle) {
    return cycle ? `${cycle - 1}–${cycle} cycle` : null;
  }

  // ── loaders (cached) ───────────────────────────────────────────────────────
  let _fecCache;   // undefined = unfetched, null = failed
  let _gaCache;

  async function getFecData() {
    if (_fecCache !== undefined) return _fecCache;
    try {
      const res = await fetch(FEC_DATA_URL);
      _fecCache = res.ok ? await res.json() : null;
    } catch (err) { console.error('CampaignFinance.getFecData()', err); _fecCache = null; }
    return _fecCache;
  }

  async function getGaFinanceData() {
    if (_gaCache !== undefined) return _gaCache;
    try {
      const res = await fetch(GA_FINANCE_URL);
      _gaCache = res.ok ? await res.json() : null;
    } catch (err) { console.error('CampaignFinance.getGaFinanceData()', err); _gaCache = null; }
    return _gaCache;
  }

  // ── formatting ─────────────────────────────────────────────────────────────
  function fmtMoney(n) {
    if (n == null) return '—';
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  // ── FEC name matching ──────────────────────────────────────────────────────
  // Mirrors normalize_name() in generate_fec_data.py. Both sides reduce a name to
  // 'first last', lowercase, without punctuation, suffixes, honorifics, quoted
  // nicknames, middle names, or bare initials.
  //
  // The two sides see different input shapes, which is the whole difficulty:
  // FEC names arrive as 'LAST, FIRST MIDDLE' while races.json carries display
  // names like 'Tricia R. Pridemore'. Reducing only the comma form (as this did
  // previously) left 44 of 91 federal candidates producing three-token keys that
  // could never match a two-token index entry, which made the name fallback dead
  // for most of the field. See CODEBASE-REVIEW-2026-08-18.md finding 1.3.
  function normalizeName(name) {
    let n = String(name || '').toLowerCase();
    n = n.replace(/["'].*?["']/g, '');                  // quoted nicknames
    n = n.replace(/\b(jr|sr|ii|iii|iv|esq)\.?\b/g, ''); // suffixes
    n = n.replace(/\b(dr|mr|mrs|ms)\.?\b/g, '');        // honorifics
    n = n.replace(/[^a-z\s,]/g, '').trim();

    const comma = n.indexOf(',');
    if (comma !== -1) {
      // 'LAST, FIRST MIDDLE' → 'first last'. Skip single-char initials so
      // 'OSSOFF, T. JONATHAN' yields 'jonathan ossoff', not 't ossoff'.
      const last = n.slice(0, comma).trim();
      const rest = n.slice(comma + 1).trim().split(/\s+/).filter(Boolean);
      const named = rest.filter(t => t.length > 1);
      const first = (named.length ? named : rest)[0] || '';
      n = `${first} ${last}`;
    } else {
      // 'First Middle Last' → 'first last'.
      const toks = n.split(/\s+/).filter(Boolean);
      if (toks.length > 2) {
        const named = toks.filter(t => t.length > 1);
        const use = named.length ? named : toks;
        n = use.length > 1 ? `${use[0]} ${use[use.length - 1]}` : (use[0] || '');
      }
    }
    return n.replace(/\s+/g, ' ').trim();
  }

  function candidateLastName(name) {
    const parts = String(name || '').trim().split(/\s+/);
    return parts[parts.length - 1].toLowerCase().replace(/[^a-z]/g, '');
  }

  // A filing with money or a coverage date is a live candidacy; one with neither
  // is typically a stale prior-cycle registration under the same name.
  function fecHasActivity(entry) {
    return !!entry && (entry.totalRaised != null || entry.coverageEndDate != null);
  }

  // Normalized-name → [candidateId, ...], built from fecData.candidates rather
  // than read from fecData.byNormalizedName, because that index keeps only one id
  // per key and so cannot express a collision. Fourteen normalized names in the
  // current FEC data map to more than one filing.
  let _nameIndex = null, _nameIndexFor = null;
  function fecNameIndex(fecData) {
    if (_nameIndexFor === fecData && _nameIndex) return _nameIndex;
    const idx = Object.create(null);
    const all = (fecData && fecData.candidates) || {};
    for (const cid of Object.keys(all)) {
      const key = normalizeName(all[cid] && all[cid].name);
      if (!key) continue;
      (idx[key] || (idx[key] = [])).push(cid);
    }
    _nameIndex = idx;
    _nameIndexFor = fecData;
    return idx;
  }

  // Reduce several candidate FEC filings to one, or report ambiguity rather than
  // guessing — the rule findGaFilers() already follows on the GA side. Picking
  // blindly is what put another man's money on a candidate page.
  // See CODEBASE-REVIEW-2026-08-18.md finding 1.2.
  function narrowFecMatches(fecData, ids, wantName) {
    const C = (fecData && fecData.candidates) || {};
    if (!ids || !ids.length) return { id: null, status: 'none' };
    if (ids.length === 1) return { id: ids[0], status: 'ok' };

    // a. Exact full-name agreement separates two different people who merely
    //    share a surname and a district (BROWN, JAMES M vs BROWN, TIMOTHY BEAU).
    const key = normalizeName(wantName);
    const named = ids.filter(cid => normalizeName(C[cid] && C[cid].name) === key);
    if (named.length === 1) return { id: named[0], status: 'ok' };
    let pool = named.length ? named : ids;

    // b. One live filing beats any number of dormant ones — this is what tells a
    //    2026 campaign apart from the same person's 2014 candidacy.
    const active = pool.filter(cid => fecHasActivity(C[cid]));
    if (active.length === 1) return { id: active[0], status: 'ok' };
    pool = active.length ? active : pool;

    // c. One committee across all remaining ids means duplicate FEC records for a
    //    single filer, so either is correct; prefer whichever carries totals.
    const committees = new Set(pool.map(cid => C[cid] && C[cid].committeeId));
    if (committees.size === 1 && !committees.has(null) && !committees.has(undefined)) {
      const withData = pool.filter(cid => fecHasActivity(C[cid]));
      return { id: (withData.length ? withData : pool)[0], status: 'ok' };
    }

    return { id: null, status: 'ambiguous' };
  }

  // Resolve a candidate to one FEC filing.
  // Returns { id, status } where status ∈ 'ok' | 'none' | 'ambiguous'.
  function findFecMatch(fecData, candidate, race) {
    const chamber = race.chamber || '';
    const wantOffice = chamber === 'U.S. Senate' ? 'S'
                     : chamber === 'U.S. House'  ? 'H' : null;

    // 0. Explicit editorial pin. An FEC candidate id set on the entry always wins —
    //    the escape hatch for cases the heuristics below can't get right (e.g. two
    //    same-surname candidates in one race).
    if (candidate.fecCandidateId && fecData.candidates?.[candidate.fecCandidateId]) {
      return { id: candidate.fecCandidateId, status: 'ok' };
    }

    // 1. Bioguide id (most reliable). A federal incumbent reference carries the
    //    bioguide in memberId; an enriched challenger carries it in existingMemberId.
    //    But only trust it when the matched filing is for the office actually being
    //    sought: a sitting House member running for Senate still has a bioguide that
    //    maps to their House candidacy, so an unqualified match links the wrong race.
    const bioguide = candidate.existingMemberId || candidate.memberId || '';
    const bioMatch = bioguide && fecData.byBioguideId?.[bioguide];
    if (bioMatch) {
      const gotOffice = fecData.candidates?.[bioMatch]?.office;
      if (!wantOffice || !gotOffice || gotOffice === wantOffice) {
        return { id: bioMatch, status: 'ok' };
      }
      // office mismatch → fall through to district/name matching for the new office
    }

    // 2. District + last name (handles formal vs. nickname mismatches).
    //    Collect *every* hit: .find() used to take the first, which silently
    //    resolved a same-surname collision by array order.
    let distKey = null;
    if (chamber === 'U.S. Senate') distKey = 'S';
    else if (chamber === 'U.S. House' && race.district != null) distKey = `H${race.district}`;
    if (distKey && fecData.byDistrict?.[distKey]) {
      const last = candidateLastName(candidate.name);
      const hits = fecData.byDistrict[distKey]
        .filter(cid => fecData.candidates?.[cid]?.lastName === last);
      if (hits.length) {
        const narrowed = narrowFecMatches(fecData, hits, candidate.name);
        if (narrowed.id) return { id: narrowed.id, status: 'ok' };
        return { id: null, status: 'ambiguous' };
      }
    }

    // 3. Normalized full-name match, likewise collision-aware.
    let byName = fecNameIndex(fecData)[normalizeName(candidate.name)] || [];
    if (wantOffice && byName.length > 1) {
      const sameOffice = byName.filter(cid => fecData.candidates?.[cid]?.office === wantOffice);
      if (sameOffice.length) byName = sameOffice;
    }
    return narrowFecMatches(fecData, byName, candidate.name);
  }

  // Back-compat wrapper: returns the id or null, discarding the reason. Callers
  // that want to distinguish "no filing" from "several filings" should use
  // findFecMatch() so they can render the ambiguous case honestly.
  function findFecId(fecData, candidate, race) {
    return findFecMatch(fecData, candidate, race).id;
  }

  // ── GA PeachFile name matching ─────────────────────────────────────────────
  const GA_CHAMBER_MAP = {
    'Georgia House of Representatives': 'House of Representatives',
    'Georgia State Senate': 'Senate',
  };
  const GA_OFFICE_MAP = {
    'Governor': 'Governor',
    'Lieutenant Governor': 'Lieutenant Governor',
    'Secretary of State': 'Secretary of State',
    'Attorney General': 'Attorney General',
    'Commissioner of Agriculture': 'Commissioner of Agriculture',
    'Insurance & Fire Safety Commissioner': 'Commissioner of Insurance',
    'Labor Commissioner': 'Commissioner of Labor',
    'State School Superintendent': 'State School Superintendent',
    'Public Service Commissioner': 'Public Service Commissioner',
  };
  const GA_SUFFIX_RE = /\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|esq)\.?\b/g;

  function gaToks(s) {
    return String(s || '').toLowerCase().replace(GA_SUFFIX_RE, '')
      .replace(/['’]/g, '').replace(/[^a-z\s]/g, ' ').split(/\s+/).filter(Boolean);
  }
  function gaNicknames(s) {
    return [...String(s || '').matchAll(/["“']([A-Za-z]+)["”']/g)].map(m => m[1].toLowerCase());
  }
  function gaFirstNameOk(a, b) {
    for (const x of a) for (const y of b) {
      if (x === y) return true;
      if (x.length >= 3 && y.length >= 3 && (x.startsWith(y) || y.startsWith(x))) return true;
      if (x.length === 1 && y.startsWith(x)) return true;
      if (y.length === 1 && x.startsWith(y)) return true;
    }
    return false;
  }

  function gaCandidatePool(chamber, district, data) {
    const ch = GA_CHAMBER_MAP[chamber];
    if (ch && district != null) return data.bySeat?.[`${ch}-${district}`] || [];
    const office = GA_OFFICE_MAP[chamber];
    if (!office) return [];
    const ids = data.byOffice?.[office] || [];
    if (district != null) {
      const scoped = ids.filter(i => String(data.filers?.[i]?.district ?? '') === String(district));
      if (scoped.length) return scoped;
    }
    return ids;
  }

  function findGaFilers(name, chamber, district, data) {
    // Seat + surname is the match; given name only breaks ties.
    const pool = gaCandidatePool(chamber, district, data);
    if (!pool.length) return [];
    const cand = gaToks(name), nicks = gaNicknames(name);
    const hits = [];
    for (const fid of pool) {
      const f = data.filers?.[fid];
      if (!f) continue;
      const fl = gaToks(f.lastName);
      if (!fl.length || fl.length > cand.length) continue;
      if (cand.slice(-fl.length).join(' ') !== fl.join(' ')) continue;
      hits.push(fid);
    }
    const uniq = [...new Set(hits)];
    if (uniq.length <= 1) return uniq;
    const narrowed = uniq.filter(fid => {
      const f = data.filers[fid];
      const fl = gaToks(f.lastName), ff = gaToks(f.firstName);
      const cf = cand.slice(0, cand.length - fl.length).concat(nicks);
      return cf.length && ff.length && gaFirstNameOk(cf, ff);
    });
    return narrowed.length === 1 ? narrowed : uniq;
  }

  // ── high-level summary ─────────────────────────────────────────────────────
  // Returns a normalized object both consumers can render:
  //   { status, source, sourceShort, raised, spent, cashOnHand, totalIndividual,
  //     cycleLabel, asOf, detailUrl, searchUrl }
  // status ∈ 'ok' | 'none' | 'ambiguous' | 'unavailable'
  async function summary(candidate, race) {
    const isFederal = (race.level || '') === 'federal';

    if (isFederal) {
      const fecData = await getFecData();
      if (!fecData) {
        return { status: 'unavailable', source: 'FEC', sourceShort: 'FEC', searchUrl: fecSearchUrl() };
      }
      const fecCycle = fecData.metadata?.cycle ?? null;
      const match = findFecMatch(fecData, candidate, race);
      const e = match.id ? fecData.candidates?.[match.id] : null;
      if (!e) {
        // 'ambiguous' renders as "Multiple filings match — search FEC" rather than
        // "no filing on record", and never as one of the candidates' figures.
        return {
          status: match.status === 'ambiguous' ? 'ambiguous' : 'none',
          source: 'FEC', sourceShort: 'FEC', searchUrl: fecSearchUrl(fecCycle),
        };
      }
      return {
        status: 'ok',
        source: 'FEC',
        sourceShort: 'FEC',
        raised: e.totalRaised ?? null,
        spent: e.totalSpent ?? null,
        cashOnHand: e.cashOnHand ?? null,
        totalIndividual: e.totalIndividual ?? null,
        cycleLabel: cycleLabelFor(fecCycle),
        asOf: e.coverageEndDate
          ? new Date(e.coverageEndDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
          : null,
        detailUrl: e.fecUrl || null,
        searchUrl: fecSearchUrl(fecCycle),
        raw: e,
      };
    }

    // State (PeachFile)
    const data = await getGaFinanceData();
    if (!data) {
      return { status: 'unavailable', source: 'GA Ethics Commission', sourceShort: 'GA Ethics', searchUrl: PEACHFILE_SEARCH };
    }

    // A reviewed override always wins over the automatic match.
    const key = candidate.id || candidate.existingMemberId || '';
    const override = data.candidateOverrides?.[key];

    let filer = null, ambiguous = false;
    if (override?.noFiling) {
      filer = null;
    } else if (override?.filerEntityId) {
      filer = data.filers?.[override.filerEntityId] || null;
    } else {
      const hits = findGaFilers(candidate.name, race.chamber, race.district, data);
      if (hits.length === 1) filer = data.filers[hits[0]];
      else if (hits.length > 1) ambiguous = true;
    }

    if (ambiguous) {
      return { status: 'ambiguous', source: 'GA Ethics Commission', sourceShort: 'GA Ethics', searchUrl: PEACHFILE_SEARCH };
    }
    if (!filer) {
      return {
        status: 'none', source: 'GA Ethics Commission', sourceShort: 'GA Ethics',
        cycleLabel: String(data.metadata?.cycle ?? ''), searchUrl: PEACHFILE_SEARCH,
      };
    }
    return {
      status: 'ok',
      source: 'GA Ethics Commission',
      sourceShort: 'GA Ethics',
      raised: filer.totalRaised ?? null,
      spent: filer.totalSpent ?? null,
      cashOnHand: filer.cashOnHand ?? null,
      cycleLabel: filer.electionCycle || String(data.metadata?.cycle ?? ''),
      asOf: null, // PeachFile totals are as-of the committee's latest required report
      detailUrl: PEACHFILE_SEARCH,
      searchUrl: PEACHFILE_SEARCH,
      raw: filer,
    };
  }

  return {
    getFecData, getGaFinanceData, fmtMoney,
    normalizeName, candidateLastName, findFecId, findFecMatch,
    narrowFecMatches, fecHasActivity,
    gaCandidatePool, findGaFilers,
    GA_CHAMBER_MAP, GA_OFFICE_MAP,
    fecSearchUrl, cycleLabelFor,
    summary,
  };
})();
