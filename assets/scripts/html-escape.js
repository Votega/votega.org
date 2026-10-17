/*
 * html-escape.js — one HTML escaper for every page.
 *
 * There were fifteen independent copies, in two behaviours. Ten escaped
 * `& < > " '` and guarded null; five escaped only `& < > "` and passed null
 * through `String()`, so a missing field rendered the literal word "undefined"
 * and an apostrophe survived into the markup. Which one a page got was an
 * accident of when it was written.
 *
 * That split was not theoretical. `_layouts/election_results.html` held one of
 * the four-character copies and also built a search attribute without calling
 * it at all, so a ballot name like `Earl L. "Buddy" Carter` closed the
 * attribute early and searching "carter" hid the race instead of finding it.
 * One escaper, used everywhere, is the fix that keeps working.
 *
 * Usage — pages keep their existing local name, so call sites are untouched:
 *   const escHtml = VoteGA.escapeHtml;
 *
 * Escapes the single quote as well as the double, so output is safe in a
 * single-quoted attribute too, and returns '' for null/undefined rather than
 * "null"/"undefined".
 *
 * safeUrl() is the companion for links. Escaping a URL keeps it inside its
 * href attribute, but `javascript:alert(1)` contains no escapable character
 * and survives intact, so a link built from data the page did not author needs
 * the scheme checked as well:
 *   <a href="${VoteGA.safeUrl(doc.html_url)}">
 */
(function (global) {
  'use strict';

  var ENTITIES = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  };

  function escapeHtml(value) {
    return (value == null ? '' : String(value))
      .replace(/[&<>"']/g, function (c) { return ENTITIES[c]; });
  }

  // Anything but an absolute http(s) URL, a site-relative path, or a bare
  // fragment becomes '#'. That rejects javascript:, data: and vbscript:
  // without maintaining a blocklist of the schemes browsers happen to run.
  function safeUrl(value) {
    var raw = (value == null ? '' : String(value)).trim();
    return /^(https?:\/\/|\/|#)/i.test(raw) ? escapeHtml(raw) : '#';
  }

  global.VoteGA = global.VoteGA || {};
  global.VoteGA.escapeHtml = escapeHtml;
  global.VoteGA.safeUrl = safeUrl;
})(window);
