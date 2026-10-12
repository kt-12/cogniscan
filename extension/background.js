/* scanmyweb background service worker: the virtual-mouse driver and recorder.
 *
 * start -> create run on server -> open tab -> attach debugger -> Page.startScreencast
 *   loop: mark elements (content script) -> CDP screenshot -> POST /api/agent/step -> animate cursor +
 *         CDP Input events -> settle -> screenshot -> POST step
 * stop/done/cap -> flush frames -> POST finish -> poll status
 */
const SERVER = 'http://127.0.0.1:8787';
const S = {
  state: 'idle', text: '', pct: 0, error: false, runId: null, tabId: null, t0: 0,
  frames: [], uploading: false, nFrames: 0, history: [], stepIndex: 0, stopRequested: false,
  maxSeconds: 90, maxSteps: 20, loadResolve: null, pausedTotal: 0, pauseStart: null,
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
const now = () => (performance.now() - S.t0 - S.pausedTotal) / 1000;  // clock stops while the model thinks
const api = async (path, body, method) => {
  const r = await fetch(SERVER + path, { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status} ${await r.text()}`);
  return r.json();
};
const cdp = (method, params) => chrome.debugger.sendCommand({ tabId: S.tabId }, method, params || {});
function setStatus(text, pct, error) { S.text = text; if (pct !== undefined) S.pct = pct; S.error = !!error; console.log('[smw]', text); }

// ------------------------------------------------------------------ content script helpers
async function cs(msg, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try { return await chrome.tabs.sendMessage(S.tabId, msg); } catch (e) {
      try {
        await chrome.scripting.executeScript({ target: { tabId: S.tabId }, files: ['smw_core.js', 'content.js'] });
      } catch {}
      await sleep(300);
    }
  }
  return null;
}

// ------------------------------------------------------------------ recording
function onDebuggerEvent(source, method, params) {
  if (source.tabId !== S.tabId) return;
  if (method === 'Page.screencastFrame') {
    if (S.pauseStart === null) S.frames.push({ t: now(), data: params.data });
    cdp('Page.screencastFrameAck', { sessionId: params.sessionId }).catch(() => {});
    if (S.frames.length >= 8) flushFrames();
  } else if (method === 'Page.loadEventFired' || method === 'Page.frameStoppedLoading') {
    if (S.loadResolve) { S.loadResolve(); S.loadResolve = null; }
  }
}
chrome.debugger.onEvent.addListener(onDebuggerEvent);
chrome.debugger.onDetach.addListener((source, reason) => {
  if (source.tabId === S.tabId && S.state === 'recording') { setStatus('debugger detached: ' + reason, undefined, true); S.stopRequested = true; }
});

async function flushFrames() {
  if (S.uploading || !S.frames.length || !S.runId) return;
  S.uploading = true;
  const batch = S.frames.splice(0, S.frames.length);
  try { const r = await api(`/api/runs/${S.runId}/frames`, { frames: batch }); S.nFrames = r.n_frames; }
  catch (e) { console.warn('frame upload failed', e); }
  finally { S.uploading = false; }
}

async function startScreencast() {
  await cdp('Page.enable');
  await cdp('Page.startScreencast', { format: 'jpeg', quality: 60, maxWidth: 1280, maxHeight: 800, everyNthFrame: 1 });
}

async function screenshot() {
  const r = await cdp('Page.captureScreenshot', { format: 'jpeg', quality: 70 });
  return r.data;
}

function waitForLoad(ms) {
  return new Promise(resolve => { const t = setTimeout(() => { S.loadResolve = null; resolve(false); }, ms); S.loadResolve = () => { clearTimeout(t); resolve(true); }; });
}

// ------------------------------------------------------------------ virtual mouse
let mouse = { x: 200, y: 200 };
async function moveMouse(x, y, steps = 10) {
  for (let i = 1; i <= steps; i++) {
    const px = mouse.x + (x - mouse.x) * i / steps, py = mouse.y + (y - mouse.y) * i / steps;
    cs({ type: 'smw:cursor', x: px, y: py }, 1);
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: px, y: py }).catch(() => {});
    await sleep(35);
  }
  mouse = { x, y };
}
async function click(x, y) {
  await moveMouse(x, y);
  await sleep(120);
  cs({ type: 'smw:cursor', x, y, click: true }, 1);
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await sleep(70);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
}
async function scroll(direction) {
  const dy = direction === 'up' ? -220 : 220;
  await moveMouse(640, 400, 6);
  for (let i = 0; i < 3; i++) { await cdp('Input.dispatchMouseEvent', { type: 'mouseWheel', x: mouse.x, y: mouse.y, deltaX: 0, deltaY: dy }); await sleep(140); }
}
const KEYS = { Enter: { code: 'Enter', vk: 13, text: '\r' }, Escape: { code: 'Escape', vk: 27 }, Tab: { code: 'Tab', vk: 9 }, Backspace: { code: 'Backspace', vk: 8 }, ArrowDown: { code: 'ArrowDown', vk: 40 }, ArrowUp: { code: 'ArrowUp', vk: 38 } };
async function pressKey(key) {
  const k = KEYS[key] || KEYS.Enter;
  await cdp('Input.dispatchKeyEvent', { type: 'rawKeyDown', key, code: k.code, windowsVirtualKeyCode: k.vk, nativeVirtualKeyCode: k.vk });
  if (k.text) await cdp('Input.dispatchKeyEvent', { type: 'char', text: k.text, key, code: k.code, windowsVirtualKeyCode: k.vk });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key, code: k.code, windowsVirtualKeyCode: k.vk, nativeVirtualKeyCode: k.vk });
}
async function typeText(text) {
  for (const ch of text) { await cdp('Input.insertText', { text: ch }); await sleep(45); }
}

async function execute(action) {
  const b = action.element && action.element.bbox;
  switch (action.type) {
    case 'click': await click(b.x, b.y); break;
    case 'type':
      await click(b.x, b.y); await cs({ type: 'smw:focus', id: action.id }, 1);
      await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', code: 'KeyA', modifiers: 2, windowsVirtualKeyCode: 65 }).catch(() => {});
      await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', modifiers: 2, windowsVirtualKeyCode: 65 }).catch(() => {});
      await typeText(action.text || '');
      if (action.submit) { await sleep(200); await pressKey('Enter'); }
      break;
    case 'scroll': await scroll(action.direction); break;
    case 'key': await pressKey(action.key); break;
    case 'navigate': await cdp('Page.navigate', { url: action.url }); await waitForLoad(6000); break;
    case 'wait': await sleep(action.ms || 1500); break;
  }
}

// ------------------------------------------------------------------ main loop
async function start(cfg) {
  if (S.state === 'recording') return { error: 'already recording' };
  Object.assign(S, { state: 'starting', text: '', pct: 0, error: false, runId: null, frames: [], nFrames: 0, history: [], stepIndex: 0, stopRequested: false, pausedTotal: 0, pauseStart: null });
  try {
    const health = await api('/api/health');
    if (!health.llm.ok) throw new Error('LLM not ready: ' + health.llm.detail);
    S.maxSeconds = health.max_flow_seconds; S.maxSteps = health.max_steps;
    const run = await api('/api/runs', { url: cfg.url, mode: cfg.mode, goal: cfg.goal, nav_model: cfg.navModel, interp_model: cfg.interpModel });
    S.runId = run.id;
    const tab = await chrome.tabs.create({ url: cfg.url, active: true });
    S.tabId = tab.id;
    await new Promise(res => { const l = (id, info) => { if (id === tab.id && info.status === 'complete') { chrome.tabs.onUpdated.removeListener(l); res(); } }; chrome.tabs.onUpdated.addListener(l); setTimeout(res, 15000); });
    await chrome.debugger.attach({ tabId: S.tabId }, '1.3');
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false }).catch(() => {});
    S.t0 = performance.now();
    await startScreencast();
    S.state = 'recording';
    setStatus('recording started', 2);
    await sleep(3000);  // let the landing page be the first stimulus
    loop(cfg).catch(e => { setStatus('loop error: ' + e.message, undefined, true); finish('error: ' + e.message); });
    return { ok: true, runId: S.runId };
  } catch (e) {
    S.state = 'idle'; setStatus(e.message, 0, true);
    return { error: e.message };
  }
}

async function loop(cfg) {
  let reason = 'done';
  while (S.state === 'recording') {
    if (S.stopRequested) { reason = 'stopped by user'; break; }
    const elapsed = now();
    if (elapsed > S.maxSeconds - 4) { reason = 'time cap reached'; break; }
    if (S.stepIndex >= S.maxSteps) { reason = 'step cap reached'; break; }
    setStatus(`step ${S.stepIndex + 1}: looking at the page… (${elapsed.toFixed(0)}s / ${S.maxSeconds}s)`, 100 * elapsed / S.maxSeconds);

    const marked = await cs({ type: 'smw:mark' });
    if (!marked) { setStatus('content script unreachable; waiting', undefined, true); await sleep(1500); continue; }
    await sleep(80);
    const before = await screenshot();
    await cs({ type: 'smw:unmark' }, 1);
    const tStart = now();
    setStatus(`step ${S.stepIndex + 1}: asking ${cfg.navModel}…`);
    let res;
    S.pauseStart = performance.now();
    try {
      res = await api('/api/agent/step', { run_id: S.runId, url: marked.viewport.url, title: marked.viewport.title, elements: marked.elements, history: S.history, screenshot: before, step_index: S.stepIndex, elapsed_s: now() });
    } catch (e) { setStatus('agent error: ' + e.message, undefined, true); reason = 'agent error'; break; }
    finally { S.pausedTotal += performance.now() - S.pauseStart; S.pauseStart = null; }
    const action = res.action;
    setStatus(`step ${S.stepIndex + 1}: ${action.type} ${action.id || ''} — ${action.label}`);
    if (action.type === 'done') { reason = action.reason || 'done'; await postStep(S.stepIndex, tStart, now() + 1.5, action, marked, before, null); break; }

    const t0 = now();
    const urlBefore = marked.viewport.url;
    try { await execute(action); } catch (e) { console.warn('execute failed', e); }
    // settle: give navigations a chance, then a short dwell so TRIBE sees the result
    await sleep(1000);
    try { const t = await chrome.tabs.get(S.tabId); if (t.status === 'loading') await waitForLoad(5000); if (t.url !== urlBefore) await startScreencast().catch(() => {}); } catch {}
    await sleep(2500);  // dwell so TRIBE sees the result of the action
    const after = await screenshot().catch(() => null);
    const t1 = now();
    await postStep(S.stepIndex, t0, t1, action, marked, before, after);
    let urlAfter = marked.viewport.url; try { urlAfter = (await chrome.tabs.get(S.tabId)).url || urlAfter; } catch {}
    S.history.push({ i: S.stepIndex, action: { type: action.type, id: action.id, text: action.text }, label: action.label, url: urlAfter });
    S.stepIndex++;
  }
  await finish(reason);
}

async function postStep(i, t0, t1, action, marked, before, after) {
  const { element, ...act } = action;
  let url = marked.viewport.url, title = marked.viewport.title;
  try { const t = await chrome.tabs.get(S.tabId); url = t.url || url; title = t.title || title; } catch {}
  await api(`/api/runs/${S.runId}/steps`, { i, t0: +t0.toFixed(3), t1: +t1.toFixed(3), action: act, element: element || null, url, title, label: action.label || '', screenshot_before: before, screenshot_after: after }).catch(e => console.warn('step upload failed', e));
}

async function finish(reason) {
  if (S.state !== 'recording') return;
  S.state = 'finishing';
  await sleep(2000);  // final dwell
  const duration = Math.min(now() + 0.5, S.maxSeconds);
  setStatus('finishing: ' + reason, 100);
  try { await cdp('Page.stopScreencast'); } catch {}
  await sleep(300);
  while (S.uploading) await sleep(100);
  await flushFrames();
  while (S.uploading) await sleep(100);
  try { await chrome.debugger.detach({ tabId: S.tabId }); } catch {}
  cs({ type: 'smw:cursor', x: -100, y: -100 }, 1);
  try { await api(`/api/runs/${S.runId}/finish`, { duration_s: duration, reason }); } catch (e) { setStatus('finish failed: ' + e.message, undefined, true); S.state = 'idle'; return; }
  S.state = 'processing';
  pollProcessing();
}

async function pollProcessing() {
  while (S.state === 'processing') {
    try {
      const run = await api(`/api/runs/${S.runId}`);
      const p = run.progress || {};
      if (run.status === 'done') { S.state = 'done'; setStatus(`done — open the slideshow (${run.n_slides} steps)`, 100); break; }
      if (run.status === 'failed') { S.state = 'idle'; setStatus('processing failed: ' + run.error, 100, true); break; }
      setStatus(`processing: ${p.stage || run.status} (${(p.pct || 0).toFixed(0)}%)`, p.pct || 0);
    } catch (e) { setStatus('server unreachable: ' + e.message, undefined, true); }
    await sleep(3000);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'smw:start') { start(msg).then(sendResponse); return true; }
  if (msg.type === 'smw:stop') { S.stopRequested = true; sendResponse({ ok: true }); return; }
  if (msg.type === 'smw:status') { sendResponse({ state: S.state, text: S.text, pct: S.pct, error: S.error, runId: S.runId, nFrames: S.nFrames, step: S.stepIndex }); return; }
});
