/*
 * results-contest.js — how a contest is read, in one place.
 *
 * Two pages render the same contest objects: the results pages via
 * _layouts/election_results.html, and the "Earlier This Cycle" panel on
 * race.html. Their markup differs for good reason — a full results card versus a
 * compact recap — but they were also each deciding, separately, what the numbers
 * *mean*. The two answers had drifted:
 *
 *   Ossoff, unopposed in the 2026 Democratic Senate primary
 *     results page: 100.0%        race page: —
 *   US Senate Republican primary, no one above 50%
 *     results page: ✓ on Collins and Dooley, "Advances to the runoff"
 *     race page:    ✓ on Collins only
 *
 * The second one is not cosmetic: one page told a visitor two candidates
 * advanced to the runoff and the other told them one did.
 *
 * This module owns the reading — contest status, how many finishers advance,
 * what a percentage cell says. Each page keeps its own markup and CSS and asks
 * here for the answers.
 *
 * `cfg` is { mode, advances }, from the results page's `results_mode` and
 * `runoff_advances` front matter:
 *   mode 'round'  leader wins outright above 50%, otherwise the top N advance
 *   mode 'final'  the leader wins (a runoff or general)
 */
(function (global) {
  'use strict';

  function percent(votes, total) {
    return total ? ((Number(votes) || 0) / total) * 100 : 0;
  }

  // 'no-results' | 'uncontested' | 'winner' | 'runoff'
  function status(contest, cfg) {
    var cands = (contest && contest.candidates) || [];
    if (!cands.length || !contest.totalVotes) return 'no-results';
    if (cands.length === 1) return 'uncontested';
    if (cfg && cfg.mode === 'final') return 'winner';
    return percent(cands[0].votes, contest.totalVotes) > 50 ? 'winner' : 'runoff';
  }

  // How many rows carry the ✓. A runoff sends `advances` finishers on, not one.
  function advanceCount(contestStatus, cfg) {
    if (contestStatus === 'winner') return 1;
    if (contestStatus === 'runoff') {
      var n = Number(cfg && cfg.advances);
      return n > 0 ? n : 2;
    }
    return 0;
  }

  function advanceTitle(contestStatus, cfg) {
    return (cfg && cfg.mode === 'round' && contestStatus === 'runoff')
      ? 'Advances to the runoff'
      : 'Leads';
  }

  // A lone candidate at 100% is an unopposed ballot line, not a landslide — show
  // no number, so it cannot be read as a margin.
  function percentText(contest, candidate, contestStatus) {
    if (contestStatus === 'no-results' || contestStatus === 'uncontested') return '—';
    return percent(candidate.votes, contest.totalVotes).toFixed(1) + '%';
  }

  // The bar still fills for an unopposed line — it just isn't labelled.
  function barWidth(contest, candidate, contestStatus) {
    if (contestStatus === 'no-results') return 0;
    if (contestStatus === 'uncontested') return 100;
    return Math.min(percent(candidate.votes, contest.totalVotes), 100);
  }

  function partyLabel(party) {
    return party === 'rep' ? 'Republican' : party === 'dem' ? 'Democrat' : 'Nonpartisan';
  }

  /*
   * An office can carry a standing note that the vote numbers cannot express:
   * the Atlantic Judicial Circuit's District Attorney contest on 3 Nov 2026 is
   * a SPECIAL PRIMARY with a 1 Dec runoff, not a general election, and a card
   * that just says "District Attorney" tells a voter the wrong thing about what
   * their vote decides.
   *
   * The notes live in the results page's own front matter, deliberately NOT in
   * the results data: _data/election_results/*.json is rebuilt wholesale from
   * the Secretary of State's CSV on election night, which would drop any field
   * added here exactly when the page matters most. Front matter survives that
   * rebuild untouched.
   *
   * Matching is normalized because the key has to survive the handover from the
   * ballot preview to that CSV. Both sides spell the office "District Attorney
   * - Atlantic Judicial Circuit" today, but case, dash style, doubled spaces and
   * the CSV's trailing "- Rep" / "- Dem" party suffix are all things that drift
   * between the two sources without changing which office is meant.
   */
  function normalizeOffice(value) {
    return String(value == null ? '' : value)
      .toLowerCase()
      .replace(/[‐-―]/g, '-')      // en dash, em dash, figure dash
      .replace(/\s*-\s*(rep|dem)\s*$/, '')     // the CSV's party suffix
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  /* The note for `office`, as { label, text }, or null. A bare string is
   * accepted as a note with no label. */
  function officeNote(notes, office) {
    if (!notes || typeof notes !== 'object') return null;
    var want = normalizeOffice(office);
    if (!want) return null;
    for (var key in notes) {
      if (!Object.prototype.hasOwnProperty.call(notes, key)) continue;
      if (normalizeOffice(key) !== want) continue;
      var note = notes[key];
      if (typeof note === 'string') return note ? { label: '', text: note } : null;
      if (note && note.text) return { label: note.label || '', text: note.text };
      return null;
    }
    return null;
  }

  /* Configured notes that match no office on the page. A note that silently
   * matches nothing is the failure mode worth surfacing: it looks identical to
   * having no note at all, so the caller logs these rather than discarding them. */
  function unmatchedNotes(notes, offices) {
    if (!notes || typeof notes !== 'object') return [];
    var present = {};
    (offices || []).forEach(function (o) { present[normalizeOffice(o)] = true; });
    return Object.keys(notes).filter(function (k) { return !present[normalizeOffice(k)]; });
  }

  global.ResultsContest = {
    percent: percent,
    status: status,
    advanceCount: advanceCount,
    advanceTitle: advanceTitle,
    percentText: percentText,
    barWidth: barWidth,
    partyLabel: partyLabel,
    normalizeOffice: normalizeOffice,
    officeNote: officeNote,
    unmatchedNotes: unmatchedNotes,
  };
})(window);
