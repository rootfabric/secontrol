import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const gridList = document.getElementById('grid-list');
const gridTitle = document.getElementById('grid-title');
const status = document.getElementById('status');
const sidebar = document.getElementById('sidebar');
const divider = document.getElementById('divider');
const viewport = document.getElementById('viewport');

let ws = null;
let gridData = null;
let labels = [];

// --- Three.js setup ---
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);

const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1e9);
camera.position.set(50, 40, 50);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
viewport.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.1;
controls.screenSpacePanning = true;

// Lights
scene.add(new THREE.AmbientLight(0x404060, 1.5));
const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
dirLight.position.set(100, 200, 150);
scene.add(dirLight);

// Grid helper
const gridHelper = new THREE.GridHelper(200, 40, 0x1e2a3a, 0x111820);
scene.add(gridHelper);

// --- Device colors ---
const DEVICE_COLORS = {
    battery: 0xf1fa8c, connector: 0xffb86c, projector: 0xbd93f9,
    weapon: 0xff5555, artillery: 0xff5555, interior_turret: 0xff6e6e,
    container: 0x8be9fd, cargo_container: 0x8be9fd,
    thruster: 0xff79c6, gyroscope: 0x50fa7b, reactor: 0xf1fa8c,
    solar_panel: 0xf1fa8c, drill: 0xffb86c, grinder: 0xff5555,
    welder: 0x50fa7b, piston: 0x6272a4, rotor: 0x6272a4,
    hinge: 0x6272a4, merge_block: 0xbd93f9, landing_gear: 0x6272a4,
    timer_block: 0xff79c6, programmable_block: 0xff79c6,
    sensor: 0x8be9fd, camera: 0x8be9fd, antenna: 0x50fa7b,
    beacon: 0x50fa7b, ore_detector: 0xffb86c,
    remote_control: 0xbd93f9, cockpit: 0xbd93f9,
    text_panel: 0x6272a4, lcd_panel: 0x6272a4,
    medical_room: 0xff5555, survival_kit: 0xff5555,
    door: 0x6272a4, interior_light: 0xf1fa8c,
    searchlight: 0xf1fa8c, turret: 0xff5555,
    motor_suspension: 0x6272a4, wheel: 0x6272a4,
    ai_basic: 0xff79c6, ai_flight_autopilot: 0xff79c6,
    ai_behavior: 0xff79c6, ai_defensive: 0xff5555, ai_offensive: 0xff5555,
    generic: 0x6272a4,
};

function getDeviceColor(type) {
    if (!type) return DEVICE_COLORS.generic;
    const t = type.toLowerCase().replace('myobjectbuilder_', '');
    return DEVICE_COLORS[t] || DEVICE_COLORS.generic;
}

// --- Objects group (cleared on each update) ---
let objectsGroup = new THREE.Group();
scene.add(objectsGroup);

// --- Divider drag ---
divider.addEventListener('mousedown', e => {
    dividerDrag = true;
    divider.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
});
let dividerDrag = false;
document.addEventListener('mousemove', e => {
    if (!dividerDrag) return;
    let w = e.clientX;
    w = Math.max(150, Math.min(600, w));
    sidebar.style.width = w + 'px';
    onResize();
});
document.addEventListener('mouseup', () => {
    if (dividerDrag) {
        dividerDrag = false;
        divider.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    }
});

// --- Resize ---
function onResize() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}
window.addEventListener('resize', onResize);
onResize();

// --- Label management ---
function clearLabels() {
    labels.forEach(l => l.el.remove());
    labels = [];
}

function addLabel(text, position, className = '') {
    const el = document.createElement('div');
    el.className = 'label-3d ' + className;
    el.textContent = text;
    viewport.appendChild(el);
    labels.push({ el, position: position.clone() });
}

function updateLabels() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    const halfW = w / 2;
    const halfH = h / 2;

    for (const label of labels) {
        const pos = label.position.clone();
        pos.project(camera);
        if (pos.z > 1) {
            label.el.style.display = 'none';
            continue;
        }
        label.el.style.display = '';
        label.el.style.left = (pos.x * halfW + halfW) + 'px';
        label.el.style.top = (-pos.y * halfH + halfH) + 'px';
    }
}

// --- Scene builder ---
let lastFocusedGridId = null;
let sceneGravityUp = new THREE.Vector3(0, 1, 0);
let sceneForward = new THREE.Vector3(0, 0, -1);
let sceneRight = new THREE.Vector3(1, 0, 0);

// Compute gravity direction from main grid position (planet center ≈ origin)
function computeGravityUp(data) {
    if (!data || !data.position) return new THREE.Vector3(0, 1, 0);
    const { x, y, z } = data.position;
    const len = Math.sqrt(x*x + y*y + z*z);
    if (len < 1) return new THREE.Vector3(0, 1, 0);
    return new THREE.Vector3(x/len, y/len, z/len);
}

function buildScene(data, focusCamera = false) {
    objectsGroup.clear();
    clearLabels();

    if (!data) {
        addLabel('Выберите грид из списка слева', new THREE.Vector3(0, 5, 0));
        return;
    }

    const blocks = data.blocks || [];
    const nearby = data.nearby || [];
    const subgrids = data.subgrids || [];

    // Only recompute gravity direction when grid selection changes
    const isNewGrid = data && data.grid_id !== lastFocusedGridId;
    if (isNewGrid) {
        sceneGravityUp = computeGravityUp(data);
        const up = sceneGravityUp.clone().normalize();
        const worldY = new THREE.Vector3(0, 1, 0);
        if (Math.abs(up.dot(worldY)) > 0.99) {
            sceneForward.set(1, 0, 0);
        } else {
            sceneForward.crossVectors(up, worldY).normalize();
        }
        sceneRight.crossVectors(sceneForward, up).normalize();
    }

    // Helper: project world-space offset onto local horizontal plane
    function toLocal(ox, oy, oz) {
        return new THREE.Vector3(
            sceneRight.x*ox + sceneRight.y*oy + sceneRight.z*oz,
            0,  // height above plane is flattened
            -(sceneForward.x*ox + sceneForward.y*oy + sceneForward.z*oz),
        );
    }

    // Compute scale from block extents
    let maxExt = 1;
    for (const b of blocks) {
        if (!b.position) continue;
        const ax = Math.abs(b.position.x);
        const ay = Math.abs(b.position.y);
        const az = Math.abs(b.position.z);
        maxExt = Math.max(maxExt, ax, ay, az);
    }
    const scale = maxExt > 0 ? 100 / maxExt : 1;

    // Draw blocks (grid-local positions, rendered directly)
    const blockGeo = new THREE.BoxGeometry(1, 1, 1);
    for (const block of blocks) {
        if (!block.position) continue;
        const isDevice = block.isDevice;
        const color = isDevice ? getDeviceColor(block.type) : 0x1a2332;
        const mat = new THREE.MeshLambertMaterial({
            color, transparent: !isDevice, opacity: isDevice ? 1.0 : 0.6,
        });
        const mesh = new THREE.Mesh(blockGeo, mat);
        // Block positions are grid-local (small values), use X/Z for horizontal, Y for vertical in grid frame
        mesh.position.set(
            block.position.x * scale,
            block.position.y * scale,
            block.position.z * scale,
        );
        const s = Math.max(0.8, 1.5 * scale);
        mesh.scale.set(s, s, s);
        objectsGroup.add(mesh);

        if (isDevice) {
            const label = block.name || block.subtype || block.type || '';
            if (label) {
                addLabel(label, mesh.position.clone().add(new THREE.Vector3(0, s * 0.7, 0)));
            }
        }
    }

    // Main grid center marker
    const centerGeo = new THREE.BoxGeometry(3, 3, 3);
    const centerMat = new THREE.MeshLambertMaterial({
        color: data.is_static ? 0x50fa7b : 0x8be9fd, wireframe: true,
    });
    objectsGroup.add(new THREE.Mesh(centerGeo, centerMat));
    addLabel(`${data.name || 'Grid'} [${data.is_static ? 'Station' : 'Ship'}]`, new THREE.Vector3(0, 5, 0));

    // Nearby grids — project onto horizontal plane
    const mainPos = data.position || { x: 0, y: 0, z: 0 };
    for (const ng of nearby) {
        if (!ng.position) continue;
        const ox = ng.position.x - mainPos.x;
        const oy = ng.position.y - mainPos.y;
        const oz = ng.position.z - mainPos.z;
        const local = toLocal(ox, oy, oz);
        const dist = local.length() * scale;
        if (dist < 1) continue;
        local.multiplyScalar(scale);

        const ngGeo = new THREE.BoxGeometry(4, 4, 4);
        const ngMat = new THREE.MeshLambertMaterial({
            color: 0x3a4a5a, wireframe: true, transparent: true, opacity: 0.5,
        });
        const ngMesh = new THREE.Mesh(ngGeo, ngMat);
        ngMesh.position.copy(local);
        objectsGroup.add(ngMesh);

        const lineGeo = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, 0, 0), local,
        ]);
        objectsGroup.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({
            color: 0x1e2a3a, transparent: true, opacity: 0.3,
        })));

        const distLabel = ng.distance != null ? ` (${(ng.distance / 1000).toFixed(1)}km)` : '';
        addLabel(`${ng.name || 'Grid'}${distLabel}`, local.clone().add(new THREE.Vector3(0, 5, 0)), 'nearby');
    }

    // Subgrids — project onto horizontal plane like nearby grids
    for (const sg of subgrids) {
        if (!sg.position) continue;
        const ox = sg.position.x - mainPos.x;
        const oy = sg.position.y - mainPos.y;
        const oz = sg.position.z - mainPos.z;
        const local = toLocal(ox, oy, oz);
        const dist = local.length() * scale;
        if (dist < 1) continue;
        local.multiplyScalar(scale);

        const sgGeo = new THREE.BoxGeometry(3, 3, 3);
        const sgMat = new THREE.MeshLambertMaterial({
            color: 0xbd93f9, wireframe: true, transparent: true, opacity: 0.6,
        });
        const sgMesh = new THREE.Mesh(sgGeo, sgMat);
        sgMesh.position.copy(local);
        objectsGroup.add(sgMesh);
        addLabel(sg.name || `Sub_${sg.grid_id}`, local.clone().add(new THREE.Vector3(0, 4, 0)), 'subgrid');
    }

    // Focus camera: always center on selected grid (origin)
    if (focusCamera || isNewGrid) {
        // Compute grid extent from blocks only (not nearby)
        let maxBlockDist = 1;
        for (const b of blocks) {
            if (!b.position) continue;
            const d = Math.sqrt(b.position.x ** 2 + b.position.y ** 2 + b.position.z ** 2);
            maxBlockDist = Math.max(maxBlockDist, d);
        }
        const dist = Math.max(maxBlockDist * scale * 2.5, 40);
        // Gravity vector in SE is -Y, so top-down: camera above looking down
        controls.target.set(0, 0, 0);
        camera.position.set(0, dist, dist * 0.01);
        camera.up.set(0, 1, 0);
        camera.lookAt(0, 0, 0);
        controls.update();
        if (data) lastFocusedGridId = data.grid_id;
    }
}

// --- Info panel ---
let infoPanel = document.getElementById('info-panel');
if (!infoPanel) {
    infoPanel = document.createElement('div');
    infoPanel.id = 'info-panel';
    viewport.appendChild(infoPanel);
}

function updateInfoPanel() {
    if (!gridData) {
        infoPanel.textContent = '';
        return;
    }
    const d = gridData;
    infoPanel.innerHTML = [
        `Blocks: ${d.block_count || 0}`,
        `Devices: ${d.device_count || 0}`,
        `Type: ${d.is_static ? 'Station' : 'Ship'}`,
        `Nearby: ${(d.nearby || []).length} grids`,
        `Subgrids: ${(d.subgrids || []).length}`,
    ].join('<br>');
}

// --- WebSocket ---
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { status.textContent = 'Подключено'; };
    ws.onclose = () => {
        status.textContent = 'Отключено. Переподключение...';
        setTimeout(connectWS, 2000);
    };
    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'update' && msg.data) {
                gridData = msg.data;
                gridTitle.textContent = `${gridData.name} (${gridData.grid_id})`;
                buildScene(gridData, false);
                updateInfoPanel();
            }
        } catch (err) {
            console.error('WS parse error:', err);
        }
    };
}

// --- Grid selection ---
function selectGrid(gridId) {
    document.querySelectorAll('.grid-item').forEach(el => el.classList.remove('active'));
    const item = document.querySelector(`.grid-item[data-id="${gridId}"]`);
    if (item) item.classList.add('active');

    lastFocusedGridId = null; // force camera refocus on next update

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'select_grid', grid_id: gridId }));
    }
}

// --- Load grids list ---
async function loadGrids() {
    try {
        const res = await fetch('/api/grids');
        const data = await res.json();
        gridList.innerHTML = '';
        if (data.error) {
            status.textContent = `Ошибка: ${data.error}`;
            return;
        }
        const grids = data.grids || [];
        if (grids.length === 0) {
            status.textContent = 'Гриды не найдены';
            return;
        }
        for (const g of grids) {
            const el = document.createElement('div');
            el.className = 'grid-item';
            el.dataset.id = g.grid_id;
            const posStr = g.position
                ? `(${(g.position.x / 1000).toFixed(1)}k, ${(g.position.y / 1000).toFixed(1)}k, ${(g.position.z / 1000).toFixed(1)}k)`
                : 'нет позиции';
            el.innerHTML = `
                <div class="name">${g.name}</div>
                <div class="meta">${g.is_static ? 'Станция' : 'Корабль'} · ${g.block_count} блоков · ${posStr}</div>
            `;
            el.addEventListener('click', () => selectGrid(g.grid_id));
            gridList.appendChild(el);
        }
        status.textContent = `Найдено гридов: ${grids.length}`;
    } catch (e) {
        status.textContent = `Ошибка загрузки: ${e.message}`;
    }
}

// --- Render loop ---
function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
    updateLabels();
}

loadGrids();
connectWS();
setInterval(loadGrids, 10000);
buildScene(null);
animate();
