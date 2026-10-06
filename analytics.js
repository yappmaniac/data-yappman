// Google Analytics 4 for data.yappman.com, loaded only after the visitor accepts cookies.
(function () {
  var GA_ID = 'G-TBY10G9M74', KEY = 'yp-data-cookie-consent';
  function has() { try { return !!localStorage.getItem(KEY); } catch (e) { return false; } }
  function load() {
    if (window.__gaLoaded) return; window.__gaLoaded = true;
    var s = document.createElement('script'); s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', GA_ID);
  }
  function banner() {
    var b = document.createElement('div');
    b.setAttribute('role', 'region'); b.setAttribute('aria-label', 'Cookie notice');
    b.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:200;background:#16202b;color:#fff;font:14px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;';
    b.innerHTML = '<div style="max-width:900px;margin:0 auto;padding:12px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;">' +
      '<span style="flex:1 1 320px;">We use cookies to understand how this site is used. See our <a href="/privacy/" style="color:#fff;text-decoration:underline;">privacy &amp; cookies</a> policy.</span>' +
      '<button type="button" style="background:#1f5fa8;color:#fff;border:0;border-radius:4px;padding:8px 18px;font:inherit;cursor:pointer;">Accept</button></div>';
    b.querySelector('button').addEventListener('click', function () {
      try { localStorage.setItem(KEY, '1'); } catch (e) {}
      b.remove(); load();
    });
    document.body.appendChild(b);
  }
  function init() { if (has()) load(); else banner(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
