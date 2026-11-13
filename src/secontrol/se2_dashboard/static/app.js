import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── 3D scene ──────────────────────────────────────────────────────────────────
const viewport = document.getElementById('viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = null;
const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1e9);
const renderer = new THREE.WebGLRenderer({ antialias: true });
viewport.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.AmbientLight(0x404060, 1.8));
const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
dirLight.position.set(1, 2, 1);
scene.add(dirLight);

function resize() {
    const w = viewport.clientWidth, h = viewport.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}
window.addEventListener('resize', resize);
resize();

const layers = {
    voxels: new THREE.Group(),
    asteroids: new THREE.Group(),
    deposits: new THREE.Group(),
    grids: new THREE.Group(),
};
Object.values(layers).forEach(g => scene.add(g));

const labels = [];
function addLabel(text, position, cls = '', onclick = null) {
    const el = document.createElement('div');
    el.className = 'label-3d ' + cls;
    el.textContent = text;
    viewport.appendChild(el);
    const entry = { el, position: position.clone() };
    if (onclick) el.addEventListener('click', onclick);
    labels.push(entry);
    return entry;
}
function clearLayer(name) {
    layers[name].clear();
    // labels tied to this layer: simplest policy — clear all labels on layer clear
    labels.forEach(l => l.el.remove());
    labels.length = 0;
}
function updateLabels() {
    const w = viewport.clientWidth, h = viewport.clientHeight;
    for (const label of labels) {
        const pos = label.position.clone().project(camera);
        if (pos.z > 1) { label.el.style.display = 'none'; continue; }
        label.el.style.display = '';
        label.el.style.left = (pos.x * w / 2 + w / 2) + 'px';
        label.el.style.top = (-pos.y * h / 2 + h / 2) + 'px';
    }
}

function animate() {
    requestAnimationFrame(animate);
    controls.update();
    updateLabels();
    renderer.render(scene, camera);
}
animate();

function frameScene(span) {
    camera.position.set(span * 0.9, span * 0.7, span * 0.9);
    controls.target.set(0, 0, 0);
    controls.update();
}

// ── UI state ──────────────────────────────────────────────────────────────────
let selectedGrid = null;
const statusEl = document.getElementById('status');

function setStatus(text) { statusEl.textContent = text; }

async function loadGrids() {
    const res = await fetch('/api/grids');
    const data = await res.json();
    const bridge = document.getElementById('bridge-status');
    if (data.error) { bridge.textContent = 'мост: OFFLINE (' + data.error + ')'; return; }
    bridge.textContent = `мост: OK, гридов: ${data.grids.length}`;
    const list = document.getElementById('grid-list');
    list.innerHTML = '';
    for (const g of data.grids) {
        const el = document.createElement('div');
        el.className = 'grid-item';
        el.innerHTML = `<div>${g.name || g.grid_id}</div><div class="pos">${g.grid_id}</div>`;
        el.addEventListener('click', () => selectGrid(g, el));
        list.appendChild(el);
    }
}

function selectGrid(g, el) {
    selectedGrid = g;
    document.querySelectorAll('.grid-item').forEach(x => x.classList.remove('active'));
    el.classList.add('active');
    const detail = document.getElementById('grid-detail');
    detail.classList.remove('hidden');
    const pos = g.position || [0, 0, 0];
    detail.innerHTML = `<b>${g.name}</b><br>id: ${g.grid_id}<br>позиция: [${pos.map(v => Math.round(v)).join(', ')}]`;
    document.getElementById('actions').classList.remove('hidden');
    // draw selected grid marker at scene origin
    clearLayer('grids');
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10),
        new THREE.MeshLambertMaterial({ color: 0x50fa7b }));
    layers.grids.add(mesh);
    addLabel(g.name, new THREE.Vector3(0, 14, 0));
}

// ── Voxel scan around grid ────────────────────────────────────────────────────
document.getElementById('btn-voxels').addEventListener('click', async () => {
    if (!selectedGrid) return;
    const radius = parseFloat(document.getElementById('scan-radius').value) || 32;
    setStatus('скан вокселей...');
    const res = await fetch('/api/voxel_scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return; }
    const timer = setInterval(async () => {
        const st = await (await fetch(`/api/voxel_status/${data.request_id}`)).json();
        setStatus(`скан: ${st.state}, плиток ${st.published || 0}`);
        if (!st.scanning) {
            clearInterval(timer);
            const vox = await (await fetch(`/api/voxels/${data.request_id}`)).json();
            if (vox.error) { setStatus('нет данных: ' + vox.error); return; }
            renderVoxels(vox);
        }
    }, 1000);
});

const ORE_COLORS = {
    Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
    Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
    Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
    Chromium: 0xaadccc, Titanium: 0xdca0a0,
};

function renderVoxels(data) {
    clearLayer('voxels');
    const solid = data.solid || [];
    const ores = data.ore_cells || [];
    const cell = (data.metadata || {}).cellSize || 1;
    setStatus(`вокселей: ${solid.length}, руд: ${ores.length}`);
    if (!solid.length && !ores.length) return;

    // instanced stone
    if (solid.length) {
        const geo = new THREE.BoxGeometry(cell, cell, cell);
        const mat = new THREE.MeshLambertMaterial({ color: 0x9a9a9a, transparent: true, opacity: 0.25 });
        const inst = new THREE.InstancedMesh(geo, mat, solid.length);
        const dummy = new THREE.Object3D();
        for (let i = 0; i < solid.length; i++) {
            dummy.position.set(solid[i][0], solid[i][1], solid[i][2]);
            dummy.updateMatrix();
            inst.setMatrixAt(i, dummy.matrix);
        }
        inst.instanceMatrix.needsUpdate = true;
        layers.voxels.add(inst);
    }
    // ores grouped by type
    const byType = {};
    for (const o of ores) (byType[o.ore] = byType[o.ore] || []).push(o.position);
    let idx = 0;
    for (const [ore, positions] of Object.entries(byType)) {
        const color = ORE_COLORS[ore] || 0xc678dd;
        const geo = new THREE.BoxGeometry(cell, cell, cell);
        const mat = new THREE.MeshLambertMaterial({ color, transparent: true, opacity: 0.95 });
        const inst = new THREE.InstancedMesh(geo, mat, positions.length);
        const dummy = new THREE.Object3D();
        positions.forEach((p, i) => {
            dummy.position.set(p[0], p[1], p[2]);
            dummy.updateMatrix();
            inst.setMatrixAt(i, dummy.matrix);
        });
        inst.instanceMatrix.needsUpdate = true;
        layers.voxels.add(inst);
        const centroid = positions.reduce((a, p) => [a[0]+p[0]/positions.length, a[1]+p[1]/positions.length, a[2]+p[2]/positions.length], [0,0,0]);
        addLabel(`${ore} ×${positions.length}`, new THREE.Vector3(centroid[0], centroid[1] + 12, centroid[2]), 'ore');
    }
    // sibling grids as blue wireframe boxes
    if (selectedGrid && selectedGrid.position) {
        const pts = [];
        for (const c of (data.contacts || [])) {
            if (!c.position) continue;
            pts.push([c.position[0] - selectedGrid.position[0],
                      c.position[1] - selectedGrid.position[1],
                      c.position[2] - selectedGrid.position[2], c.name]);
        }
        for (const [x, y, z, name] of pts) {
            const mesh = new THREE.Mesh(new THREE.BoxGeometry(8, 8, 8),
                new THREE.MeshLambertMaterial({ color: 0x3a86ff, wireframe: true, transparent: true, opacity: 0.7 }));
            mesh.position.set(x, y, z);
            layers.voxels.add(mesh);
        }
    }
    frameScene(Math.max(radiusOf(solid), 60));
}

function radiusOf(points) {
    let m = 0;
    for (const p of points) m = Math.max(m, Math.abs(p[0]), Math.abs(p[1]), Math.abs(p[2]));
    return m * 2 + 20;
}

// ── Asteroid index (from seed) ────────────────────────────────────────────────
document.getElementById('btn-asteroids').addEventListener('click', async () => {
    if (!selectedGrid) return;
    const km = parseFloat(document.getElementById('asteroid-radius').value) || 40;
    setStatus('индекс астероидов из сида...');
    const res = await fetch('/api/asteroid_index', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius: km }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return; }
    const timer = setInterval(async () => {
        const st = await (await fetch(`/api/asteroids/${data.request_id}`)).json();
        if (st.state === 'complete' || st.state === 'partial') {
            clearInterval(timer);
            renderAsteroids(st.asteroids || []);
            setStatus(`астероидов: ${st.count}`);
        } else if (st.error || st.state === 'rejected' || st.state === 'failed') {
            clearInterval(timer);
            setStatus('ошибка индекса: ' + (st.error || st.state));
        }
    }, 1000);
});

function renderAsteroids(asteroids) {
    clearLayer('asteroids');
    if (!asteroids.length || !selectedGrid?.position) return;
    const origin = selectedGrid.position;
    let maxSpan = 50;
    for (const a of asteroids) {
        const cx = a.center[0] - origin[0], cy = a.center[1] - origin[1], cz = a.center[2] - origin[2];
        const wx = Math.max(4, a.max[0] - a.min[0]), wy = Math.max(4, a.max[1] - a.min[1]), wz = Math.max(4, a.max[2] - a.min[2]);
        maxSpan = Math.max(maxSpan, Math.abs(cx) + wx, Math.abs(cy) + wy, Math.abs(cz) + wz);
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(wx, wy, wz),
            new THREE.MeshLambertMaterial({ color: 0xffb86c, transparent: true, opacity: 0.4 }));
        mesh.position.set(cx, cy, cz);
        layers.asteroids.add(mesh);
        const dist = Math.sqrt(cx * cx + cy * cy + cz * cz);
        const center = a.center;
        addLabel(`астероид ${Math.round(Math.max(wx, wy, wz))}м (${Math.round(dist)} м)`,
            new THREE.Vector3(cx, cy + wy / 2 + 8, cz), 'ast',
            () => {
                const gps = `GPS:Asteroid:${center[0]}:${center[1]}:${center[2]}:`;
                navigator.clipboard?.writeText(gps);
                setStatus('GPS скопирован: ' + gps);
            });
    }
    frameScene(maxSpan * 2);
}

// ── Ore deposits ──────────────────────────────────────────────────────────────
document.getElementById('btn-deposits').addEventListener('click', async () => {
    if (!selectedGrid) return;
    setStatus('детекция рудных депозитов...');
    const res = await fetch('/api/deposits', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius: 32 }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return; }
    const timer = setInterval(async () => {
        const st = await (await fetch(`/api/deposits_result/${data.request_id}`)).json();
        if (st.state === 'complete' || st.state === 'partial') {
            clearInterval(timer);
            renderDeposits(st.deposits || []);
            setStatus(`депозитов руды: ${st.count}`);
        } else if (st.error) {
            clearInterval(timer);
            setStatus('ошибка: ' + st.error);
        }
    }, 1000);
});

function renderDeposits(deposits) {
    clearLayer('deposits');
    if (!deposits.length || !selectedGrid?.position) return;
    const origin = selectedGrid.position;
    const oreDeps = deposits.filter(d => !d.material.startsWith('Asteroid') && d.material !== 'Stone');
    let span = 50;
    for (const d of oreDeps.slice(0, 200)) {
        const cx = d.center[0] - origin[0], cy = d.center[1] - origin[1], cz = d.center[2] - origin[2];
        span = Math.max(span, Math.abs(cx), Math.abs(cy), Math.abs(cz));
        const s = 6;
        const color = ORE_COLORS[d.material] || 0xc678dd;
        const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(s),
            new THREE.MeshLambertMaterial({ color }));
        mesh.position.set(cx, cy, cz);
        layers.deposits.add(mesh);
    }
    if (oreDeps.length) {
        const first = oreDeps[0];
        addLabel(`${first.material} ×${oreDeps.length} (ближайшая)`,
            new THREE.Vector3(first.center[0] - origin[0], first.center[1] - origin[1] + 10, first.center[2] - origin[2]), 'ore');
    }
    frameScene(span * 2);
}

loadGrids();
setInterval(loadGrids, 15000);
