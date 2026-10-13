/* cogniscan content script: bridges background messages to the page-side core (cogniscan_core.js). */
(function () {
  if (window.__cogniscanBridge) return; window.__cogniscanBridge = true;
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    const cogniscan = window.__cogniscan;
    try {
      if (!cogniscan) { sendResponse({ ok: false, error: 'core not loaded' }); return; }
      switch (msg && msg.type) {
        case 'cogniscan:mark': sendResponse(cogniscan.mark()); break;
        case 'cogniscan:unmark': cogniscan.unmark(); sendResponse({ ok: true }); break;
        case 'cogniscan:cursor': sendResponse({ ok: cogniscan.cursor(msg.x, msg.y, msg.click) }); break;
        case 'cogniscan:focus': sendResponse({ ok: cogniscan.focus(msg.id) }); break;
        case 'cogniscan:ping': sendResponse({ ok: true }); break;
        default: sendResponse({ ok: false });
      }
    } catch (e) { sendResponse({ ok: false, error: String(e) }); }
  });
})();
