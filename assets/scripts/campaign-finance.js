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

  const FEC_DATA_URL   = 'assets/data/ga-fec-data.json';
  const GA_FINANCE_URL = 'assets/data/ga-campaign-finance.json';

  const PEACHFILE_SEARCH = 'https://peachfile.ethics.ga.gov/public/cf/publiccandidate';
  const FEC_SEARCH       = 'https://www.fec.gov/data/candidates/?state=GA&election_year=2026';

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
  function normalizeName(name) {
    // Mirror normalize_name() in generate_fec_data.py:
    // 'LAST, FIRST MIDDLE' → 'first last' (lowercase, no punctuation/suffixes/nicknames)
    let n = String(name || '').toLowerCase();
    n = n.replace(/["'].*?["']/g, '');
    n = n.replace(/\b(jr|sr|ii|iii|iv|esq)\.?\b/g, '');
    n = n.replace(/[^a-z\s,]/g, '').trim();
    if (n.includes(',')) {
      const [last, first] = n.split(',', 2);
      const firstToken = first.trim().split(/\s+/)[0];
      n = `${firstToken} ${last.trim()}`;
    }
    return n.replace(/\s+/g, ' ').trim();
  }

  function candidateLastName(name) {
    const parts = String(name || '').trim().split(/\s+/);
    return parts[parts.length - 1].toLowerCase().replace(/[^a-z]/g, '');
  }

  function findFecId(fecData, candidate, race) {
    // 1. Bioguide id (most reliable). A federal incumbent reference carries the
    //    bioguide in memberId; an enriched challenger carries it in existingMemberId.
    const bioguide = candidate.existingMemberId || candidate.memberId || '';
    if (bioguide && fecData.byBioguideId?.[bioguide]) return fecData.byBioguideId[bioguide];

    // 2. District + last name (handles formal vs. nickname mismatches)
    const chamber = race.chamber || '';
    let distKey = null;
    if (chamber === 'U.S. Senate') distKey = 'S';
    else if (chamber === 'U.S. House' && race.district != null) distKey = `H${race.district}`;
    if (distKey && fecData.byDistrict?.[distKey]) {
      const last = candidateLastName(candidate.name);
      const match = fecData.byDistrict[distKey].find(cid => fecData.candidates?.[cid]?.lastName === last);
      if (match) return match;
    }

    // 3. Normalized full-name exact match
    return fecData.byNormalizedName?.[normalizeName(candidate.name)] || null;
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
        return { status: 'unavailable', source: 'FEC', sourceShort: 'FEC', searchUrl: FEC_SEARCH };
      }
      const fecId = findFecId(fecData, candidate, race);
      const e = fecId ? fecData.candidates?.[fecId] : null;
      if (!e) {
        return { status: 'none', source: 'FEC', sourceShort: 'FEC', searchUrl: FEC_SEARCH };
      }
      return {
        status: 'ok',
        source: 'FEC',
        sourceShort: 'FEC',
        raised: e.totalRaised ?? null,
        spent: e.totalSpent ?? null,
        cashOnHand: e.cashOnHand ?? null,
        totalIndividual: e.totalIndividual ?? null,
        cycleLabel: '2025–2026 cycle',
        asOf: e.coverageEndDate
          ? new Date(e.coverageEndDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
          : null,
        detailUrl: e.fecUrl || null,
        searchUrl: FEC_SEARCH,
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
    normalizeName, candidateLastName, findFecId,
    gaCandidatePool, findGaFilers,
    GA_CHAMBER_MAP, GA_OFFICE_MAP,
    summary,
  };
})();
