import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── 3D scene ──────────────────────────────────────────────────────────────────
const viewport = document.getElementById('viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x202836);
const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1e9);
const renderer = new THREE.WebGLRenderer({ antialias: true });
viewport.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 2.2));
const dir1 = new THREE.DirectionalLight(0xffffff, 1.6);
dir1.position.set(1, 2, 1);
scene.add(dir1);
const dir2 = new THREE.DirectionalLight(0x8be9fd, 0.8);
dir2.position.set(-1, -0.5, -1);
scene.add(dir2);

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
    clearLayer('grids');
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10),
        new THREE.MeshLambertMaterial({ color: 0x50fa7b }));
    layers.grids.add(mesh);
    addLabel(g.name, new THREE.Vector3(0, 14, 0));
    frameScene(60);
}

// ── Tile decode: voxels with per-tile orientation ─────────────────────────────
const ORE_NAMES = ['Iron','Nickel','Gold','Silver','Cobalt','Copper','Silicon',
                   'Uranium','Uraninite','Platinum','Magnesium','Chromium',
                   'Titanium','Lead','Ice'];
const ORE_COLORS = {
    Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
    Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
    Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
    Chromium: 0xaadccc, Titanium: 0xdca0a0,
};
function isOreName(name) {
    const s = (name || '').toLowerCase();
    return ['ore','iron','nickel','gold','silver','cobalt','copper','silicon','uranium',
            'uraninite','platinum','magnesium','chromium','titanium','lead','ice']
        .some(k => s.includes(k));
}

// Per-tile oriented instanced rendering: each tile has basis axes (may be rotated);
// voxels within a tile are placed in tile basis. Brighter materials.
function renderTiles(tiles, legend, gridPos, radius) {
    clearLayer('voxels');
    const oreIds = {};
    for (const entry of legend) {
        const idx = parseInt(entry.split('=')[0]);
        const name = entry.split('=').slice(1).join('=');
        if (isOreName(name)) oreIds[idx] = name;
    }
    const ORE_PALETTE = [0xc678dd, 0xffb86c, 0x8be9fd, 0x50fa7b, 0xff5555, 0xf1fa8c];

    let tileIdx = 0;
    const span = radius * 2;
    const nextTile = () => {
        if (tileIdx >= tiles.length) return null;
        const tile = tiles[tileIdx++];
        // world center of the tile
        const c = tile.origin;
        const ax = tile.axisX, ay = tile.axisY, az = tile.axisZ;
        const m = new THREE.Matrix4().makeBasis(
            new THREE.Vector3(ax[0], ax[1], ax[2]),
            new THREE.Vector3(ay[0], ay[1], ay[2]),
            new THREE.Vector3(az[0], az[1], az[2]));
        const q = new THREE.Quaternion().setFromRotationMatrix(m);
        const worldCenter = new THREE.Vector3(c[0], c[1], c[2]);
        return { tile, q, worldCenter };
    };

    // decode loop per tile, building one InstancedMesh per tile per material
    let done = 0;
    const step = () => {
        const batchStart = time.now0;
        while (done < tiles.length) {
            const tile = tiles[done++];
            decodeTile(tile);
            if (performance.now() - batchStart > 16) { setTimeout(step, 0); return; }
        }
        finish();
    };

    function decodeTile(tile) {
        const content = atob(tile.content);
        const material = tile.material ? atob(tile.material) : null;
        const nx = tile.size[0], ny = tile.size[1], nz = tile.size[2];
        const origin = tile.origin;
        const ax = tile.axisX, ay = tile.axisY, az = tile.axisZ;
        const basis = new THREE.Matrix4().makeBasis(
            new THREE.Vector3(ax[0], ax[1], ax[2]),
            new THREE.Vector3(ay[0], ay[1], ay[2]),
            new THREE.Vector3(az[0], az[1], az[2]));
        const quat = new THREE.Quaternion().setFromRotationMatrix(basis);
        const voxelScale = Math.cbrt(Math.abs(
            (ax[0]*(ay[1]*az[2]-ay[2]*az[1]) - ax[1]*(ay[0]*az[2]-ay[2]*az[0]) + ax[2]*(ay[0]*az[1]-ay[1]*az[0]))));

        // group voxels: solid non-ore and ore-by-name
        const groups = {};
        const data = new Uint8Array(nx * ny * nz);
        for (let i = 0; i < content.length; i++) data[i] = content[i];
        const mData = material ? new Uint8Array(nx * ny * nz) : null;
        if (material) for (let i = 0; i < material.length; i++) mData[i] = material[i];

        for (let z = 0; z < nz; z++)
        for (let y = 0; y < ny; y++)
        for (let x = 0; x < nx; x++) {
            const i = x + nx * (y + ny * z);
            if (!data[i]) continue;
            let matId = material ? mData[i] : -1;
            const oreName = (material !== null && oreIds[matId]) ? oreIds[matId] : null;
            const key = oreName ? 'ore:' + oreName : 'solid';
            (groups[key] = groups[key] || []).push([x + 0.5, y + 0.5, z + 0.5]);
        }

        for (const [key, locals] of Object.entries(groups)) {
            const isOre = key.startsWith('ore:');
            const geo = new THREE.BoxGeometry(1, 1, 1);
            const mat = isOre
                ? new THREE.MeshLambertMaterial({ color: ORE_PALETTE[hashCode(key) % ORE_PALETTE.length],
                                                  emissive: ORE_PALETTE[hashCode(key) % ORE_PALETTE.length],
                                                  emissiveIntensity: 0.35 })
                : new THREE.MeshLambertMaterial({ color: 0xd8d8e0 });
            const inst = new THREE.InstancedMesh(geo, mat, locals.length);
            const dummy = new THREE.Object3D();
            dummy.quaternion.copy(quat);
            locals.forEach((l, i) => {
                const wp = new THREE.Vector3(origin[0] + l[0]*ax[0] + l[1]*ay[0] + l[2]*az[0] - gridPos[0],
                                             origin[1] + l[0]*ax[1] + l[1]*ay[1] + l[2]*az[1] - gridPos[1],
                                             origin[2] + l[0]*ax[2] + l[1]*ay[2] + l[2]*az[2] - gridPos[2]);
                dummy.position.copy(wp);
                dummy.updateMatrix();
                inst.setMatrixAt(i, dummy.matrix);
            });
            inst.instanceMatrix.needsUpdate = true;
            layers.voxels.add(inst);
            if (isOre) {
                const c = locals.reduce((a, l) => [a[0]+l[0]/locals.length, a[1]+l[1]/locals.length, a[2]+l[2]/locals.length], [0,0,0]);
                const wp = new THREE.Vector3(
                    origin[0] + c[0]*ax[0] + c[1]*ay[0] + c[2]*az[0] - gridPos[0],
                    origin[1] + c[0]*ax[1] + c[1]*ay[1] + c[2]*az[1] - gridPos[1],
                    origin[2] + c[0]*ax[2] + c[1]*ay[2] + c[2]*az[2] - gridPos[2]);
                addLabel(key.slice(4) + ' ×' + locals.length, wp.clone().add(new THREE.Vector3(0, 8, 0)), 'ore');
            }
        }
    }

    const origin = selectedGrid ? selectedGrid.position : [0,0,0];
    const gridPos = origin;
    for (const tile of tiles) decodeTile(tile);

    let maxSpan = 60;
    for (const tile of tiles) {
        const c = tile.origin;
        maxSpan = Math.max(maxSpan, Math.abs(c[0]-gridPos[0]), Math.abs(c[1]-gridPos[1]), Math.abs(c[2]-gridPos[2]));
    }
    frameScene(maxSpan * 1.6);
}

function hashCode(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
}

// ── Buttons wiring ────────────────────────────────────────────────────────────
async function runScan(kind) {
    if (!selectedGrid) { setStatus('выбери грид'); return; }
    const radius = parseFloat(document.getElementById('scan-radius').value) || 32;
    setStatus('скан (' + kind + ')...');
    let url = kind === 'deposits' ? '/api/deposits' : '/api/voxel_scan';
    const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return; }
    const rid = data.request_id;
    const timer = setInterval(async () => {
        const st = await (await fetch(`/api/${kind === 'deposits' ? 'deposits_result' : 'voxel_status'}/${rid}`)).json();
        const doneStates = ['complete', 'partial', 'rejected', 'failed'];
        if (doneStates.includes(st.state) || st.scanning === false) {
            clearInterval(timer);
            if (kind === 'deposits') { renderDepositsResult(st); return; }
            // voxel tiles path
            loadTiles(rid);
        }
    }, 1000);
}

async function loadTiles(rid) {
    const res = await fetch(`/api/voxel_tiles/${rid}`);
    const data = await res.json();
    if (data.error) { setStatus('нет тайлов: ' + data.error); return; }
    renderTiles(data.tiles || [], data.legend || []);
}

async function loadAsteroids(rid) {
    const st = await (await fetch(`/api/asteroids/${rid}`)).json();
    if (st.error || !st.asteroids) { setStatus('ошибка: ' + (st.error || 'нет данных')); return; }
    renderAsteroidField(st.asteroids);
}

async function loadDepositsResult(rid) {
    const st = await (await fetch(`/api/deposits_result/${rid}`)).json();
    if (st.error || !st.deposits) { setStatus('нет депозитов'); return; }
    renderDeposits(st.deposits);
}

function renderAsteroidField(asteroids) {
    clearLayer('asteroids');
    if (!selectedGrid?.position || !asteroids.length) { setStatus('астероидов не найдено'); return; }
    const origin = selectedGrid.position;
    for (const a of asteroids) {
        const cx = a.center[0] - origin[0], cy = a.center[1] - origin[1], cz = a.center[2] - origin[2];
        const wx = Math.max(4, a.max[0] - a.min[0]), wy = Math.max(4, a.max[1] - a.min[1]), wz = Math.max(4, a.max[2] - a.min[2]);
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(wx, wy, wz),
            new THREE.MeshLambertMaterial({ color: 0xffb86c, transparent: true, opacity: 0.35 }));
        mesh.position.set(cx, cy, cz);
        layers.asteroids.add(mesh);
        const dist = Math.sqrt(cx*cx + cy*cy + cz*cz);
        addLabel(`Астероид ${Math.round(Math.max(wx,wy,wz))}м (${Math.round(dist/100)*100} м)`,
            new THREE.Vector3(cx, cy + wy/2 + 10, cz), 'ast');
    }
    setStatus(`астероидов: ${asteroids.length}`);
    frameScene(Math.max(...asteroids.flatMap(a => [a.max[0]-a.min[0], a.max[1]-a.min[1], a.max[2]-a.min[2], 50])) * 2.2);
}

function renderDeposits(deposits) {
    clearLayer('deposits');
    if (!selectedGrid?.position) return;
    const origin = selectedGrid.position;
    const oreDeps = deposits.filter(d => !d.material.startsWith('Asteroid') && d.material !== 'Stone');
    for (const d of oreDeps.slice(0, 300)) {
        const cx = d.center[0] - origin[0], cy = d.center[1] - origin[1], cz = d.center[2] - origin[2];
        const color = ORE_COLORS[d.material] || 0xc678dd;
        const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(8),
            new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.5 }));
        mesh.position.set(cx, cy, cz);
        layers.deposits.add(mesh);
        addLabel(`${d.material}`, new THREE.Vector3(cx, cy + 12, cz), 'ore');
    }
    setStatus(`рудных депозитов: ${oreDeps.length}`);
}

// ── Buttons ───────────────────────────────────────────────────────────────────
document.getElementById('btn-voxels').addEventListener('click', () => runScan('voxels'));
document.getElementById('btn-deposits').addEventListener('click', () => runScan('deposits'));
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
    loadAsteroids(data.request_id);
});

loadGrids();
setInterval(loadGrids, 15000);
