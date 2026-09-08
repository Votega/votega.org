// Shared VoteGA front-end helpers, loaded on every page from _includes/head.html
// (synchronously in <head>, so these are defined before any page's inline code
// runs). Add only tiny, page-agnostic helpers here.
(function () {
  // Base URL prefix for building absolute asset/data paths. The site is served at
  // the domain root (CNAME www.votega.org), so this is always '/'. Kept as a
  // function — the single home for a value that was copy-pasted into ~16 pages and
  // entity includes — so the ~93 call sites and the "resolve through getBasePath"
  // convention keep working, and a non-root deployment could restore the logic here.
  if (typeof window.getBasePath !== 'function') {
    window.getBasePath = function getBasePath() {
      return '/';
    };
  }
})();
