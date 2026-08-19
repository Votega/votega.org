/*
 * a11y-tabs.js — ARIA wiring for the site's tab bars.
 *
 * The site grew eight independent tab UIs, each with its own markup, class
 * names and activation code. They are all real <button>s, so they are
 * focusable, but a screen reader announced a row of unlabelled buttons with no
 * indication of which was selected or what it controlled.
 *
 * Rather than rewrite eight activation handlers, this enhancer layers the ARIA
 * tab pattern on top of whatever each page already does:
 *
 *   - assigns role=tablist / role=tab / role=tabpanel and the id wiring
 *   - mirrors each page's own "active" class into aria-selected
 *   - implements roving tabindex plus Arrow/Home/End keys, delegating the
 *     actual switch back to the page by calling .click()
 *
 * Because state is *observed* rather than owned, a page can keep toggling its
 * class however it likes and the ARIA stays correct.
 *
 * Markup contract — on the tab bar:
 *   data-tabs                 marks the container (required)
 *   aria-label                names the tablist (required for a useful reading)
 *   data-tab-panel="#id"      one shared region whose contents change
 *   data-tab-panel-prefix="tab-"  per-tab panels: <button data-tab="x"> -> #tab-x
 *   data-tab-panel-suffix="View"  ... and/or a suffix: data-tab="x" -> #xView
 *   data-tab-attr="data-tab"  which attribute holds the tab key (default data-tab)
 *   data-tab-active="active"  the page's own active class (default "active")
 *
 * Bars built at runtime should call window.a11yTabs.scan() after rendering.
 * See CODEBASE-REVIEW-2026-08-18.md finding 4.7.
 */
(function () {
  'use strict';

  var uid = 0;

  function buttonsOf(bar) {
    return Array.prototype.filter.call(bar.children, function (el) {
      return el.tagName === 'BUTTON';
    });
  }

  function panelFor(bar, btn) {
    var shared = bar.getAttribute('data-tab-panel');
    if (shared) return document.querySelector(shared);
    var attr = bar.getAttribute('data-tab-attr') || 'data-tab';
    var key = btn.getAttribute(attr);
    if (!key) return null;
    var prefix = bar.getAttribute('data-tab-panel-prefix') || '';
    var suffix = bar.getAttribute('data-tab-panel-suffix') || '';
    return document.getElementById(prefix + key + suffix);
  }

  // Read the page's own notion of "selected" instead of tracking our own.
  function isActive(bar, btn) {
    var cls = bar.getAttribute('data-tab-active') || 'active';
    return btn.classList.contains(cls);
  }

  function sync(bar) {
    var btns = buttonsOf(bar);
    var selected = null;
    btns.forEach(function (btn) {
      var on = isActive(bar, btn);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
      // Roving tabindex: one stop for the whole bar, arrows move within it.
      btn.tabIndex = on ? 0 : -1;
      if (on) selected = btn;
    });
    // Nothing marked active yet (e.g. a bar rendered before its first switch):
    // keep the first button reachable so the bar is not a keyboard dead end.
    if (!selected && btns.length) btns[0].tabIndex = 0;

    if (bar.getAttribute('data-tab-panel') && selected) {
      var shared = document.querySelector(bar.getAttribute('data-tab-panel'));
      if (shared) shared.setAttribute('aria-labelledby', selected.id);
    }
  }

  function onKeydown(bar, e) {
    var keys = { ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last' };
    if (!(e.key in keys)) return;
    var btns = buttonsOf(bar);
    if (!btns.length) return;
    var i = btns.indexOf(document.activeElement);
    if (i === -1) return;
    var move = keys[e.key];
    var next = move === 'first' ? 0
             : move === 'last' ? btns.length - 1
             : (i + move + btns.length) % btns.length;
    e.preventDefault();
    btns[next].focus();
    // Delegate the actual switch to whatever handler the page already has.
    btns[next].click();
  }

  function enhance(bar) {
    if (bar.dataset.tabsReady === '1') return;
    bar.dataset.tabsReady = '1';
    bar.setAttribute('role', 'tablist');

    var btns = buttonsOf(bar);
    btns.forEach(function (btn) {
      if (!btn.id) btn.id = 'tab-btn-' + (++uid);
      btn.setAttribute('role', 'tab');
      btn.setAttribute('type', 'button');
      var panel = panelFor(bar, btn);
      if (panel) {
        if (!panel.id) panel.id = 'tab-panel-' + (++uid);
        btn.setAttribute('aria-controls', panel.id);
        panel.setAttribute('role', 'tabpanel');
        // Per-tab panels get a permanent label; a shared panel's label follows
        // the selection and is set in sync().
        if (!bar.getAttribute('data-tab-panel')) {
          panel.setAttribute('aria-labelledby', btn.id);
          // A panel holding no focusable content still needs to be reachable
          // for a keyboard user reading it after activating its tab.
          if (!panel.hasAttribute('tabindex')) panel.tabIndex = 0;
        }
      }
    });

    sync(bar);
    bar.addEventListener('keydown', function (e) { onKeydown(bar, e); });

    // The pages own the active class; watch it rather than duplicating it.
    var obs = new MutationObserver(function () { sync(bar); });
    btns.forEach(function (btn) {
      obs.observe(btn, { attributes: true, attributeFilter: ['class'] });
    });
  }

  function scan(root) {
    (root || document).querySelectorAll('[data-tabs]').forEach(enhance);
  }

  window.a11yTabs = { scan: scan };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(); });
  } else {
    scan();
  }
})();
