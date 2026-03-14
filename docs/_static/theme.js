/**
 * theme.js — HDL AutoDoc theme engine
 * Handles dark/light toggle, injects the floating button,
 * and applies the saved or OS-preferred theme on load.
 */
(function () {
  'use strict';

  // ── Apply theme ────────────────────────────────────────────────────────────
  function applyTheme(dark) {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    localStorage.setItem('hdl-theme', dark ? 'dark' : 'light');

    var btn = document.getElementById('hdl-toggle');
    if (btn) {
      btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      btn.setAttribute('title',      dark ? 'Switch to light mode' : 'Switch to dark mode');
      btn.querySelector('.hdl-toggle-track').setAttribute('data-dark', dark ? '1' : '0');
    }
  }

  // ── Read saved / OS preference ─────────────────────────────────────────────
  var saved      = localStorage.getItem('hdl-theme');
  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  var isDark     = saved === 'dark' || (!saved && prefersDark);
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');

  // ── Inject toggle button after DOM ready ──────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.createElement('button');
    btn.id = 'hdl-toggle';
    btn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    btn.setAttribute('title',      isDark ? 'Switch to light mode' : 'Switch to dark mode');
    btn.innerHTML =
      '<span class="hdl-toggle-track" data-dark="' + (isDark ? '1' : '0') + '">' +
        '<span class="hdl-toggle-thumb"></span>' +
        '<span class="hdl-toggle-icon-moon">&#9790;</span>' +
        '<span class="hdl-toggle-icon-sun">&#9788;</span>' +
      '</span>' +
      '<span class="hdl-toggle-label">Dark</span>';

    document.body.appendChild(btn);
    applyTheme(isDark);

    btn.addEventListener('click', function () {
      var dark = document.documentElement.getAttribute('data-theme') !== 'dark';
      applyTheme(dark);
    });

    // ── Sync label text ─────────────────────────────────────────────────────
    var observer = new MutationObserver(function () {
      var d = document.documentElement.getAttribute('data-theme') === 'dark';
      var label = btn.querySelector('.hdl-toggle-label');
      if (label) label.textContent = d ? 'Light' : 'Dark';
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  });

})();