// Yappman Data: small vanilla helpers. No cookies.
(function () {
  var nav = document.querySelector('nav[aria-label="Main"]');
  var btn = document.querySelector('.menu-btn');

  // ---------- Navigation: dropdown panels (desktop) and accordions (phone). Every item is a real link, so the
  // menu also works with JavaScript off (see the html:not(.js) rules in the stylesheet).
  if (nav) {
    var groups = [].slice.call(nav.querySelectorAll('.nav-group'));
    var phone = window.matchMedia('(max-width: 768px)');
    var canHover = window.matchMedia('(hover: hover) and (pointer: fine)');
    var topBtn = function (g) { return g.querySelector('.nav-top'); };
    var panelLinks = function (g) { return [].slice.call(g.querySelectorAll('.panel a')); };
    var isOpen = function (g) { return g.classList.contains('open'); };

    var setOpen = function (g, open, by) {
      g.classList.toggle('open', open);
      topBtn(g).setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) g.setAttribute('data-by', by || 'click'); else g.removeAttribute('data-by');
    };
    var closeAll = function (except) { groups.forEach(function (g) { if (g !== except && isOpen(g)) setOpen(g, false); }); };
    var openGroup = function (g, by) { closeAll(g); setOpen(g, true, by); }; // one menu open at a time
    var hoverOK = function () { return !phone.matches && canHover.matches; };

    groups.forEach(function (g) {
      var b = topBtn(g);

      // click, Enter and Space (a button fires click for all three): touch, keyboard and screen readers
      b.addEventListener('click', function () {
        clearTimeout(g._ot); clearTimeout(g._ct);
        if (isOpen(g) && g.getAttribute('data-by') === 'hover') g.setAttribute('data-by', 'click'); // a click pins a hover-opened panel
        else if (isOpen(g)) setOpen(g, false);
        else openGroup(g, 'click');
      });

      // hover with a short intent delay (about 150 ms) and a small grace period on the way out
      g.addEventListener('mouseenter', function () {
        if (!hoverOK()) return;
        clearTimeout(g._ct);
        if (!isOpen(g)) { clearTimeout(g._ot); g._ot = setTimeout(function () { openGroup(g, 'hover'); }, 150); }
      });
      g.addEventListener('mouseleave', function () {
        if (!hoverOK()) return;
        clearTimeout(g._ot);
        if (g.getAttribute('data-by') === 'hover') g._ct = setTimeout(function () { setOpen(g, false); }, 200);
      });

      // focus leaving the group closes it
      g.addEventListener('focusout', function () {
        setTimeout(function () { if (!g.contains(document.activeElement)) setOpen(g, false); }, 0);
      });

      // arrow keys within a panel; Escape closes and returns focus to the button
      g.addEventListener('keydown', function (e) {
        var links = panelLinks(g), i = links.indexOf(document.activeElement), onBtn = document.activeElement === b;
        if (e.key === 'ArrowDown' && (onBtn || i >= 0)) {
          e.preventDefault();
          if (!isOpen(g)) openGroup(g, 'key');
          links = panelLinks(g);
          (onBtn ? links[0] : links[(i + 1) % links.length]).focus();
        } else if (e.key === 'ArrowUp' && (onBtn || i >= 0)) {
          e.preventDefault();
          if (!isOpen(g)) openGroup(g, 'key');
          links = panelLinks(g);
          (onBtn ? links[links.length - 1] : links[(i - 1 + links.length) % links.length]).focus();
        } else if (e.key === 'Home' && i >= 0) { e.preventDefault(); links[0].focus(); }
        else if (e.key === 'End' && i >= 0) { e.preventDefault(); links[links.length - 1].focus(); }
        else if (e.key === 'Escape' && isOpen(g)) { e.preventDefault(); setOpen(g, false); b.focus(); }
      });
    });

    // Left and Right arrows move between the top-level items (desktop)
    var topItems = [].slice.call(nav.querySelectorAll('.nav-list > li > .nav-top, .nav-list > li > a'));
    nav.addEventListener('keydown', function (e) {
      if (phone.matches || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft')) return;
      var i = topItems.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      topItems[(i + (e.key === 'ArrowRight' ? 1 : topItems.length - 1)) % topItems.length].focus();
    });

    // outside click, scroll and breakpoint changes close everything
    document.addEventListener('click', function (e) { if (!nav.contains(e.target)) closeAll(); });
    window.addEventListener('scroll', function () { if (!phone.matches) closeAll(); }, { passive: true });
    if (phone.addEventListener) phone.addEventListener('change', function () { closeAll(); if (btn) { nav.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); } });

    // phone: the Menu button opens the sheet
    var closeSheet = function () { if (btn) { nav.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); } closeAll(); };
    if (btn) btn.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) closeAll();
    });
    nav.addEventListener('click', function (e) { if (e.target.closest('.nav-list a')) closeSheet(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && btn && phone.matches && nav.classList.contains('open') && !groups.some(isOpen)) { closeSheet(); btn.focus(); }
    });
  }

  // ---------- Dismissible announcement bar. The choice is kept only for this visit (session storage), never sent anywhere.
  var strip = document.getElementById('strip');
  if (strip) {
    try { if (sessionStorage.getItem('yd-strip-dismissed') === '1') strip.hidden = true; } catch (e) {}
    var x = strip.querySelector('.strip-x');
    if (x) x.addEventListener('click', function () {
      strip.hidden = true;
      try { sessionStorage.setItem('yd-strip-dismissed', '1'); } catch (e) {}
    });
  }

  // ---------- Old home-page anchors now live on their own pages.
  if (location.pathname === '/' || location.pathname === '/index.html') {
    var moved = { '#demos': '/demos/', '#notices': '/notices/', '#sample': '/methodology/#sample', '#fields': '/methodology/#fields', '#series': '/methodology/#series' };
    if (moved[location.hash]) location.replace(moved[location.hash]);
  }
})();
