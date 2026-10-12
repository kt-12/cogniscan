/* scanmyweb content script: bridges background messages to the page-side core (smw_core.js). */
(function () {
  if (window.__smwBridge) return; window.__smwBridge = true;
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    const smw = window.__smw;
    try {
      if (!smw) { sendResponse({ ok: false, error: 'core not loaded' }); return; }
      switch (msg && msg.type) {
        case 'smw:mark': sendResponse(smw.mark()); break;
        case 'smw:unmark': smw.unmark(); sendResponse({ ok: true }); break;
        case 'smw:cursor': sendResponse({ ok: smw.cursor(msg.x, msg.y, msg.click) }); break;
        case 'smw:focus': sendResponse({ ok: smw.focus(msg.id) }); break;
        case 'smw:ping': sendResponse({ ok: true }); break;
        default: sendResponse({ ok: false });
      }
    } catch (e) { sendResponse({ ok: false, error: String(e) }); }
  });
})();
