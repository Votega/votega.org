/*
 * votega-nominations.js — the nomination filter on senators' Voting History
 * (_includes/entity/federal-legislator.html).
 *
 * Holds the page's wording (filter options and terms, in this one place), the chart
 * caption and note for a selected Type, and the en bloc rows: one roll call on a
 * group of nominees, with a "Show all N nominations" list and search over the names.
 * The names live in assets/data/federal-en-bloc-nominees.json, fetched only when a
 * reader opens a list or searches. A list is shown complete or not at all.
 *
 * Needs html-escape.js and votega-votes-table.js. Exposed on
 * window.VotegaNominations; tested by tests/js/nominations.test.js, so nothing here
 * may touch `document` or the network at load time.
 *
 * Definitions are checked against https://www.senate.gov/about/research-tools/glossary.htm
 * and, for cloture and en bloc votes, CRS Report R48729. They describe procedure,
 * never why a senator voted a given way.
 */
window.VotegaNominations = (function () {
  'use strict';

  var TYPES = [
    { value: 'all', label: 'All votes',
      description: 'Every recorded roll call vote, on nominations, legislation and everything else.' },
    { value: 'confirm', label: 'Confirmation votes', noun: 'confirmation vote',
      description: 'The Senate’s final yes-or-no vote on whether a nominee gets the job.' },
    { value: 'nomination', label: 'All nomination votes', noun: 'nomination vote',
      description: 'Confirmation votes, plus the earlier and procedural votes about nominees.' },
    { value: 'other', label: 'Legislation and other',
      description: 'Votes that are not about nominations, such as bills, resolutions and amendments, including procedural votes on them.' },
  ];

  // `motions` are the wordings of the Motion column that a term explains. Terms
  // without them are matched by `shows(meta, entry)`.
  var TERMS = [
    { term: 'Nomination', shownAs: 'the subject of the vote',
      shows: function (meta) { return !!meta.category; },
      definition: 'A person the President has put forward for a job that needs Senate approval, such as a Cabinet secretary, federal judge, ambassador or senior military officer.' },
    { term: 'Confirmation vote', motions: ['On the Nomination'],
      definition: 'The final vote. “Yea” supports confirming the nominee and “Nay” opposes it.' },
    { term: 'Cloture', motions: ['On the Cloture Motion', 'On Cloture on the Motion to Proceed'],
      definition: 'A vote to limit further debate so that a final vote can happen. It is not the final vote itself. On nominations it needs a simple majority of senators voting; on most legislation it needs three-fifths of the Senate, usually 60 votes. Groups of nominees, and the resolutions that allow them, have needed only a simple majority since September 2025. Before that change, such a vote could fail with more Yeas than Nays.' },
    { term: 'Motion to proceed', motions: ['On the Motion to Proceed'],
      definition: 'A vote on whether to take the matter up.' },
    { term: 'Motion to reconsider', motions: ['On the Motion to Reconsider'],
      definition: 'A vote on whether to revisit an earlier vote.' },
    { term: 'Motion to table', motions: ['On the Motion to Table'],
      definition: 'A vote to set a question aside. “Yea” supports setting it aside, which in effect defeats it.' },
    { term: 'Decision of the chair', motions: ['On the Decision of the Chair'],
      definition: 'A vote on whether to uphold the presiding officer’s ruling on a Senate rule. “Yea” supports the ruling.' },
    { term: 'En bloc', shownAs: 'labeled in the row title',
      shows: function (meta) { return isEnBloc(meta); },
      definition: 'One vote covering a group of nominees. The senator’s vote applies to the whole group, and does not show a view on any one person in it.' },
    // "On the Resolution" is defined only for the resolution about nominees.
    { term: 'En bloc resolution', shownAs: 'On the Resolution (S.Res.)', resolutionMotion: 'On the Resolution',
      shows: function (meta) { return isEnBlocResolution(meta); },
      definition: 'A resolution that lets the Senate consider a group of nominees together. Passing it does not confirm anyone.' },
    { term: 'Not voting', shownAs: 'Not Voting, in the Vote column',
      shows: function (meta, entry) { return entry.vote === 'Not Voting'; },
      definition: 'The senator did not cast a vote on this roll call.' },
  ];

  var CHART_CAPTION = 'Counts are roll calls, not nominees. One en bloc vote can cover many nominees.';
  var CAVEAT = 'The Senate took one vote on this whole group. A senator&rsquo;s vote does not show a view on any one nominee.';
  var MATCHES_SHOWN = 3;

  function esc(value) { return window.VoteGA.escapeHtml(value); }
  function table() { return window.VotegaVotesTable; }

  function isEnBlocResolution(meta) {
    return !!(meta && meta.category && /^S\.Res\./.test(meta.bill || ''));
  }

  // A counted group, or the uncounted "En bloc" row a Voteview record gets.
  function isEnBloc(meta) {
    if (!meta || !meta.category) return false;
    return meta.nomineeCount > 1 || meta.title === 'En bloc';
  }

  function hasNominations(entries, index) {
    return entries.some(function (e) { return !!(index[e.voteId] || {}).category; });
  }

  // The Type options this record can fill, each with its count. All votes is first.
  function typeOptions(entries, index) {
    return TYPES.map(function (t) {
      var count = entries.filter(table().makeMatcher({ type: t.value }, index)).length;
      return { value: t.value, label: t.label + ' (' + count + ')', description: t.description, count: count };
    }).filter(function (t) { return t.value === 'all' || t.count > 0; });
  }

  // null means "the page's own caption".
  function chartCaption(type) {
    return type === 'confirm' || type === 'nomination' ? CHART_CAPTION : null;
  }

  function scopeNote(type, count, filtered) {
    var t = TYPES.filter(function (x) { return x.value === type; })[0] || TYPES[0];
    var plural = count === 1 ? '' : 's';
    var what = t.noun ? t.noun + plural
      : type === 'other' ? 'vote' + plural + ' on legislation and other matters'
        : 'vote' + plural;
    return 'The breakdown above covers all ' + count + ' ' + what
      + (filtered ? ', not the filtered list.' : '.');
  }

  function definitionFor(motion) {
    var hit = TERMS.filter(function (t) {
      return (t.motions && t.motions.indexOf(motion) !== -1) || t.resolutionMotion === motion;
    })[0];
    return hit ? hit.definition : null;
  }

  // Only the terms this record shows, plus the four filter options.
  function legendHtml(entries, index) {
    var motions = {};
    var unknown = {};
    entries.forEach(function (e) {
      var meta = index[e.voteId] || {};
      if (!meta.motionText) return;
      motions[meta.motionText] = true;
      if (meta.category && !definitionFor(meta.motionText)) unknown[meta.motionText] = true;
    });
    Object.keys(unknown).forEach(function (m) {
      console.warn('votega-nominations: no definition for the motion "' + m + '"');
    });

    var terms = TERMS.map(function (t) {
      var shownAs = t.shownAs;
      if (t.motions) {
        var present = t.motions.filter(function (m) { return motions[m]; });
        if (!present.length) return '';
        shownAs = present.join(', ');
      } else if (!entries.some(function (e) { return t.shows(index[e.voteId] || {}, e); })) {
        return '';
      }
      return '<dt>' + esc(t.term) + '<span class="vote-term-shown">Shown as: ' + esc(shownAs) + '</span></dt>'
        + '<dd>' + esc(t.definition) + '</dd>';
    }).join('');

    var options = TYPES.map(function (t) {
      return '<dt>' + esc(t.label) + '</dt><dd>' + esc(t.description) + '</dd>';
    }).join('');

    return '<details class="vote-terms">'
      + '<summary><i class="fa-solid fa-circle-question" aria-hidden="true"></i> What do these terms mean?</summary>'
      + '<p class="vote-terms-head">Filter options</p><dl>' + options + '</dl>'
      + '<p class="vote-terms-head">Terms in the table</p><dl>' + terms + '</dl>'
      + '</details>';
  }

  // https://www.congress.gov/nomination/119th-congress/55/25 for PN55-25; a
  // nomination that was never split into parts (PN18) has no last segment.
  function nominationUrl(congress, pn) {
    var m = /^PN(\d+)(?:-(\d+))?$/.exec(pn || '');
    var n = Number(congress);
    if (!m || !n) return null;
    var tens = n % 100, ones = n % 10;
    var suffix = tens >= 11 && tens <= 13 ? 'th' : ones === 1 ? 'st' : ones === 2 ? 'nd' : ones === 3 ? 'rd' : 'th';
    return 'https://www.congress.gov/nomination/' + n + suffix + '-congress/' + m[1] + (m[2] ? '/' + m[2] : '');
  }

  function senateVoteUrl(voteId) {
    var m = /^S(\d+)_(\d)_(\d{5})$/.exec(voteId || '');
    if (!m) return null;
    return 'https://www.senate.gov/legislative/LIS/roll_call_votes/vote' + m[1] + m[2]
      + '/vote_' + m[1] + '_' + m[2] + '_' + m[3] + '.htm';
  }

  function listFor(doc, voteId, meta) {
    if (!doc) return null;
    var list = (doc.batches || {})[(doc.votes || {})[voteId]];
    return list && list.length === meta.nomineeCount ? list : null;
  }

  // Name, state or position; the source title only where it could not be split, so
  // that "to be" does not match every batch.
  function matchNominees(list, q) {
    if (!q) return [];
    var norm = table().normalizeQuery;
    return list.filter(function (n) {
      var fields = n.name ? [n.name, n.state, n.position] : [n.title];
      return fields.some(function (f) { return norm(f).indexOf(q) !== -1; });
    });
  }

  // "name, of state, to be position" exactly as the source has it, the name linked.
  function nomineeHtml(n, congress) {
    var title = n.title || n.name || n.pn || '';
    var lead = n.name && title.indexOf(n.name) === 0 ? n.name : title;
    var url = nominationUrl(congress, n.pn);
    var linked = url
      ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(lead) + '</a>'
      : esc(lead);
    return linked + esc(title.slice(lead.length));
  }

  function listHtml(list, congress) {
    return '<ol class="vote-nominee-list">'
      + list.map(function (n) { return '<li>' + nomineeHtml(n, congress) + '</li>'; }).join('')
      + '</ol>';
  }

  function listBodyHtml(voteId, meta, doc) {
    var list = listFor(doc, voteId, meta);
    return list
      ? listHtml(list, (doc.metadata || {}).congress)
      : '<p class="vote-nominee-missing"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> '
        + 'The nominee list could not be loaded. The official roll call on Senate.gov names every nominee.</p>';
  }

  // What goes under an en bloc row's title; '' for every other row. `loader` is
  // only read here, never started: the file waits for a reader to ask.
  function rowHtml(voteId, meta, loader, q) {
    if (!isEnBloc(meta)) return '';
    var html = '<div class="vote-enbloc">';
    if (meta.nomineeCount > 1) {
      var doc = loader && loader.doc();
      var list = listFor(doc, voteId, meta);
      var matched = list ? matchNominees(list, table().normalizeQuery(q || '')) : [];
      if (matched.length) {
        var more = matched.length - MATCHES_SHOWN;
        html += '<p class="vote-nominee-match">Matched nominee' + (matched.length === 1 ? '' : 's') + ': '
          + matched.slice(0, MATCHES_SHOWN).map(function (n) {
              return nomineeHtml(n, doc.metadata.congress);
            }).join('; ')
          + (more > 0 ? '; and ' + more + ' more' : '') + '</p>';
      }
      html += '<details class="vote-nominees" data-nominees="' + esc(voteId) + '">'
        + '<summary>Show all ' + esc(meta.nomineeCount) + ' nominations</summary>'
        + '<div class="vote-nominees-body">' + (doc ? listBodyHtml(voteId, meta, doc) : '') + '</div>'
        + '</details>';
    } else {
      html += '<p class="vote-nominee-missing">Nominee names are not available yet.</p>';
    }
    var url = senateVoteUrl(voteId);
    return html + '<p class="vote-enbloc-note">' + CAVEAT + '</p>'
      + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">Official roll call on Senate.gov</a>' : '')
      + '</div>';
  }

  // For VotegaVotesTable.makeMatcher: does a nominee behind this row match?
  function extraMatcher(loader, index) {
    return function (entry, q) {
      var meta = index[entry.voteId] || {};
      var list = meta.nomineeCount > 1 && listFor(loader && loader.doc(), entry.voteId, meta);
      return !!list && matchNominees(list, q).length > 0;
    };
  }

  // One line on what a search could not cover; '' when it covers every name.
  function searchStatus(loader, entries, index, q) {
    if (!loader || !table().normalizeQuery(q || '')) return '';
    if (loader.failed()) return 'En bloc nominee names could not be loaded, so this search does not cover them.';
    var doc = loader.doc();
    if (!doc) return 'Loading en bloc nominee names…';
    var uncovered = entries.filter(function (e) {
      var meta = index[e.voteId] || {};
      return isEnBloc(meta) && !listFor(doc, e.voteId, meta);
    }).length;
    if (!uncovered) return '';
    var one = uncovered === 1;
    return 'Names for ' + uncovered + ' en bloc vote' + (one ? '' : 's')
      + ' are not available yet, so this search does not cover ' + (one ? 'it.' : 'them.');
  }

  // Fetches the nominee file once, when first asked. A failure resolves to null and
  // can be retried; it never rejects.
  function createLoader(url, fetchFn) {
    var promise = null, doc = null, failed = false;
    return {
      doc: function () { return doc; },
      failed: function () { return failed; },
      load: function () {
        if (!promise) {
          failed = false;
          promise = Promise.resolve()
            .then(function () { return fetchFn ? fetchFn(url) : window.fetch(url); })
            .then(function (r) {
              if (!r.ok) throw new Error('HTTP ' + r.status);
              return r.json();
            })
            .then(function (d) {
              if (!d || !d.batches || !d.votes) throw new Error('unexpected file shape');
              doc = d;
              return d;
            })
            .catch(function (err) {
              console.warn('Could not load the en bloc nominee lists:', err);
              failed = true;
              promise = null;
              return null;
            });
        }
        return promise;
      },
    };
  }

  return {
    TYPES: TYPES,
    TERMS: TERMS,
    isEnBloc: isEnBloc,
    hasNominations: hasNominations,
    typeOptions: typeOptions,
    chartCaption: chartCaption,
    scopeNote: scopeNote,
    definitionFor: definitionFor,
    legendHtml: legendHtml,
    nominationUrl: nominationUrl,
    senateVoteUrl: senateVoteUrl,
    listFor: listFor,
    matchNominees: matchNominees,
    listHtml: listHtml,
    listBodyHtml: listBodyHtml,
    rowHtml: rowHtml,
    extraMatcher: extraMatcher,
    searchStatus: searchStatus,
    createLoader: createLoader,
  };
})();
