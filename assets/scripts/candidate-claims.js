/*
 * candidate-claims.js — shared loader + renderer for campaign-submitted profile content.
 *
 * Single source of truth for the claim "firewall": campaign-submitted content is
 * always rendered inside a labeled, dated block, visually distinct from the
 * public-record profile. Public-record fields (name, party, office, votes,
 * finance) are never sourced from here.
 *
 * Used by candidate.html (full profile block + claim CTA) and race.html
 * (a small "campaign profile" badge on cards).
 *
 * Claims are keyed by candidate_key — the same value the Tally form carries as a
 * hidden field: a challenger's `id` or an incumbent's `memberId`.
 */
(function (global) {
  'use strict';

  const CLAIMS_URL = 'assets/data/candidate-claims.json';
  const FORM_BASE  = 'https://tally.so/r/q48agY';

  function basePath() {
    return window.location.pathname.includes('/votega.org-TEST/')
      ? '/votega.org-TEST/' : '/';
  }

  // race.level -> questionnaire tier, mirroring scripts/build_candidate_claim_links.py
  const TIER_BY_LEVEL = {
    'federal': 'B',
    'state': 'B',
    'state-executive': 'C',
    'state-judicial': 'D',
  };

  // Questionnaire keys in display order, grouped by tier. Rendered only if answered.
  const QUESTION_LABELS = [
    // Tier A
    ['q_why_running', 'Why are you running for this office?'],
    ['q_priority_1', 'Top priority'],
    ['q_priority_2', 'Second priority'],
    ['q_priority_3', 'Third priority'],
    ['q_background', 'What in your background prepares you for this office?'],
    ['q_first_year', 'One measurable thing you’d do in your first year'],
    ['q_overlooked', 'An important issue getting too little attention'],
    ['q_party_disagreement', 'An issue where you disagree with your own party'],
    // Tier B
    ['q_bill_intro', 'A bill you’d introduce or sponsor in your first term'],
    ['q_spend_more', 'Where Georgia should spend more'],
    ['q_spend_less', 'Where Georgia should spend less'],
    // Tier C
    ['q_statutory_power', 'A statutory power you’d use differently'],
    ['q_agency_management', 'The first thing you’d change about how the office operates'],
    ['q_office_limits', 'Something asked of this office that’s outside its authority'],
    ['q_measurable_outcome', 'What voters should hold you to at the end of your term'],
    ['q_psc_rates', 'Conditions under which you’d approve a rate increase'],
    ['q_psc_ratepayer_balance', 'Balancing ratepayers against regulated utilities'],
    // Tier D (judicial)
    ['q_legal_career', 'Legal career and prior judicial service'],
    ['q_judicial_philosophy', 'Judicial philosophy'],
    ['q_court_administration', 'Administrative or access-to-justice improvements'],
    ['q_bar_admissions', 'Bar admissions and leadership roles'],
  ];

  const LINK_LABELS = [
    ['website', 'Campaign website'],
    ['donate', 'Donate'],
    ['volunteer', 'Volunteer'],
    ['events', 'Events'],
    ['facebook', 'Facebook'],
    ['x', 'X / Twitter'],
    ['instagram', 'Instagram'],
    ['youtube', 'YouTube'],
    ['tiktok', 'TikTok'],
    ['linkedin', 'LinkedIn'],
  ];

  let _cache = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  // Escape, then turn newlines into <br> for multi-line submitted text.
  function escMultiline(s) {
    return esc(s).replace(/\r?\n/g, '<br>');
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso);
    if (isNaN(d)) return '';
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function maskEmail(email) {
    if (!email || email.indexOf('@') < 1) return '';
    const [local, domain] = email.split('@');
    return local[0] + '***@' + domain;
  }

  // Fetch and cache the claims map. Never throws — a missing/broken file just
  // means no claims, and the public-record profile renders unchanged.
  async function fetchClaims(basePath) {
    if (_cache) return _cache;
    const url = (basePath || '') + CLAIMS_URL;
    try {
      const res = await fetch(url);
      if (!res.ok) { _cache = {}; return _cache; }
      const data = await res.json();
      const claims = (data && data.claims) || {};
      // Drop `_`-prefixed template/example keys (mirrors the overrides convention).
      _cache = {};
      for (const k of Object.keys(claims)) {
        if (!k.startsWith('_')) _cache[k] = claims[k];
      }
      return _cache;
    } catch (e) {
      console.warn('candidate-claims: could not load claims', e);
      _cache = {};
      return _cache;
    }
  }

  function getClaim(claims, key) {
    if (!claims || !key) return null;
    return claims[key] || null;
  }

  // The labeled, dated block for candidate.html. Everything here is escaped —
  // this is campaign-submitted content.
  function profileBlockHtml(claim) {
    if (!claim) return '';
    const parts = [];

    const dateStr = formatDate(claim.claimedAt);
    parts.push(`<div class="claim-block">
      <div class="claim-label">
        <span class="claim-label-badge">Submitted by the campaign</span>
        ${dateStr ? `<span class="claim-label-date">${esc(dateStr)}</span>` : ''}
      </div>`);

    if (claim.bio) {
      parts.push(`<div class="claim-bio"><p>${escMultiline(claim.bio)}</p></div>`);
    }

    // Questionnaire
    const qa = (claim.questionnaire) || {};
    const answered = QUESTION_LABELS.filter(([k]) => qa[k]);
    // Priorities render as one grouped item if any are present.
    if (answered.length) {
      const rows = [];
      for (const [key, label] of QUESTION_LABELS) {
        const val = qa[key];
        if (!val) continue;
        rows.push(`<div class="claim-qa">
          <p class="claim-q">${esc(label)}</p>
          <p class="claim-a">${escMultiline(val)}</p>
        </div>`);
      }
      parts.push(`<div class="claim-questionnaire">
        <h3 class="claim-subhead">Questionnaire</h3>
        ${rows.join('')}
      </div>`);
    }

    // Recorded-vote positions (optional; grid selection TBD)
    if (claim.votes && Object.keys(claim.votes).length) {
      const vrows = Object.entries(claim.votes).map(([bill, v]) => {
        const pos = esc((v && v.position) || '');
        const note = v && v.note ? `<span class="claim-vote-note">${escMultiline(v.note)}</span>` : '';
        const label = v && v.label ? esc(v.label) : esc(bill);
        return `<li><span class="claim-vote-bill">${label}</span>
          <span class="claim-vote-pos">${pos}</span>${note}</li>`;
      });
      parts.push(`<div class="claim-votes">
        <h3 class="claim-subhead">Stated positions on recorded votes</h3>
        <ul>${vrows.join('')}</ul>
      </div>`);
    }

    // Endorsements
    const endorsements = claim.endorsements || [];
    if (endorsements.length || claim.endorsementsUrl) {
      const items = endorsements.map(e => `<li>${esc(e)}</li>`).join('');
      const urlLink = claim.endorsementsUrl
        ? `<a href="${esc(claim.endorsementsUrl)}" target="_blank" rel="noopener">Full endorsements list ↗</a>`
        : '';
      parts.push(`<div class="claim-endorsements">
        <h3 class="claim-subhead">Endorsements</h3>
        <p class="claim-unverified">Listed as claimed by the campaign. VoteGA has not independently verified these.</p>
        ${items ? `<ul>${items}</ul>` : ''}
        ${urlLink}
      </div>`);
    }

    // Links
    const links = claim.links || {};
    const linkEls = LINK_LABELS
      .filter(([k]) => links[k])
      .map(([k, label]) => `<a href="${esc(links[k])}" target="_blank" rel="noopener">${esc(label)} ↗</a>`);
    if (linkEls.length) {
      parts.push(`<div class="claim-links">${linkEls.join('')}</div>`);
    }

    parts.push(`</div>`);
    return parts.join('');
  }

  // Small chip for race.html cards.
  function badgeHtml(claim) {
    if (!claim) return '';
    return `<span class="claim-card-badge" title="This candidate has added campaign-submitted content">✓ Campaign profile</span>`;
  }

  // Build the prefilled Tally claim link for an unclaimed candidate, reproducing
  // the mail-merge builder so an organically-found profile claims correctly.
  function claimLink(opts) {
    const params = new URLSearchParams({
      candidate_key: opts.key || '',
      key_type: opts.keyType || '',
      member_source: opts.memberSource || '',
      race_id: opts.raceId || '',
      candidate_name: opts.name || '',
      race_label: opts.raceLabel || '',
      tier: TIER_BY_LEVEL[opts.level] || '',
      onfile_email_hint: maskEmail(opts.email || ''),
      src: opts.src || 'candidate_page',
    });
    return `${FORM_BASE}?${params.toString()}`;
  }

  // The "Are you this candidate?" CTA for candidate.html (shown when unclaimed).
  function claimCtaHtml(opts) {
    const href = claimLink(opts);
    const who = opts.name ? esc(opts.name) : 'this candidate';
    return `<div class="claim-cta">
      <p class="claim-cta-text">Are you ${who}, or part of this campaign?
        This profile is built from public records — you can add a biography,
        a photo, and your answers to the candidate questionnaire. It’s free.</p>
      <a class="claim-cta-btn" href="${href}" target="_blank" rel="noopener">Claim this profile →</a>
      <a class="claim-cta-learn" href="${basePath()}candidates/">How it works</a>
    </div>`;
  }

  global.CandidateClaims = {
    fetchClaims,
    getClaim,
    profileBlockHtml,
    badgeHtml,
    claimCtaHtml,
    claimLink,
    esc,
    tierForLevel: (lvl) => TIER_BY_LEVEL[lvl] || '',
  };
})(window);
