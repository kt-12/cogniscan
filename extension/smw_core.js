/* scanmyweb page-side core: numbered marks on interactive elements + a visible virtual cursor.
 * Shared by the extension content script (content.js) and the CLI CDP driver (injected directly).
 * Exposes window.__smw = { mark(), unmark(), cursor(x, y, click), focus(id), ping() }.
 */
(function () {
  if (window.__smw) return;
  let marks = [];
  let lastElements = [];

  function cursorEl() {
    let c = document.getElementById('__smw_cursor');
    if (!c) {
      c = document.createElement('div'); c.id = '__smw_cursor';
      c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M5 3l14 9-6 1 4 7-3 1-4-7-5 4z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
      document.documentElement.appendChild(c);
      const r = document.createElement('div'); r.id = '__smw_ripple'; document.documentElement.appendChild(r);
      if (!document.getElementById('__smw_style')) {
        const s = document.createElement('style'); s.id = '__smw_style';
        s.textContent = `#__smw_cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:left .09s linear,top .09s linear;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6));display:none}
#__smw_cursor.smw-click{animation:smw-click .25s ease-out}@keyframes smw-click{0%{transform:translate(-3px,-2px) scale(1)}40%{transform:translate(-3px,-2px) scale(.75)}100%{transform:translate(-3px,-2px) scale(1)}}
#__smw_ripple{position:fixed;width:36px;height:36px;border-radius:50%;border:3px solid #ff7a1a;z-index:2147483646;pointer-events:none;transform:translate(-50%,-50%) scale(.2);opacity:0;display:none}
#__smw_ripple.smw-go{display:block;animation:smw-ripple .45s ease-out forwards}@keyframes smw-ripple{0%{transform:translate(-50%,-50%) scale(.2);opacity:.9}100%{transform:translate(-50%,-50%) scale(1.6);opacity:0}}
.__smw_mark{position:absolute;z-index:2147483645;pointer-events:none;background:#e8102a;color:#fff;font:bold 11px/1 Arial,sans-serif;padding:2px 4px;border-radius:3px;box-shadow:0 0 0 1px #fff;white-space:nowrap}
.__smw_box{position:absolute;z-index:2147483644;pointer-events:none;outline:2px solid rgba(232,16,42,.75)}`;
        document.documentElement.appendChild(s);
      }
    }
    return c;
  }

  function visible(e) {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return null;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return null;
    if (r.bottom < -200 || r.top > innerHeight + 600 || r.right < 0 || r.left > innerWidth) return null;
    return r;
  }

  function textOf(e) {
    const t = (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ');
    if (t) return t.slice(0, 120);
    const img = e.querySelector && e.querySelector('img');
    return (e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('alt') || (img && img.alt) || '').trim().slice(0, 120);
  }

  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=radio], [onclick], [contenteditable=true], label[for]';

  function collect() {
    const nodes = Array.from(document.querySelectorAll(SEL));
    const out = []; const seen = new Set();
    let id = 0;
    for (const e of nodes) {
      if (seen.has(e)) continue; seen.add(e);
      if (e.closest('#__smw_cursor')) continue;
      const r = visible(e); if (!r) continue;
      if (e.parentElement && seen.has(e.parentElement) && e.parentElement.matches(SEL)) continue;
      id++;
      const inView = r.top >= 0 && r.bottom <= innerHeight;
      out.push({
        id, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', type: e.getAttribute('type') || '',
        text: textOf(e), name: e.getAttribute('name') || '', placeholder: e.getAttribute('placeholder') || '',
        value: (e.value && typeof e.value === 'string' && e.type !== 'password') ? e.value.slice(0, 40) : '',
        href: e.tagName === 'A' ? (e.getAttribute('href') || '').slice(0, 100) : '',
        bbox: { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), w: Math.round(r.width), h: Math.round(r.height), left: Math.round(r.left), top: Math.round(r.top) },
        inViewport: inView,
        _el: e,
      });
      if (out.length >= 160) break;
    }
    return out;
  }

  function mark() {
    unmark();
    lastElements = collect();
    const frag = document.createDocumentFragment();
    for (const el of lastElements) {
      if (!el.inViewport) continue;
      const b = el.bbox;
      const box = document.createElement('div'); box.className = '__smw_box';
      box.style.cssText = `left:${b.left + scrollX}px;top:${b.top + scrollY}px;width:${b.w}px;height:${b.h}px`;
      const m = document.createElement('div'); m.className = '__smw_mark'; m.textContent = el.id;
      m.style.cssText = `left:${Math.max(0, b.left + scrollX - 2)}px;top:${Math.max(0, b.top + scrollY - 14)}px`;
      frag.appendChild(box); frag.appendChild(m); marks.push(box, m);
    }
    cursorEl();
    document.documentElement.appendChild(frag);
    return {
      elements: lastElements.map(({ _el, ...rest }) => rest),
      viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio, scrollY, title: document.title, url: location.href },
    };
  }
  function unmark() { for (const m of marks) m.remove(); marks = []; }

  function cursor(x, y, click) {
    const c = cursorEl(); c.style.display = 'block'; c.style.left = x + 'px'; c.style.top = y + 'px';
    if (click) {
      c.classList.remove('smw-click'); void c.offsetWidth; c.classList.add('smw-click');
      const r = document.getElementById('__smw_ripple'); r.style.left = x + 'px'; r.style.top = y + 'px';
      r.classList.remove('smw-go'); void r.offsetWidth; r.classList.add('smw-go');
    }
    return true;
  }

  function focus(id) {
    const el = lastElements.find(e => e.id === id);
    if (el && el._el) { el._el.focus(); if (el._el.select && el._el.tagName !== 'SELECT') { try { el._el.select(); } catch (e) {} } return true; }
    return false;
  }

  window.__smw = { mark, unmark, cursor, focus, ping: () => true };
})();
