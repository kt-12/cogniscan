/* scanmyweb slideshow: runs list + per-step player (flow video | brain | TRIBE stats + LLM text) */
(function () {
  const $ = s => document.querySelector(s);
  const el = {
    runs: $('#runs'), runsBody: $('#runsBody'), player: $('#player'), runSelect: $('#runSelect'), status: $('#status'),
    video: $('#video'), stepShot: $('#stepShot'), caption: $('#flowCaption'), flowHead: $('#flowHead'),
    canvas: $('#brainCanvas'), roiBars: $('#roiBars'), legendScale: $('#legendScale'), overlay: $('#overlayMsg'),
    sentence: $('#tribeText .sentence'), parcels: $('#tribeText .parcels'), spark: $('#spark'),
    headline: $('#interp .headline'), text: $('#interp .text'), ux: $('#interp .ux'), meta: $('#interp .meta'), interpModel: $('#interpModel'),
    dots: $('#dots'), scrub: $('#scrub'), timeLabel: $('#timeLabel'), thr: $('#thr'), btnWindow: $('#btnWindow'), btnRoi: $('#btnRoi'),
  };
  const state = { run: null, slides: null, preds: null, nT: 0, nV: 20484, scale: 0.6, idx: 0, t: 0, windowMode: true, viewer: null, playing: false, summaryMode: false };

  // ------------------------------------------------------------ routing / runs list
  function runIdFromPath() { const m = location.pathname.match(/^\/view\/([A-Za-z0-9_-]+)/); return m ? m[1] : null; }

  async function loadRuns() {
    const r = await (await fetch('/api/runs')).json();
    el.runSelect.innerHTML = '<option value="">Runs…</option>' + r.runs.map(x => `<option value="${x.id}">${x.id} · ${shortUrl(x.url)} · ${x.status}</option>`).join('');
    if (state.run) el.runSelect.value = state.run.id;
    el.runsBody.innerHTML = r.runs.length ? r.runs.map(x => {
      const p = x.progress || {}; const pct = x.status === 'done' ? 100 : (p.pct || 0);
      return `<tr>
        <td class="mono">${x.id}</td><td><a href="${x.url}" target="_blank">${shortUrl(x.url)}</a></td>
        <td>${x.mode}${x.goal ? ' · ' + esc(x.goal) : ''}</td>
        <td><span class="pill ${x.status}">${x.status}</span></td>
        <td><div class="prog"><i style="width:${pct}%"></i></div><div class="muted" style="font-size:11px">${esc(p.stage || '')}${x.error ? ' · ' + esc(x.error) : ''}</div></td>
        <td>${x.n_steps ?? ''}</td>
        <td>${x.status === 'done' ? `<a href="/view/${x.id}">open</a>` : ''} ${x.status === 'failed' || x.status === 'recorded' ? `<button data-reprocess="${x.id}">retry</button>` : ''} <button data-del="${x.id}">delete</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="7" class="empty">No runs yet.</td></tr>';
    const busy = r.runs.some(x => ['processing', 'queued', 'recording'].includes(x.status));
    el.status.textContent = r.processing ? `processing ${r.processing}` : (busy ? 'waiting…' : '');
    return busy;
  }
  function shortUrl(u) { try { const x = new URL(u); return x.host + (x.pathname.length > 1 ? x.pathname.slice(0, 24) : ''); } catch { return u || ''; } }
  function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  el.runsBody.addEventListener('click', async e => {
    const del = e.target.dataset.del, rep = e.target.dataset.reprocess;
    if (del && confirm(`Delete run ${del}?`)) { await fetch(`/api/runs/${del}`, { method: 'DELETE' }); loadRuns(); }
    if (rep) { await fetch(`/api/runs/${rep}/reprocess`, { method: 'POST' }); loadRuns(); }
  });
  $('#btnRuns').onclick = () => { history.pushState({}, '', '/'); showRuns(); };
  el.runSelect.onchange = () => { if (el.runSelect.value) { history.pushState({}, '', '/view/' + el.runSelect.value); openRun(el.runSelect.value); } };
  window.onpopstate = () => { const id = runIdFromPath(); id ? openRun(id) : showRuns(); };

  let pollTimer = null;
  function showRuns() {
    el.player.classList.add('hidden'); el.runs.classList.remove('hidden');
    el.video.pause();
    const tick = async () => { const busy = await loadRuns(); pollTimer = setTimeout(tick, busy ? 3000 : 15000); };
    clearTimeout(pollTimer); tick();
  }

  // ------------------------------------------------------------ run player
  async function openRun(id) {
    clearTimeout(pollTimer);
    const run = await (await fetch('/api/runs/' + id)).json();
    if (run.status !== 'done') { showRuns(); el.status.textContent = `run ${id} is ${run.status}`; return; }
    el.runs.classList.add('hidden'); el.player.classList.remove('hidden');
    el.overlay.classList.remove('hidden'); el.overlay.textContent = 'loading predictions…';
    if (!state.viewer) {
      state.viewer = new BrainViewer(el.canvas);
      try { await state.viewer.load('/mesh.json'); } catch (e) { el.overlay.textContent = 'mesh.json missing: run `scanmyweb export-mesh`'; return; }
      state.viewer.setThreshold(parseFloat(el.thr.value));
    }
    const [slides, buf] = await Promise.all([
      (await fetch(`/api/runs/${id}/slides.json`)).json(),
      (await fetch(`/api/runs/${id}/preds.i8`)).arrayBuffer(),
    ]);
    state.run = run; state.slides = slides; state.preds = new Int8Array(buf);
    state.nT = slides.tribe.n_seconds; state.scale = slides.tribe.i8_scale || 0.6;
    state.idx = 0; state.summaryMode = false;
    el.video.src = `/api/runs/${id}/video`;
    el.runSelect.value = id;
    el.interpModel.textContent = slides.interp_model || '';
    el.legendScale.textContent = `±${state.scale} a.u.`;
    el.scrub.max = Math.max(0, state.nT - 1);
    el.dots.innerHTML = slides.slides.map((s, i) => `<button data-i="${i}" title="${esc(s.label || '')}">${i + 1}</button>`).join('');
    el.overlay.classList.add('hidden');
    state.viewer.resize();
    showSlide(0);
    el.status.textContent = `${slides.slides.length} steps · ${state.nT} s · TRIBE ${slides.tribe.runtime.features_and_predict_s}s on ${slides.tribe.runtime.gpu || 'cpu'}`;
  }

  function rowData(rows) {
    const out = new Float32Array(state.nV);
    const sc = state.scale / 127;
    for (const r of rows) { const off = r * state.nV; for (let v = 0; v < state.nV; v++) out[v] += state.preds[off + v]; }
    const k = sc / Math.max(1, rows.length);
    for (let v = 0; v < state.nV; v++) out[v] *= k;
    return out;
  }

  function showSlide(i, keepTime) {
    const s = state.slides.slides[i]; if (!s) return;
    state.idx = i; state.summaryMode = false;
    const st = s.stats;
    if (!keepTime) state.t = st.rows[0];
    el.dots.querySelectorAll('button').forEach(b => b.classList.toggle('active', +b.dataset.i === i));
    el.flowHead.textContent = `step ${i + 1}/${state.slides.slides.length} · ${st.t0}-${st.t1} s`;
    el.caption.querySelector('.lbl').textContent = s.label || s.interp?.headline || `Step ${i + 1}`;
    el.caption.querySelector('.act').textContent = describeAction(s);
    el.caption.querySelector('.url').textContent = s.url || '';
    const shot = s.screenshot_after || s.screenshot_before;
    el.stepShot.src = shot ? `/api/runs/${state.run.id}/steps/${shot}` : '';
    // tribe text
    el.sentence.textContent = st.sentence || '';
    el.parcels.innerHTML = 'top parcels: ' + (st.top_parcels || []).map(p => `${esc(p.name)} ${p.z >= 0 ? '+' : ''}${p.z.toFixed(1)}σ`).join(' · ');
    // interpretation
    const it = s.interp || {};
    el.headline.textContent = it.headline || '';
    el.text.textContent = it.interpretation || '';
    el.ux.textContent = it.ux_note ? 'UX note: ' + it.ux_note : '';
    el.meta.textContent = `confidence ${it.confidence || '?'} · ${it.model || ''}` + (it.error ? ' · ' + it.error : '');
    renderRoiBars(st);
    renderSpark();
    updateBrain();
    if (!state.playing) seekVideo(state.t);
  }

  function describeAction(s) {
    const a = s.action || {}; const e = s.element || {};
    const lbl = (e.text || e.name || e.placeholder || '').slice(0, 60);
    switch (a.type) {
      case 'click': return `click ${e.tag || ''} “${lbl}”`;
      case 'type': return `type “${(a.text || '').slice(0, 40)}” into ${e.tag || 'field'} “${lbl}”`;
      case 'scroll': return `scroll ${a.direction || 'down'}`;
      case 'navigate': return `open ${a.url || ''}`;
      case 'key': return `press ${a.key}`;
      case 'done': return `done: ${a.reason || ''}`;
      default: return a.type || '';
    }
  }

  function renderRoiBars(st) {
    const rows = (st.rois || []).slice();
    el.roiBars.innerHTML = '<h4>ROI groups · z vs this run</h4>' + rows.map(r => {
      const z = Math.max(-3, Math.min(3, r.z)); const w = Math.abs(z) / 3 * 50;
      const left = z >= 0 ? 50 : 50 - w; const col = z >= 0 ? 'var(--accent)' : 'var(--accent2)';
      return `<div class="row" title="${esc(r.about || '')}"><span class="name">${esc(r.label)}</span><div class="track"><i style="left:${left}%;width:${w}%;background:${col}"></i></div><span class="z">${z >= 0 ? '+' : ''}${r.z.toFixed(1)}σ</span></div>`;
    }).join('');
  }

  function renderSpark() {
    const series = state.slides.tribe.per_second_mean_abs || [];
    const W = el.spark.clientWidth || 400, H = 56, n = series.length;
    if (!n) { el.spark.innerHTML = ''; return; }
    const max = Math.max(...series) || 1, min = Math.min(...series);
    const x = i => (i + 0.5) / n * W, y = v => H - 6 - (v - min) / (max - min + 1e-9) * (H - 14);
    let svg = '';
    state.slides.slides.forEach((s, i) => {
      const r = s.stats.rows; const x0 = r[0] / n * W, x1 = (r[r.length - 1] + 1) / n * W;
      svg += `<rect x="${x0}" y="0" width="${x1 - x0}" height="${H}" fill="${i === state.idx ? 'rgba(255,122,26,.22)' : (i % 2 ? 'rgba(255,255,255,.03)' : 'transparent')}" data-i="${i}" style="cursor:pointer"/>`;
    });
    svg += `<polyline fill="none" stroke="#9aa3b5" stroke-width="1.2" points="${series.map((v, i) => `${x(i)},${y(v)}`).join(' ')}"/>`;
    svg += `<line x1="${x(state.t)}" x2="${x(state.t)}" y1="0" y2="${H}" stroke="#ffcc4d" stroke-width="1.5"/>`;
    svg += `<text x="3" y="10" fill="#9aa3b5" font-size="9">mean |predicted BOLD| over cortex, per second</text>`;
    el.spark.setAttribute('viewBox', `0 0 ${W} ${H}`); el.spark.innerHTML = svg;
  }
  el.spark.addEventListener('click', e => { const i = e.target.dataset.i; if (i !== undefined) showSlide(+i); });

  function updateBrain() {
    if (!state.viewer || !state.preds) return;
    const s = state.slides.slides[state.idx];
    const rows = state.windowMode && !state.playing ? s.stats.rows : [Math.max(0, Math.min(state.nT - 1, Math.floor(state.t)))];
    state.viewer.setData(rowData(rows), { scale: state.scale });
    el.scrub.value = Math.floor(state.t);
    el.timeLabel.textContent = (state.windowMode && !state.playing) ? `${s.stats.t0}-${s.stats.t1} s (mean)` : `t = ${Math.floor(state.t)} s`;
  }

  function seekVideo(t) { if (el.video.readyState >= 1) el.video.currentTime = Math.min(t, Math.max(0, el.video.duration - 0.05)); else el.video.addEventListener('loadedmetadata', () => { el.video.currentTime = t; }, { once: true }); }

  // ------------------------------------------------------------ controls
  $('#btnPrev').onclick = () => showSlide(Math.max(0, state.idx - 1));
  $('#btnNext').onclick = () => showSlide(Math.min(state.slides.slides.length - 1, state.idx + 1));
  el.dots.addEventListener('click', e => { if (e.target.dataset.i !== undefined) showSlide(+e.target.dataset.i); });
  el.scrub.oninput = () => { state.t = +el.scrub.value; state.windowMode = false; el.btnWindow.classList.remove('active'); const i = state.slides.slides.findIndex(s => state.t >= s.stats.rows[0] && state.t <= s.stats.rows[s.stats.rows.length - 1]); if (i >= 0 && i !== state.idx) showSlide(i, true); else { updateBrain(); renderSpark(); } seekVideo(state.t); };
  el.btnWindow.onclick = () => { state.windowMode = !state.windowMode; el.btnWindow.classList.toggle('active', state.windowMode); updateBrain(); };
  el.thr.oninput = () => state.viewer && state.viewer.setThreshold(parseFloat(el.thr.value));
  el.btnRoi.onclick = () => { const on = !el.btnRoi.classList.contains('active'); el.btnRoi.classList.toggle('active', on); state.viewer.setRoiOutlines(on); };
  document.querySelectorAll('#brainTools button[data-view]').forEach(b => b.onclick = () => { state.viewer.setView(b.dataset.view); document.querySelectorAll('#brainTools button[data-view]').forEach(x => x.classList.toggle('active', x === b)); });
  $('#btnShot').onclick = () => { const on = el.stepShot.style.display !== 'block'; el.stepShot.style.display = on ? 'block' : 'none'; $('#btnShot').classList.toggle('active', on); };

  const btnPlay = $('#btnPlay');
  function playWindow() {
    const s = state.slides.slides[state.idx]; if (!s) return;
    if (state.playing) { stopPlay(); return; }
    state.playing = true; btnPlay.textContent = '■ stop'; el.stepShot.style.display = 'none'; $('#btnShot').classList.remove('active');
    el.video.currentTime = s.stats.t0; el.video.play();
  }
  function stopPlay() { state.playing = false; btnPlay.textContent = '▶ play window'; el.video.pause(); updateBrain(); }
  btnPlay.onclick = playWindow;
  el.video.addEventListener('timeupdate', () => {
    if (!state.playing) return;
    const s = state.slides.slides[state.idx];
    state.t = el.video.currentTime;
    if (state.t >= s.stats.t1 || el.video.ended) { stopPlay(); state.t = s.stats.rows[0]; renderSpark(); return; }
    updateBrain(); renderSpark();
  });

  $('#btnSummary').onclick = () => {
    const sm = state.slides.summary || {}; state.summaryMode = true;
    el.headline.textContent = 'Run summary';
    el.text.textContent = sm.summary || '';
    el.ux.innerHTML = (sm.notable_steps || []).map(n => `step ${n.step}: ${esc(n.why)}`).join('<br>');
    el.meta.textContent = (sm.caveat || '') + ' · ' + (sm.model || '');
    const rs = state.slides.run_stats || {};
    el.sentence.textContent = `Strongest overall response at step ${(rs.strongest_step ?? 0) + 1}, weakest at step ${(rs.weakest_step ?? 0) + 1}. ` + (state.slides.tribe.caveats || []).join(' ');
  };

  document.addEventListener('keydown', e => {
    if (el.player.classList.contains('hidden') || e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === 'ArrowRight') $('#btnNext').click();
    else if (e.key === 'ArrowLeft') $('#btnPrev').click();
    else if (e.key === ' ') { e.preventDefault(); playWindow(); }
    else if (e.key === 'w') el.btnWindow.click();
    else if (e.key === 'r') el.btnRoi.click();
  });

  // boot
  const id = runIdFromPath();
  loadRuns().then(() => id ? openRun(id) : showRuns());
})();
