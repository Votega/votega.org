// Shared VoteGA front-end helpers, loaded on every page from _includes/head.html
// (synchronously in <head>, so these are defined before any page's inline code
// runs). Add only tiny, page-agnostic helpers here.
(function () {
  // Base URL prefix: '/' in production, '/votega.org-TEST/' on the staging mirror.
  // Was copy-pasted verbatim into ~16 pages and entity includes; consolidated here.
  if (typeof window.getBasePath !== 'function') {
    window.getBasePath = function getBasePath() {
      return window.location.pathname.includes('/votega.org-TEST/')
        ? '/votega.org-TEST/'
        : '/';
    };
  }
})();
