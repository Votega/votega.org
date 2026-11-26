/*
 * ElectionsView — what the candidates page (elections.html) shows, kept apart
 * from the DOM so it can be tested (tests/js/elections-view.test.js).
 *
 * `filters` is the page's TAB_FILTER map: tab id -> predicate on a race.
 */
(function () {
  'use strict';

  // The first tab, in tab-bar order, holding a race in this phase. The first tab
  // when none does.
  function firstTabWithRaces(activeRaces, phase, tabs, filters) {
    const inPhase = activeRaces.filter(r => r.activePhase === phase);
    return tabs.find(tab => inPhase.some(filters[tab])) || tabs[0];
  }

  // True when a tab is empty because its races for this election are over: it
  // lists nothing in the phase, but decided races held on this date belong to it.
  // The date matters: a runoff certified earlier in the cycle says nothing about
  // a later one.
  function isDecidedTab(activeRaces, decidedRaces, phase, date, filter) {
    if (activeRaces.some(r => r.activePhase === phase && filter(r))) return false;
    return decidedRaces.some(r => r.activePhase === phase
      && r.phases?.[phase]?.electionDate === date && filter(r));
  }

  window.ElectionsView = { firstTabWithRaces, isDecidedTab };
})();
