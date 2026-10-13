// Yappman Data: small vanilla helpers. No cookies.
(function () {
  // Menu toggle below 768px
  var nav = document.querySelector('nav[aria-label="Main"]');
  var btn = document.querySelector('.menu-btn');
  function closeMenu() { if (nav && btn) { nav.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); } }
  if (nav && btn) {
    btn.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    nav.addEventListener('click', function (e) { if (e.target.closest('.links a')) closeMenu(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && nav.classList.contains('open')) { closeMenu(); btn.focus(); } });
  }

  // Dismissible announcement bar. The choice is kept only for this visit (session storage), never sent anywhere.
  var strip = document.getElementById('strip');
  if (strip) {
    try { if (sessionStorage.getItem('yd-strip-dismissed') === '1') strip.hidden = true; } catch (e) {}
    var x = strip.querySelector('.strip-x');
    if (x) x.addEventListener('click', function () {
      strip.hidden = true;
      try { sessionStorage.setItem('yd-strip-dismissed', '1'); } catch (e) {}
    });
  }

  // Old home-page anchors now live on their own pages.
  if (location.pathname === '/' || location.pathname === '/index.html') {
    var moved = { '#demos': '/demos/', '#notices': '/notices/', '#sample': '/methodology/#sample', '#fields': '/methodology/#fields', '#series': '/methodology/#series' };
    if (moved[location.hash]) location.replace(moved[location.hash]);
  }

})();
