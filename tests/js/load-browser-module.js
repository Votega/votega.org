/*
 * load-browser-module.js — run a browser asset under `node --test`.
 *
 * The site's shared scripts are plain IIFEs that assign themselves onto `window`
 * (campaign-finance.js, votega-core.js, html-escape.js). That is the right shape
 * for a static site with no build step, and nothing here asks them to change: we
 * evaluate the real file against a stub global instead, so the tests exercise the
 * same bytes the browser gets.
 *
 * Because the asset is evaluated, not imported, a module under test must not touch
 * `document` at load time — only inside its functions.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');

/**
 * Evaluates one or more browser assets (paths relative to the repo root) against a
 * shared stub `window`, in the order given, and returns that stub.
 *
 * Load order matters exactly as it does in the page: html-escape.js first, since
 * the other modules call VoteGA.escapeHtml.
 */
function loadBrowserModules(...relativePaths) {
  const win = {};
  win.window = win;          // assets that reference `window` inside functions
  for (const rel of relativePaths) {
    const file = path.join(REPO_ROOT, rel);
    const src = fs.readFileSync(file, 'utf8');
    // eslint-disable-next-line no-new-func
    new Function('window', src)(win);
  }
  return win;
}

module.exports = { loadBrowserModules, REPO_ROOT };
