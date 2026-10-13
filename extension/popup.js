const $ = s => document.querySelector(s);
const SERVER = 'http://127.0.0.1:8787';

async function init() {
  const saved = await chrome.storage.local.get(['url', 'mode', 'goal', 'navModel', 'interpModel']);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('#url').value = saved.url || (tab && /^https?:/.test(tab.url || '') ? tab.url : '');
  $('#mode').value = saved.mode || 'goal';
  $('#goal').value = saved.goal || '';
  toggleGoal();
  try {
    const r = await (await fetch(SERVER + '/api/models')).json();
    const fill = (sel, needVision, def) => {
      sel.innerHTML = r.models.filter(m => !needVision || m.vision).map(m => `<option value="${m.name}">${m.name}${m.vision ? ' 👁' : ''}</option>`).join('');
      sel.value = def && [...sel.options].some(o => o.value === def) ? def : (needVision ? r.nav_model : r.interp_model);
    };
    fill($('#navModel'), true, saved.navModel);
    fill($('#interpModel'), false, saved.interpModel);
    $('#server').textContent = 'server ok';
  } catch (e) {
    $('#server').textContent = 'server not running: `cogniscan serve`';
    $('#status').className = 'err'; $('#status').textContent = 'Cannot reach ' + SERVER;
  }
  refresh();
}

function toggleGoal() { $('#goalWrap').style.display = $('#mode').value === 'goal' ? '' : 'none'; }
$('#mode').onchange = toggleGoal;

$('#start').onclick = async () => {
  const url = $('#url').value.trim();
  if (!/^https?:\/\//.test(url)) { $('#status').className = 'err'; $('#status').textContent = 'Enter a full http(s) URL'; return; }
  const cfg = { url, mode: $('#mode').value, goal: $('#goal').value.trim(), navModel: $('#navModel').value, interpModel: $('#interpModel').value };
  await chrome.storage.local.set(cfg);
  $('#status').className = ''; $('#status').textContent = 'starting…';
  const res = await chrome.runtime.sendMessage({ type: 'cogniscan:start', ...cfg });
  if (res && res.error) { $('#status').className = 'err'; $('#status').textContent = res.error; }
  refresh();
};
$('#stop').onclick = async () => { await chrome.runtime.sendMessage({ type: 'cogniscan:stop' }); refresh(); };

async function refresh() {
  const st = await chrome.runtime.sendMessage({ type: 'cogniscan:status' });
  if (!st) return;
  const running = st.state === 'recording';
  $('#start').disabled = running; $('#stop').disabled = !running;
  $('#bar').style.width = (st.pct || 0) + '%';
  $('#status').className = st.error ? 'err' : '';
  $('#status').textContent = st.text || '';
  if (st.runId) { $('#open').href = `${SERVER}/${st.state === 'done' ? 'view/' + st.runId : ''}`; }
  if (running || st.state === 'processing') setTimeout(refresh, 1500);
}

init();
