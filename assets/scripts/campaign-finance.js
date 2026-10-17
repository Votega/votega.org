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
    return '/';
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
  // Shared by every finance panel (the legislator pages used to carry their own copies).
  // Rounding is decided on the ROUNDED value: $999,500–$999,999 round to 1000K, so the
  // K branch has to hand off to M at that boundary rather than at the raw 1e6.
  function fmtMoney(n) {
    if (n == null) return '—';
    const sign = n < 0 ? '-' : '';
    const abs = Math.abs(n);
    if (abs >= 1e6 || Math.round(abs / 1e3) >= 1000) return sign + '$' + (abs / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return sign + '$' + Math.round(abs / 1e3) + 'K';
    return sign + '$' + Math.round(abs).toLocaleString();
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

  // Of several filings, the one with the newest lastFileDate — the live candidacy,
  // where a filing with no date never outranks one that has. Mirrors _newest_first()
  // in generate_fec_data.py. Falls back to array order when no id carries a date,
  // so data generated before lastFileDate existed behaves as it did.
  function mostRecentlyFiled(candidates, ids) {
    return ids.reduce((best, cid) => {
      const a = (candidates[cid] && candidates[cid].lastFileDate) || '';
      const b = (candidates[best] && candidates[best].lastFileDate) || '';
      return a > b ? cid : best;
    }, ids[0]);
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

    // c. One committee across all remaining ids means the same filer under several
    //    candidate registrations — a sitting House member running for Senate holds
    //    an H and an S id drawing on one committee. Both carry the same money, so
    //    the totals cannot separate them; the most recently filed id can, and it is
    //    the one whose FEC page actually shows the cycle. Picking by array order
    //    sent Buddy Carter's page to his dormant House filing, which FEC.gov renders
    //    as "nothing filed".
    const committees = new Set(pool.map(cid => C[cid] && C[cid].committeeId));
    if (committees.size === 1 && !committees.has(null) && !committees.has(undefined)) {
      const withData = pool.filter(cid => fecHasActivity(C[cid]));
      return { id: mostRecentlyFiled(C, withData.length ? withData : pool), status: 'ok' };
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

  // -- "Where the money came from": composition of receipts -----------------
  //
  // The headline cards print Total Raised and From Individuals, which on an
  // incumbent leaves a large unexplained gap (Clay Fuller, 2026: $1.85M raised,
  // $1.08M from individuals, $766K unaccounted for). That gap is the PAC, party,
  // transfer and self-funding money -- the part of "who funds this member" a
  // reader most wants named, and it was on the wire already inside the committee
  // totals response. generate_fec_data.py now keeps it as entry.funding.
  //
  // Lives here rather than in either template because the finance panel is
  // duplicated between _includes/entity/federal-legislator.html and
  // _includes/entity/candidate.html; a second copy of this logic would diverge
  // the way the employers table already has.

  // Display groups, each summing one or more raw components. Ordered by size at
  // render time, not here -- "where did the money come from" is answered fastest
  // when the biggest source is first, and the fixed label+color per group keeps
  // two members comparable.
  const FUNDING_GROUPS = [
    {
      key: 'small', label: 'Small donors (under $200)', color: '#15803d',
      parts: ['individualUnitemized'],
      // Contributions from donors whose cycle total stays at or under $200. The
      // FEC does not require these to be itemized, so no name, employer or date
      // is disclosed for any of it -- it is a sum, not a list of people.
    },
    { key: 'itemized', label: 'Individuals ($200 and up)', color: '#4ade80',
      parts: ['individualItemized'] },
    { key: 'pac',      label: 'PACs and other committees', color: '#b45309',
      parts: ['pac'] },
    { key: 'party',    label: 'Party committees', color: '#a16207',
      parts: ['party'] },
    { key: 'transfers', label: 'Transfers from the candidate\u2019s other committees', color: '#1d4ed8',
      parts: ['transfers'] },
    { key: 'self',     label: 'The candidate (contributions and loans)', color: '#6d28d9',
      parts: ['candidateSelf', 'candidateLoans'] },
    { key: 'other',    label: 'Other receipts', color: '#9ca3af',
      parts: ['otherLoans', 'offsets', 'otherReceipts'] },
  ];

  function fundingRows(entry) {
    const f = entry && entry.funding;
    const receipts = entry && entry.totalRaised;
    if (!f || !receipts || receipts <= 0) return null;

    const rows = FUNDING_GROUPS
      .map(g => ({
        label: g.label,
        color: g.color,
        amount: g.parts.reduce((sum, k) => sum + (f[k] || 0), 0),
      }))
      .filter(r => r.amount > 0);
    if (!rows.length) return null;

    // Anything receipts covers that the named components do not. A renamed or
    // dropped FEC field, or a receipt type with no component of its own, lands
    // here instead of quietly disappearing from a breakdown that claims to
    // account for every dollar raised. Negatives (refunds netted into a
    // component, rounding) are clamped away rather than printed as a source.
    const named = rows.reduce((sum, r) => sum + r.amount, 0);
    const remainder = receipts - named;
    // Floor keeps a rounding crumb from rendering as a 0%-share row of its own;
    // $1,000 and 0.5% are both small enough to be noise on any real filing.
    if (remainder > 1000 && remainder / receipts > 0.005) {
      const other = rows.find(r => r.label === 'Other receipts');
      if (other) other.amount += remainder;
      else rows.push({ label: 'Other receipts', color: '#9ca3af', amount: remainder });
    }

    rows.sort((a, b) => b.amount - a.amount);
    // Receipts is the denominator that makes a row readable on its own ("31% of
    // what he raised came from PACs"). Guard it anyway: an amended filing can
    // leave the components summing past gross receipts, and dividing by the
    // smaller figure would print a 120% share and a bar segment wider than the
    // bar. Falling back to the row total caps shares at 100% in that case and
    // changes nothing in the normal one.
    const denom = Math.max(receipts, rows.reduce((sum, r) => sum + r.amount, 0));
    rows.forEach(r => { r.share = r.amount / denom; });
    return { rows, receipts };
  }

  // Shares are of total receipts, so they sum to 100% and each row is readable
  // on its own ("31% of what he raised came from PACs") without the reader
  // having to hold a denominator in their head.
  function fundingBreakdownHtml(entry) {
    const data = fundingRows(entry);
    if (!data) return '';
    // A real source too small to round to a whole percent reads as '0%' and looks
    // like a rendering bug. Entity-escaped: a raw '<' in text, even one a browser
    // tolerates, is the kind of thing a downstream sanitizer eats.
    const pct = share => (share * 100 < 1 ? '&lt;1' : Math.round(share * 100)) + '%';

    const bar = data.rows.map(r =>
      '<span class="funding-bar-seg" style="width:' + (r.share * 100).toFixed(2) + '%;background:' + r.color + ';"'
      + ' title="' + r.label + ': ' + fmtMoney(r.amount) + '"></span>').join('');

    const body = data.rows.map(r =>
      '<tr>'
      + '<td><span class="funding-swatch" style="background:' + r.color + ';"></span>' + r.label + '</td>'
      + '<td>' + fmtMoney(r.amount) + '</td>'
      + '<td>' + pct(r.share) + '</td>'
      + '</tr>').join('');

    return '<h3 class="finance-subhead">Where the money came from</h3>'
      + '<p class="finance-meta funding-note">Share of the ' + fmtMoney(data.receipts)
      + ' raised this cycle, through the reporting date above.</p>'
      + '<div class="funding-bar" role="presentation">' + bar + '</div>'
      + '<table class="employers-table funding-table">'
      + '<thead><tr><th>Source</th><th>Amount</th><th>Share</th></tr></thead>'
      + '<tbody>' + body + '</tbody></table>'
      + '<p class="finance-meta funding-note">Donors who gave $200 or less in total are not itemized by the FEC,'
      + ' so no names, employers or dates are disclosed for that money.</p>';
  }

  // Per-block provenance line ("Finance data from the FEC, updated October 4, 2026.").
  // Finance figures come from their own files (ga-fec-data.json /
  // ga-campaign-finance.json), not from the roster the page-level stamp describes, so
  // each panel dates itself from the finance file's own metadata.generatedAt. Returns ''
  // when the timestamp is absent or unparseable rather than printing a bare or wrong date.
  function provenanceLine(sourceName, generatedAt) {
    if (!generatedAt) return '';
    const d = new Date(generatedAt);
    if (isNaN(d)) return '';
    const when = d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    return '<p class="finance-meta">Finance data from ' + sourceName + ', updated ' + when + '.</p>';
  }

  return {
    getFecData, getGaFinanceData, fmtMoney, provenanceLine,
    normalizeName, candidateLastName, findFecId, findFecMatch,
    narrowFecMatches, fecHasActivity,
    gaCandidatePool, findGaFilers,
    GA_CHAMBER_MAP, GA_OFFICE_MAP,
    fecSearchUrl, cycleLabelFor,
    fundingBreakdownHtml,
    summary,
  };
})();
