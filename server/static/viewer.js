/* BrainViewer: inflated fsaverage5 in three.js, coloured by a per-vertex value array.
 * Usage:
 *   const v = new BrainViewer(canvas); await v.load('/mesh.json');
 *   v.setData(Float32Array(nV), {scale}); v.setView('lateral'); v.setThreshold(0.15); v.setRoiOutlines(true)
 */
(function () {
  const N_HEMI = 10242;

  function b64ToArray(b64, Ctor) {
    const bin = atob(b64);
    const buf = new ArrayBuffer(bin.length);
    const u8 = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return new Ctor(buf);
  }

  // diverging colormap: blue (neg) -> dark grey (0) -> orange -> yellow (pos)
  const STOPS_POS = [[0, [0.17, 0.18, 0.23]], [0.25, [0.85, 0.35, 0.12]], [0.7, [1.0, 0.54, 0.24]], [1, [1.0, 0.89, 0.42]]];
  const STOPS_NEG = [[0, [0.17, 0.18, 0.23]], [0.25, [0.18, 0.35, 0.85]], [0.7, [0.42, 0.63, 1.0]], [1, [0.72, 0.85, 1.0]]];
  function ramp(stops, x) {
    x = Math.max(0, Math.min(1, x));
    for (let i = 1; i < stops.length; i++) {
      if (x <= stops[i][0]) {
        const [x0, c0] = stops[i - 1], [x1, c1] = stops[i];
        const f = (x - x0) / (x1 - x0);
        return [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, c0[2] + (c1[2] - c0[2]) * f];
      }
    }
    return stops[stops.length - 1][1];
  }

  class BrainViewer {
    constructor(canvas) {
      this.canvas = canvas;
      this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(30, 1, 1, 2000);
      this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
      const key = new THREE.DirectionalLight(0xffffff, 0.7); key.position.set(1, 1, 2); this.scene.add(key);
      const fill = new THREE.DirectionalLight(0xffffff, 0.35); fill.position.set(-1, -0.5, -1); this.scene.add(fill);
      this.group = new THREE.Group(); this.scene.add(this.group);
      this.threshold = 0.15; this.scale = 1; this.data = null; this.roiOutlines = false;
      this.view = 'lateral'; this.orbit = { theta: 0, phi: 0, dist: 420 };
      this._bindMouse();
      this._resizeObs = new ResizeObserver(() => this.resize()); this._resizeObs.observe(canvas.parentElement);
      this.resize();
      const loop = () => { this.renderer.render(this.scene, this.camera); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }

    async load(url) {
      const m = await (await fetch(url)).json();
      if (m.error) throw new Error(m.error);
      this.mesh = m;
      this.coords = b64ToArray(m.coords, Float32Array);
      this.faces = b64ToArray(m.faces, Uint32Array);
      this.sulc = b64ToArray(m.sulc, Float32Array);
      this.parcel = b64ToArray(m.parcel, Uint16Array);
      this.nV = m.nV;
      // per-hemisphere meshes so medial views can hide one side
      this.hemis = [];
      for (let h = 0; h < 2; h++) {
        const lo = h * N_HEMI, hi = lo + N_HEMI;
        const idx = [];
        for (let f = 0; f < this.faces.length; f += 3) {
          if (this.faces[f] >= lo && this.faces[f] < hi) idx.push(this.faces[f] - lo, this.faces[f + 1] - lo, this.faces[f + 2] - lo);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(this.coords.subarray(lo * 3, hi * 3), 3));
        g.setIndex(idx);
        const colors = new Float32Array(N_HEMI * 3);
        g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        g.computeVertexNormals();
        const mat = new THREE.MeshLambertMaterial({ vertexColors: true });
        const mesh = new THREE.Mesh(g, mat);
        this.group.add(mesh);
        this.hemis.push({ mesh, colors, lo, hi });
      }
      this._buildRoiEdges();
      this.recolor();
      this.setView('oblique');
      return m;
    }

    _buildRoiEdges() {
      // edges whose two vertices belong to different ROI groups (or group vs none)
      const groups = this.mesh.roiGroups || {};
      const gid = new Uint8Array(this.nV);
      let k = 0;
      for (const key of Object.keys(groups)) {
        k++;
        const ids = new Set(groups[key].parcelIds || []);
        for (let v = 0; v < this.nV; v++) if (ids.has(this.parcel[v])) gid[v] = k;
      }
      const pos = [];
      const seen = new Set();
      const push = (a, b) => {
        if (gid[a] === gid[b]) return;
        const key = a < b ? a * 65536 + b : b * 65536 + a;
        if (seen.has(key)) return; seen.add(key);
        pos.push(this.coords[a * 3], this.coords[a * 3 + 1], this.coords[a * 3 + 2], this.coords[b * 3], this.coords[b * 3 + 1], this.coords[b * 3 + 2]);
      };
      for (let f = 0; f < this.faces.length; f += 3) {
        const a = this.faces[f], b = this.faces[f + 1], c = this.faces[f + 2];
        push(a, b); push(b, c); push(c, a);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
      this.edges = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x4cc3ff, transparent: true, opacity: 0.55 }));
      this.edges.visible = false;
      this.edges.scale.set(1.004, 1.004, 1.004);
      this.group.add(this.edges);
      this.groupIds = gid;
    }

    setRoiOutlines(on) { this.roiOutlines = !!on; if (this.edges) this.edges.visible = this.roiOutlines; }
    setThreshold(t) { this.threshold = t; this.recolor(); }
    /** data: Float32Array(nV) in model units; scale: value that maps to full colour */
    setData(data, opts) { this.data = data; if (opts && opts.scale) this.scale = opts.scale; this.recolor(); }

    recolor() {
      if (!this.hemis) return;
      const thr = this.threshold;
      for (const h of this.hemis) {
        const c = h.colors;
        for (let v = 0; v < N_HEMI; v++) {
          const s = this.sulc[h.lo + v];
          const bg = s > 0 ? 0.30 : 0.50;  // sulci darker
          let r = bg, g = bg, b = bg + 0.03;
          if (this.data) {
            const x = this.data[h.lo + v] / this.scale;
            const ax = Math.abs(x);
            if (ax > thr) {
              const f = Math.min(1, (ax - thr) / (1 - thr));
              const col = ramp(x > 0 ? STOPS_POS : STOPS_NEG, f);
              const a = Math.min(1, 0.35 + f * 0.9);
              r = bg * (1 - a) + col[0] * a; g = bg * (1 - a) + col[1] * a; b = bg * (1 - a) + col[2] * a;
            }
          }
          c[v * 3] = r; c[v * 3 + 1] = g; c[v * 3 + 2] = b;
        }
        h.mesh.geometry.attributes.color.needsUpdate = true;
      }
    }

    setView(name) {
      this.view = name;
      const [L, R] = this.hemis.map(h => h.mesh);
      L.visible = R.visible = true;
      if (this.edges) this.edges.visible = this.roiOutlines;
      // theta: azimuth around z (up); phi: elevation
      const views = {
        oblique: { theta: -0.55, phi: 0.85, dist: 470 },        // both hemispheres, from above and slightly front-left
        lateral: { theta: -Math.PI / 2, phi: 0.05, dist: 330 },  // left hemisphere, lateral surface
        lateralR: { theta: Math.PI / 2, phi: 0.05, dist: 330 },
        medial: { theta: Math.PI / 2, phi: 0.05, dist: 300 },
        top: { theta: 0, phi: Math.PI / 2 - 0.01, dist: 380 },
        front: { theta: 0, phi: 0.05, dist: 380 },
        back: { theta: Math.PI, phi: 0.05, dist: 380 },
      };
      const v = views[name] || views.oblique;
      this.orbit = { ...v };
      if (name === 'medial') { R.visible = false; }  // show left hemisphere from the right (medial wall)
      if (name === 'lateral') { R.visible = false; }
      if (name === 'lateralR') { L.visible = false; }
      this._applyCamera();
    }

    _applyCamera() {
      const { theta, phi, dist } = this.orbit;
      // x right, y anterior, z up (fsaverage). Camera orbits around origin.
      const x = dist * Math.cos(phi) * Math.sin(theta);
      const y = dist * Math.cos(phi) * Math.cos(theta);  // theta 0 = camera anterior (front view)
      const z = dist * Math.sin(phi);
      this.camera.position.set(x, y, z);
      this.camera.up.set(0, 0, 1);
      this.camera.lookAt(0, 0, 0);
    }

    _bindMouse() {
      let drag = null;
      const c = this.canvas;
      c.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); });
      c.addEventListener('pointermove', e => {
        if (!drag) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY };
        this.orbit.theta += dx * 0.01;
        this.orbit.phi = Math.max(-1.5, Math.min(1.5, this.orbit.phi + dy * 0.01));
        this._applyCamera();
      });
      c.addEventListener('pointerup', () => { drag = null; });
      c.addEventListener('wheel', e => { e.preventDefault(); this.orbit.dist = Math.max(150, Math.min(900, this.orbit.dist * (1 + e.deltaY * 0.001))); this._applyCamera(); }, { passive: false });
    }

    resize() {
      const el = this.canvas.parentElement;
      const w = el.clientWidth || 400, h = el.clientHeight || 300;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    }
  }

  window.BrainViewer = BrainViewer;
  window.b64ToArray = b64ToArray;
})();
