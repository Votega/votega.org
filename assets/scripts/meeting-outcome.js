/*
 * meeting-outcome.js: one way to show what the minutes record for a motion.
 *
 * Shared by the place page's recorded-votes panel (local-meetings.js, where a
 * motion carries name lists) and the topic pages' follow-through rows
 * (topic-index.js, where it carries counts). See the follow-through convention
 * in CLAUDE.md.
 *
 *   VoteGAOutcome.chip(motion)    result chip: green only for adopted/passed,
 *                                 amber only for failed, neutral for every step
 *                                 in between (held, referred, recommended ...)
 *   VoteGAOutcome.tally(motion)   "11–0", "Unanimous", or ""
 *   VoteGAOutcome.flags(motion)   notes a reader must see: the minutes' own text
 *                                 contradicts the tally; where the item goes next
 *
 * The label is the body's own wording ("Adopted substitute", "Returned as held"),
 * so a step is never dressed up as a final outcome.
 */
(function (global) {
  'use strict';

  function esc(v) { return global.VoteGA.escapeHtml(v == null ? '' : String(v)); }
  function count(v) { return Array.isArray(v) ? v.length : (v || 0); }

  var STEP_ICON = {
    held: 'fa-pause', referred: 'fa-share', recommended: 'fa-thumbs-up',
    adversed: 'fa-thumbs-down', filed: 'fa-folder', amended: 'fa-pen',
    scheduled: 'fa-calendar', tabled: 'fa-pause', withdrawn: 'fa-rotate-left',
    completed: 'fa-check', 'no-action': 'fa-minus'
  };

  function chip(mo) {
    if (!mo) return '';
    var label = mo.resultText;
    if (mo.result === 'passed') {
      return '<span class="cmv-result cmv-passed"><i class="fa-solid fa-check" aria-hidden="true"></i> ' +
        esc(label || 'Passed') + '</span>';
    }
    if (mo.result === 'failed') {
      return '<span class="cmv-result cmv-failed"><i class="fa-solid fa-xmark" aria-hidden="true"></i> ' +
        esc(label || 'Failed') + '</span>';
    }
    if (!label) return '';
    var icon = STEP_ICON[mo.resultClass] || 'fa-circle-info';
    return '<span class="cmv-result cmv-step"><i class="fa-solid ' + icon + '" aria-hidden="true"></i> ' +
      esc(label) + '</span>';
  }

  function tally(mo) {
    if (!mo) return '';
    if (mo.tally && mo.tally.length === 2) return mo.tally[0] + '–' + mo.tally[1];
    if (mo.unanimous) return 'Unanimous';
    var y = count(mo.yes), n = count(mo.no);
    return (y || n) ? y + '–' + n : '';
  }

  function flags(mo) {
    if (!mo) return '';
    var out = '';
    if (mo.textDisagrees) {
      out += '<span class="cmv-flag"><i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i> ' +
        'The minutes’ own account of this vote disagrees with the recorded tally; read the minutes</span>';
    }
    if (mo.next) out += '<span class="cmv-next">Next: ' + esc(mo.next) + '</span>';
    return out;
  }

  global.VoteGAOutcome = { chip: chip, tally: tally, flags: flags };
})(window);
