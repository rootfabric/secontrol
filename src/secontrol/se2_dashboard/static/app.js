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

const layers = { voxels: new THREE.Group(), asteroids: new THREE.Group(),
                 deposits: new THREE.Group(), grids: new THREE.Group() };
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

// ── UI ────────────────────────────────────────────────────────────────────────
let selectedGrid = null;
const statusEl = document.getElementById('status');
const setStatus = t => statusEl.textContent = t;

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
    layers.grids.add(new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10),
        new THREE.MeshLambertMaterial({ color: 0x50fa7b })));
    addLabel(g.name, new THREE.Vector3(0, 14, 0));
    frameScene(60);
}

// ── Ore palette ───────────────────────────────────────────────────────────────
const ORE_NAMES = ['iron','nickel','gold','silver','cobalt','copper','silicon',
                   'uranium','uraninite','platinum','magnesium','chromium',
                   'titanium','lead','ice'];
const ORE_COLORS = {
    Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
    Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
    Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
    Chromium: 0xaadccc, Titanium: 0xdca0a0,
};
function isOreName(name) {
    const s = (name || '').toLowerCase();
    return ORE_NAMES.some(k => s.includes(k));
}
function oreColor(name) {
    for (const key of ORE_NAMES)
        if ((name || '').toLowerCase().includes(key))
            return ORE_COLORS[key.charAt(0).toUpperCase() + key.slice(1)] || 0xc678dd;
    return 0xc678dd;
}

// ── Voxel render: per-tile oriented instanced cubes ───────────────────────────
function renderVoxelTiles(tiles, legend, gridPos) {
    clearLayer('voxels');
    const oreIds = {};
    for (const entry of legend) {
        const idx = parseInt(entry.split('=')[0]);
        const name = entry.split('=').slice(1).join('=');
        if (isOreName(name)) oreIds[idx] = name;
    }
    for (const tile of tiles) {
        const content = Uint8Array.from(atob(tile.content), ch => ch.charCodeAt(0));
        const material = tile.material ? Uint8Array.from(atob(tile.material), ch => ch.charCodeAt(0)) : null;
        const nx = tile.size[0], ny = tile.size[1], nz = tile.size[2];
        const origin = tile.origin;
        const ax = tile.axisX, ay = tile.axisY, az = tile.axisZ;
        const quat = new THREE.Quaternion().setFromRotationMatrix(
            new THREE.Matrix4().makeBasis(
                new THREE.Vector3(ax[0], ax[1], ax[2]),
                new THREE.Vector3(ay[0], ay[1], ay[2]),
                new THREE.Vector3(az[0], az[1], az[2])));

        const groups = {};
        for (let z = 0; z < nz; z++)
        for (let y = 0; y < ny; y++)
        for (let x = 0; x < nx; x++) {
            const i = x + nx * (y + ny * z);
            if (!content[i]) continue;
            const matId = material ? material[i] : -1;
            const oreName = (matId in oreIds) ? oreIds[matId] : null;
            const key = oreName ? 'ore:' + oreName : 'solid';
            (groups[key] = groups[key] || []).push([x + 0.5, y + 0.5, z + 0.5]);
        }

        for (const [key, locals] of Object.entries(groups)) {
            const isOre = key.startsWith('ore:');
            const oreName = isOre ? key.slice(4) : null;
            const color = isOre ? oreColor(oreName) : 0xd8d8e0;
            const geo = new THREE.BoxGeometry(1, 1, 1);
            const mat = isOre
                ? new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.3 })
                : new THREE.MeshLambertMaterial({ color: 0xd8d8e0, transparent: true, opacity: 0.55 });
            const inst = new THREE.InstancedMesh(geo, mat, locals.length);
            const dummy = new THREE.Object3D();
            dummy.quaternion.copy(quat);
            locals.forEach((l, i) => {
                dummy.position.set(
                    origin[0] + l[0]*ax[0] + l[1]*ay[0] + l[2]*az[0] - gridPos[0],
                    origin[1] + l[0]*ax[1] + l[1]*ay[1] + l[2]*az[1] - gridPos[1],
                    origin[2] + l[0]*ax[2] + l[1]*ay[2] + l[2]*az[2] - gridPos[2]);
                dummy.updateMatrix();
                inst.setMatrixAt(i, dummy.matrix);
            });
            inst.instanceMatrix.needsUpdate = true;
            layers.voxels.add(inst);
            if (isOre && locals.length >= 20) {
                const c = locals.reduce((a, l) => [a[0]+l[0]/locals.length, a[1]+l[1]/locals.length, a[2]+l[2]/locals.length], [0,0,0]);
                const wp = new THREE.Vector3(
                    origin[0] + c[0]*ax[0] + c[1]*ay[0] + c[2]*az[0] - gridPos[0],
                    origin[1] + c[0]*ax[1] + c[1]*ay[1] + c[2]*az[1] - gridPos[1],
                    origin[2] + c[0]*ax[2] + c[1]*ay[2] + c[2]*az[2] - gridPos[2]);
                addLabel(oreName + ' ×' + locals.length, wp.add(new THREE.Vector3(0, 6, 0)), 'ore');
            }
        }
    }
}

// ── Asteroid index render ─────────────────────────────────────────────────────
function renderAsteroidField(asteroids, gridPos) {
    clearLayer('asteroids');
    for (const a of asteroids) {
        const cx = a.center[0] - gridPos[0], cy = a.center[1] - gridPos[1], cz = a.center[2] - gridPos[2];
        const wx = Math.max(4, a.max[0] - a.min[0]), wy = Math.max(4, a.max[1] - a.min[1]), wz = Math.max(4, a.max[2] - a.min[2]);
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(wx, wy, wz),
            new THREE.MeshLambertMaterial({ color: 0xffb86c, transparent: true, opacity: 0.12,
                                            depthWrite: false, wireframe: true }));
        mesh.position.set(cx, cy, cz);
        layers.asteroids.add(mesh);
        const dist = Math.sqrt(cx*cx + cy*cy + cz*cz);
        const center = a.center;
        addLabel(`Астероид ${Math.round(Math.max(wx,wy,wz))}м (${Math.round(dist/100)*100} м)`,
            new THREE.Vector3(cx, cy + wy/2 + 10, cz), 'ast',
            () => {
                const gps = `GPS:Asteroid:${center[0]}:${center[1]}:${center[2]}:`;
                navigator.clipboard?.writeText(gps);
                setStatus('GPS скопирован: ' + gps);
            });
    }
    let span = 60;
    for (const a of asteroids)
        span = Math.max(span, distance(a.center, gridPos) * 1.1 + 50);
    frameScene(span);
}

// ── Deposits render ───────────────────────────────────────────────────────────
function renderDeposits(deposits, gridPos) {
    clearLayer('deposits');
    const oreDeps = deposits.filter(d => !d.material.startsWith('Asteroid') && d.material !== 'Stone');
    for (const d of oreDeps.slice(0, 300)) {
        const cx = d.center[0] - gridPos[0], cy = d.center[1] - gridPos[1], cz = d.center[2] - gridPos[2];
        const color = oreColor(d.material);
        const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(8),
            new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.5 }));
        mesh.position.set(cx, cy, cz);
        layers.deposits.add(mesh);
        addLabel(d.material, new THREE.Vector3(cx, cy + 12, cz), 'ore');
    }
    setStatus(`рудных депозитов: ${oreDeps.length}`);
}

function distance(a, b) {
    return Math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2);
}

// ── Scans ─────────────────────────────────────────────────────────────────────
async function runScan(kind, radius) {
    if (!selectedGrid) { setStatus('выбери грид'); return; }
    setStatus('скан (' + kind + ')...');
    const res = await fetch('/api/' + (kind === 'deposits' ? 'deposits' : 'voxel_scan'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return null; }
    const rid = data.request_id;
    const deadline = timeNow() + 240;
    while (timeNow() < deadline) {
        try {
            const st = await (await fetch(`/api/${kind === 'deposits' ? 'deposits_result' : 'voxel_status'}/${rid}`)).json();
            if (!st.scanning && (st.state === 'complete' || st.state === 'partial')) return rid;
            if (st.error || st.state === 'rejected' || st.state === 'failed') { setStatus('ошибка: ' + (st.error || st.state)); return null; }
        } catch (e) { /* transient */ }
        await sleep(1.0);
    }
    setStatus('таймаут скана');
    return null;
}
const timeNow = () => performance.now() / 1000;
const sleep = s => new Promise(r => setTimeout(r, s * 1000));

document.getElementById('btn-voxels').addEventListener('click', async () => {
    const radius = parseFloat(document.getElementById('scan-radius').value) || 32;
    const rid = await runScan('voxels', radius);
    if (!rid) return;
    const tiles = await (await fetch(`/api/voxel_tiles/${rid}`)).json();
    if (tiles.error) { setStatus('нет тайлов: ' + tiles.error); return; }
    const gp = selectedGrid.position;
    renderVoxelTiles(tiles.tiles, tiles.legend || [], gp);
    setStatus(`тайлов: ${(tiles.tiles || []).length}`);
});

document.getElementById('btn-deposits').addEventListener('click', async () => {
    const rid = await runScan('deposits', 32);
    if (!rid) return;
    const res = await (await fetch(`/api/deposits_result/${rid}`)).json();
    if (res.error) { setStatus('нет депозитов: ' + res.error); return; }
    renderDeposits(res.deposits || [], selectedGrid.position);
    setStatus(`депозитов: ${(res.deposits || []).length}`);
});

document.getElementById('btn-asteroids').addEventListener('click', async () => {
    const km = parseFloat(document.getElementById('asteroid-radius').value) || 40;
    if (!selectedGrid) { setStatus('выбери грид'); return; }
    setStatus('индекс астероидов из сида...');
    const res = await fetch('/api/asteroid_index', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius: km }),
    });
    const data = await res.json();
    if (data.error) { setStatus('ошибка: ' + data.error); return; }
    const rid = data.request_id;
    const deadline = timeNow() + 120;
    let asteroids = null;
    while (timeNow() < deadline) {
        const st = await (await fetch(`/api/asteroids/${rid}`)).json();
        if (st.state === 'complete' || st.state === 'partial') { asteroids = st.asteroids || []; break; }
        if (st.error || st.state === 'rejected' || st.state === 'failed') { setStatus('ошибка: ' + (st.error || st.state)); return; }
        await sleep(1.0);
    }
    if (!asteroids) { setStatus('таймаут индекса'); return; }
    // dedup by rounded center
    const seen = {};
    const unique = asteroids.filter(a => {
        const k = a.center.map(v => Math.round(v)).join(',');
        if (seen[k]) return false;
        seen[k] = true;
        return true;
    });
    renderAsteroidField(unique, selectedGrid.position);
    setStatus(`астероидов: ${unique.length}`);
});

loadGrids();
setInterval(loadGrids, 15000);

// ── Multi-asteroid ore scan: voxel-scan around each indexed asteroid ──────────
document.getElementById('btn-asteroid-scan').addEventListener('click', async () => {
    if (!selectedGrid) { setStatus('выбери грид'); return; }
    const km = parseFloat(document.getElementById('asteroid-radius').value) || 40;
    setStatus('индекс астероидов...');
    const res = await fetch('/api/asteroid_index', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius: km }),
    });
    const idx = await res.json();
    if (idx.error) { setStatus('ошибка индекса: ' + idx.error); return; }
    const rid = idx.request_id;
    const timer = setInterval(async () => {
        const st = await (await fetch(`/api/asteroids/${rid}`)).json();
        if (st.state !== 'complete' && st.state !== 'partial') return;
        clearInterval(timer);
        const asteroids = dedupAsteroids(st.asteroids || []);
        setStatus(`астероидов: ${asteroids.length} — сканирую каждый...`);
        scanAll(asteroids.slice(0, 15));
    }, 1000);
});

function dedupAsteroids(list) {
    const seen = {};
    const out = [];
    for (const a of list) {
        const k = a.center.map(v => Math.round(v)).join(',');
        if (!seen[k]) { seen[k] = true; out.push(a); }
    }
    return out;
}

async function scanAll(asteroids) {
    const origin = selectedGrid.position;
    let found = 0;
    for (let i = 0; i < asteroids.length; i++) {
        const a = asteroids[i];
        const d = Math.sqrt((a.center[0]-origin[0])**2 + (a.center[1]-origin[1])**2 + (a.center[2]-origin[2])**2);
        setStatus(`скан ${i+1}/${asteroids.length}: ${Math.round(d/1000)} км`);
        const body = { grid_id: selectedGrid.grid_id, center: a.center, radius: 16.0, fresh: true };
        const res = await fetch('/api/voxel_scan', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.error) { setStatus('ошибка скана: ' + data.error); continue; }
        // wait for tiles
        let tiles = null;
        for (let w = 0; w < 120; w++) {
            const st = await (await fetch(`/api/voxel_status/${data.request_id}`)).json();
            if (st.state === 'complete' || st.state === 'partial') { tiles = true; break; }
            if (st.state === 'rejected' || st.state === 'failed') break;
            await new Promise(r => setTimeout(r, 500));
        }
        // fetch tiles
        const tr = await (await fetch(`/api/voxel_tiles/${data.request_id}`)).json();
        if (!tr.tiles) continue;
        const ores = extractOres(tr.tiles, tr.legend || []);
        found += ores.length;
        renderOres(ores);
        setStatus(`скан ${i+1}/${asteroids.length}: рудных вокселей всего ${found}`);
    }
    setStatus(`готово: рудных вокселей ${found}`);
}

function extractOres(tiles, legend) {
    const oreIds = {};
    for (const entry of legend) {
        const idx = parseInt(entry.split('=')[0]);
        const name = entry.split('=').slice(1).join('=');
        if (isOreName(name)) oreIds[idx] = name;
    }
    const out = [];
    for (const tile of tiles) {
        if (!tile.material) continue;
        const content = Uint8Array.from(atob(tile.content), ch => ch.charCodeAt(0));
        const material = Uint8Array.from(atob(tile.material), ch => ch.charCodeAt(0));
        const nx = tile.size[0], ny = tile.size[1], nz = tile.size[2];
        const origin = tile.origin;
        const ax = tile.axisX, ay = tile.axisY, az = tile.axisZ;
        for (let z = 0; z < nz; z++)
        for (let y = 0; y < ny; y++)
        for (let x = 0; x < nx; x++) {
            const i = x + nx * (y + ny * z);
            if (!content[i] || !oreIds[material[i]]) continue;
            const p = [origin[0] + (x+0.5)*ax[0] + (y+0.5)*ay[0] + (z+0.5)*az[0],
                       origin[1] + (x+0.5)*ax[1] + (y+0.5)*ay[1] + (z+0.5)*az[1],
                       origin[2] + (x+0.5)*ax[2] + (y+0.5)*ay[2] + (z+0.5)*az[2]];
            out.push({ ore: oreIds[material[i]], position: p });
        }
    }
    return out;
}

function renderOres(oreCells) {
    const ORE_MAP = { Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
        Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
        Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
        Chromium: 0xaadccc, Titanium: 0xdca0a0 };
    const byType = {};
    for (const o of oreCells) (byType[o.ore] = byType[o.ore] || []).push(o.position);
    for (const [ore, positions] of Object.entries(byType)) {
        const color = ORE_MAP[ore] || 0xc678dd;
        const geo = new THREE.BoxGeometry(1, 1, 1);
        const mat = new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.4 });
        const inst = new THREE.InstancedMesh(geo, mat, positions.length);
        const dummy = new THREE.Object3D();
        positions.forEach((p, i) => {
            dummy.position.set(p[0] - originShift[0], p[1] - originShift[1], p[2] - originShift[2]);
            dummy.updateMatrix();
            inst.setMatrixAt(i, dummy.matrix);
        });
        inst.instanceMatrix.needsUpdate = true;
        layers.voxels.add(inst);
    }
}

// ── Ore accumulator for multi-asteroid scan ──────────────────────────────────
let originShift = [0, 0, 0];
const ORE_MAP = { Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
    Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
    Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
    Chromium: 0xaadccc, Titanium: 0xdca0a0 };

function renderOres(oreCells) {
    const byType = {};
    for (const o of oreCells) (byType[o.ore] = byType[o.ore] || []).push(o.position);
    for (const [ore, positions] of Object.entries(byType)) {
        const color = ORE_MAP[ore] || 0xc678dd;
        const geo = new THREE.BoxGeometry(1, 1, 1);
        const mat = new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.4 });
        const inst = new THREE.InstancedMesh(geo, mat, positions.length);
        const dummy = new THREE.Object3D();
        positions.forEach((p, i) => {
            dummy.position.set(p[0] - originShift[0], p[1] - originShift[1], p[2] - originShift[2]);
            dummy.updateMatrix();
            inst.setMatrixAt(i, dummy.matrix);
        });
        inst.instanceMatrix.needsUpdate = true;
        layers.voxels.add(inst);
        const centroid = positions.reduce((a, p) => [a[0]+p[0]/positions.length, a[1]+p[1]/positions.length, a[2]+p[2]/positions.length], [0,0,0]);
        addLabel(ore + ' ×' + positions.length, new THREE.Vector3(centroid[0], centroid[1] + 12, centroid[2]), 'ore');
    }
}

// ── Multi-asteroid ore scan: voxel-scan around each indexed asteroid ──────────
document.getElementById('btn-asteroid-scan').addEventListener('click', async () => {
    if (!selectedGrid) { setStatus('выбери грид'); return; }
    const km = parseFloat(document.getElementById('asteroid-radius').value) || 40;
    setStatus('индекс астероидов...');
    const idxRes = await fetch('/api/asteroid_index', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ grid_id: selectedGrid.grid_id, radius: km }),
    });
    const idx = await idxRes.json();
    if (idx.error) { setStatus('ошибка индекса: ' + idx.error); return; }
    // wait for asteroid index
    let asteroids = null;
    const idxDeadline = Date.now() + 120000;
    while (Date.now() < idxDeadline) {
        const st = await (await fetch(`/api/asteroids/${idx.request_id}`)).json();
        if (st.state === 'complete' || st.state === 'partial') { asteroids = st.asteroids || []; break; }
        if (st.error || st.state === 'rejected' || st.state === 'failed') { setStatus('ошибка индекса: ' + (st.error || st.state)); return; }
        await sleep(1.0);
    }
    if (!asteroids) { setStatus('таймаут индекса'); return; }
    // dedup
    const seen = {};
    const unique = asteroids.filter(a => {
        const k = a.center.map(v => Math.round(v)).join(',');
        if (seen[k]) return false;
        seen[k] = true; return true;
    });
    setStatus(`астероидов: ${unique.length} — сканирую каждый (до 15)...`);
    originShift = selectedGrid.position;
    let found = 0;
    for (let i = 0; i < Math.min(15, unique.length); i++) {
        const a = unique[i];
        setStatus(`скан ${i+1}/${Math.min(15, unique.length)}: ${Math.round(distance(a.center, originShift)/1000)} км`);
        const body = { grid_id: selectedGrid.grid_id, center: a.center, radius: 16.0, fresh: true };
        const res = await fetch('/api/voxel_scan', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.error) { continue; }
        let tiles = null;
        const deadline = Date.now() + 120000;
        while (Date.now() < deadline) {
            const tr = await (await fetch(`/api/voxel_tiles/${data.request_id}`)).json();
            if (!tr.error && tr.tiles && tr.tiles.length) { tiles = tr.tiles; break; }
            await sleep(1.0);
        }
        if (!tiles) continue;
        const ores = extractOres(tiles, tr.legend || []);
        found += ores.length;
        renderOres(ores);
        setStatus(`скан ${i+1}: рудных вокселей найдено ${ores.length}, всего ${found}`);
    }
    setStatus(`готово: рудных вокселей ${found}`);
});

function extractOres(tiles, legend) {
    const oreIds = {};
    for (const entry of legend) {
        const idx = parseInt(entry.split('=')[0]);
        const name = entry.split('=').slice(1).join('=');
        if (isOreName(name)) oreIds[idx] = name;
    }
    const out = [];
    for (const tile of tiles) {
        if (!tile.material) continue;
        const content = Uint8Array.from(atob(tile.content), ch => ch.charCodeAt(0));
        const material = Uint8Array.from(atob(tile.material), ch => ch.charCodeAt(0));
        const nx = tile.size[0], ny = tile.size[1], nz = tile.size[2];
        const origin = tile.origin;
        const ax = tile.axisX, ay = tile.axisY, az = tile.axisZ;
        for (let z = 0; z < nz; z++)
        for (let y = 0; y < ny; y++)
        for (let x = 0; x < nx; x++) {
            const i = x + nx * (y + ny * z);
            if (!content[i] || !oreIds[material[i]]) continue;
            const p = [origin[0] + (x+0.5)*ax[0] + (y+0.5)*ay[0] + (z+0.5)*az[0],
                       origin[1] + (x+0.5)*ax[1] + (y+0.5)*ay[1] + (z+0.5)*az[1],
                       origin[2] + (x+0.5)*ax[2] + (y+0.5)*ay[2] + (z+0.5)*az[2]];
            out.push({ ore: oreIds[material[i]], position: p });
        }
    }
    return out;
}

function renderOreMarkers(oreCells) {
    const ORE_MAP = { Iron: 0xb4643c, Nickel: 0x78aa50, Cobalt: 0x3c8cc8, Magnesium: 0xdcdcdc,
        Silicon: 0xc8be8c, Silver: 0xbebed2, Gold: 0xffd700, Platinum: 0xb4dcf0,
        Uranium: 0x50dc50, Ice: 0x8cc8ff, Copper: 0xc87840, Lead: 0x8c8c9c,
        Chromium: 0xaadccc, Titanium: 0xdca0a0 };
    const byType = {};
    for (const o of oreCells) (byType[o.ore] = byType[o.ore] || []).push(o.position);
    for (const [ore, positions] of Object.entries(byType)) {
        const color = ORE_MAP[ore] || 0xc678dd;
        const geo = new THREE.BoxGeometry(1, 1, 1);
        const mat = new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.4 });
        const inst = new THREE.InstancedMesh(geo, mat, positions.length);
        const dummy = new THREE.Object3D();
        positions.forEach((p, i) => {
            dummy.position.set(p[0] - originShift[0], p[1] - originShift[1], p[2] - originShift[2]);
            dummy.updateMatrix();
            inst.setMatrixAt(i, dummy.matrix);
        });
        inst.instanceMatrix.needsUpdate = true;
        layers.voxels.add(inst);
    }
}
