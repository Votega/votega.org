// Lame-duck departure labels on a SITTING member's own page (D6, decided 2026-11-23).
//
// Between certification and the rollover, a departing member is still in office and
// still on the live roster. Their approved label (ga-departure-labels.json /
// federal-departure-labels.json) shows on their live page until their term ends, then
// drops off by itself, with no manual step:
//   * metadata.termEnds: from that date (the viewer's local day) no label shows;
//   * metadata.session (GA): the label shows only while the live roster is that
//     biennium, so the rollover's new roster retires it even before termEnds is read;
//   * a former-member page or a frozen biennium view never uses this (they have their own).
// Pure, so scripts/test_departure_label_js.py can run it under node.
(function (root) {
  function todayIso(now) {
    const d = now || new Date();
    const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }
  // ctx: { live: bool, former: bool, session: string|null, now: Date }
  function lameDuckLabel(doc, id, ctx) {
    if (!doc || !doc.labels || id == null || !ctx || !ctx.live || ctx.former) return null;
    const meta = doc.metadata || {};
    if (!meta.termEnds) return null;               // no end date, no live label: fail closed
    if (todayIso(ctx.now) >= meta.termEnds) return null;
    if (meta.session && meta.session !== ctx.session) return null;
    const entry = doc.labels[String(id)];
    return entry && entry.label ? entry : null;
  }
  // "2027-01-11" -> "January 11, 2027"
  function longDate(iso) {
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }
  const api = { lameDuckLabel, longDate, todayIso };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.VotegaDeparture = api;
})(typeof window !== 'undefined' ? window : this);
