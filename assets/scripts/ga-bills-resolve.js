/*
 * ga-bills-resolve.js — which bill does a link mean? (VoteGA.billsResolve)
 *
 * Bill numbers restart every General Assembly: HB 943 in 2027 is a different bill
 * from HB 943 in 2025-26. So an identifier alone names a bill only WITHIN a
 * biennium, and every function here treats it that way:
 *   - legislationId is the bill's own id, unique across bienniums, and wins when
 *     a link carries one. If it matches nothing, the answer is "not in this file",
 *     never "whichever bill reuses that number".
 *   - a bare identifier resolves inside the file it is given (the current
 *     biennium's), preferring the session a link names.
 *   - a card's anchor carries its session, so two bills sharing a number can never
 *     share an anchor.
 *
 * Pure functions only (no DOM), so tests/js can run the shipped bytes.
 */
(function (global) {
  'use strict';

  var VoteGA = global.VoteGA = global.VoteGA || {};

  // '2025_26' -> '2025-2026' (the form ga-bills.json metadata.biennium uses).
  function tagToBiennium(tag) {
    var m = /^(\d{4})_(\d{2})$/.exec(String(tag || ''));
    if (!m) return null;
    var start = parseInt(m[1], 10);
    if ((start + 1) % 100 !== parseInt(m[2], 10)) return null;
    return start + '-' + (start + 1);
  }

  // '2025-2026' or '2025_26' -> '2025_26'; anything else -> null.
  function toTag(value) {
    var s = String(value || '');
    if (tagToBiennium(s)) return s;
    var m = /^(\d{4})-(\d{4})$/.exec(s);
    if (m && parseInt(m[2], 10) === parseInt(m[1], 10) + 1) return m[1] + '_' + m[2].slice(2);
    return null;
  }

  // Which frozen biennium does a session id belong to? A regular session id is its
  // own tag ('2025_26'); a special session ('2026_ss') belongs to the biennium whose
  // two years include it. `tags` are the frozen tags on offer. Returns a tag or null.
  function tagForSession(sessionId, tags) {
    var s = String(sessionId || '');
    var list = tags || [];
    if (tagToBiennium(s)) return list.indexOf(s) !== -1 ? s : null;
    var m = /^(\d{4})_/.exec(s);
    if (!m) return null;
    var year = parseInt(m[1], 10);
    for (var i = 0; i < list.length; i++) {
      var start = parseInt(list[i].slice(0, 4), 10);
      if (year === start || year === start + 1) return list[i];
    }
    return null;
  }

  function normalizeIdentifier(s) {
    return String(s == null ? '' : s).replace(/\s+/g, '').toUpperCase();
  }

  function clean(part) { return String(part == null ? '' : part).replace(/[^A-Za-z0-9_]/g, ''); }

  // 'bill-2025_26-HB943'. The session is part of the key; a bill with no session
  // (older records) gets 'x' so the shape stays uniform.
  function anchorId(bill) {
    return 'bill-' + (clean(bill.session) || 'x') + '-' + clean(String(bill.identifier).replace(/\s+/g, ''));
  }

  // The pre-D2 anchor, 'bill-HB943', still honoured when it arrives as a #hash.
  function legacyAnchorId(identifier) {
    return 'bill-' + clean(String(identifier).replace(/\s+/g, ''));
  }

  /**
   * findBill(bills, { legislationId, identifier, session }) -> bill | null
   * legislationId present: match on it alone (never fall back to the identifier).
   * Otherwise match the identifier, preferring `session` when a link names one.
   */
  function findBill(bills, q) {
    q = q || {};
    var list = bills || [];
    var i;
    if (q.legislationId != null && q.legislationId !== '') {
      for (i = 0; i < list.length; i++) {
        if (String(list[i].legislationId) === String(q.legislationId)) return list[i];
      }
      return null;
    }
    if (!q.identifier) return null;
    var want = normalizeIdentifier(q.identifier);
    var first = null;
    for (i = 0; i < list.length; i++) {
      if (normalizeIdentifier(list[i].identifier) !== want) continue;
      if (q.session && list[i].session === q.session) return list[i];
      if (!first) first = list[i];
    }
    // A link that names a session and finds no such bill there is a miss, not a
    // licence to open the same number from another session.
    return q.session ? null : first;
  }

  /**
   * A link is "bare" when nothing in it says which biennium it means: an identifier
   * with no legislationId, no session and no biennium. After a rollover such a link
   * may refer to either General Assembly, so the page says so rather than guessing.
   */
  function isBareLink(q) {
    q = q || {};
    return !!q.identifier && !q.legislationId && !q.session && !q.biennium;
  }

  VoteGA.billsResolve = {
    tagToBiennium: tagToBiennium,
    toTag: toTag,
    tagForSession: tagForSession,
    normalizeIdentifier: normalizeIdentifier,
    anchorId: anchorId,
    legacyAnchorId: legacyAnchorId,
    findBill: findBill,
    isBareLink: isBareLink
  };
}(window));
