import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── DOM ──
const gridList = document.getElementById('grid-list');
const gridTitle = document.getElementById('grid-title');
const statusEl = document.getElementById('status');
const sidebar = document.getElementById('sidebar');
const divider = document.getElementById('divider');
const viewport = document.getElementById('viewport');
const rightPanel = document.getElementById('right-panel');
const panelTitle = document.getElementById('panel-title');
const panelClose = document.getElementById('panel-close');
const panelGridInfo = document.getElementById('panel-grid-info');
const panelActions = document.getElementById('panel-actions');
const panelHealth = document.getElementById('panel-health');
const panelDevices = document.getElementById('panel-devices');
const deviceCountEl = document.getElementById('device-count');
const fleetStats = document.getElementById('fleet-stats');
const gridSearch = document.getElementById('grid-search');
const btnFleetView = document.getElementById('btn-fleet-view');

// ── State ──
let ws = null;
let gridData = null;
let fleetData = null;
let labels = [];
let selectedGridId = null;
let selectedDeviceId = null;
let allMeshes = [];
let fleetMeshes = [];

// ── Three.js ──
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);
scene.fog = new THREE.FogExp2(0x0a0e14, 0.00015);

const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1e9);
camera.position.set(50, 40, 50);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
viewport.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.1;
controls.screenSpacePanning = true;

scene.add(new THREE.AmbientLight(0x404060, 1.5));
const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
dirLight.position.set(100, 200, 150);
scene.add(dirLight);

const gridHelper = new THREE.GridHelper(200, 40, 0x1e2a3a, 0x111820);
scene.add(gridHelper);

const objectsGroup = new THREE.Group();
scene.add(objectsGroup);

const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

// ── Device colors ──
const DEVICE_COLORS = {
    battery: 0xf1fa8c, connector: 0xffb86c, projector: 0xbd93f9,
    weapon: 0xff5555, artillery: 0xff5555, interior_turret: 0xff6e6e,
    container: 0x8be9fd, cargo: 0x8be9fd, cargo_container: 0x8be9fd,
    thruster: 0xff79c6, gyroscope: 0x50fa7b, reactor: 0xf1fa8c,
    solar: 0xf1fa8c, solar_panel: 0xf1fa8c, drill: 0xffb86c,
    grinder: 0xff5555, welder: 0x50fa7b, piston: 0x6272a4,
    rotor: 0x6272a4, hinge: 0x6272a4, merge: 0xbd93f9,
    merge_block: 0xbd93f9, landing_gear: 0x6272a4,
    timer: 0xff79c6, timer_block: 0xff79c6,
    programmable: 0xff79c6, programmable_block: 0xff79c6,
    sensor: 0x8be9fd, camera: 0x8be9fd, antenna: 0x50fa7b,
    beacon: 0x50fa7b, ore_detector: 0xffb86c,
    remote_control: 0xbd93f9, cockpit: 0xbd93f9,
    lcd: 0x6272a4, text_panel: 0x6272a4, lcd_panel: 0x6272a4,
    medical: 0xff5555, medical_room: 0xff5555, survival_kit: 0xff5555,
    door: 0x6272a4, light: 0xf1fa8c, interior_light: 0xf1fa8c,
    searchlight: 0xf1fa8c, turret: 0xff5555,
    suspension: 0x6272a4, wheel: 0x6272a4,
    ai: 0xff79c6, ai_basic: 0xff79c6, ai_flight_autopilot: 0xff79c6,
    ai_behavior: 0xff79c6, ai_defensive: 0xff5555, ai_offensive: 0xff5555,
    build_and_repair: 0x50fa7b, nanobot: 0x50fa7b,
    engine: 0xf1fa8c, wind_turbine: 0x50fa7b, oxygen_farm: 0x50fa7b,
    seat: 0x6272a4, button: 0x6272a4, air_vent: 0x8be9fd,
    assembler: 0x8be9fd, refinery: 0xffb86c, survival: 0xff5555,
    generic: 0x6272a4,
};

function getDeviceColor(type) {
    if (!type) return DEVICE_COLORS.generic;
    const t = type.toLowerCase().replace('myobjectbuilder_', '');
    return DEVICE_COLORS[t] || DEVICE_COLORS.generic;
}

function getHealthColor(pct) {
    if (pct >= 90) return '#50fa7b';
    if (pct >= 50) return '#f1fa8c';
    if (pct >= 25) return '#ffb86c';
    return '#ff5555';
}

// ── Labels ──
function clearLabels() {
    labels.forEach(l => l.el.remove());
    labels = [];
}

function addLabel(text, position, className = '', clickable = false, minCameraDist = 0) {
    const el = document.createElement('div');
    el.className = 'label-3d ' + className;
    el.textContent = text;
    if (clickable) el.style.cursor = 'pointer';
    viewport.appendChild(el);
    labels.push({ el, position: position.clone(), clickable, minCameraDist });
    return el;
}

function updateLabels() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    const halfW = w / 2;
    const halfH = h / 2;
    const camPos = camera.position;

    for (const label of labels) {
        const dist = camPos.distanceTo(label.position);
        if (label.minCameraDist > 0 && dist > label.minCameraDist) {
            label.el.style.display = 'none';
            continue;
        }
        const pos = label.position.clone();
        pos.project(camera);
        if (pos.z > 1) { label.el.style.display = 'none'; continue; }
        label.el.style.display = '';
        label.el.style.left = (pos.x * halfW + halfW) + 'px';
        label.el.style.top = (-pos.y * halfH + halfH) + 'px';
    }
}

// ── Divider drag ──
let dividerDrag = false;
divider.addEventListener('mousedown', e => {
    dividerDrag = true;
    divider.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
});
document.addEventListener('mousemove', e => {
    if (!dividerDrag) return;
    sidebar.style.width = Math.max(150, Math.min(600, e.clientX)) + 'px';
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

// ── Resize ──
function onResize() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}
window.addEventListener('resize', onResize);
onResize();

// ── Gravity ──
let sceneGravityUp = new THREE.Vector3(0, 1, 0);
let sceneForward = new THREE.Vector3(0, 0, -1);
let sceneRight = new THREE.Vector3(1, 0, 0);

function computeGravityUp(data) {
    if (!data || !data.position) return new THREE.Vector3(0, 1, 0);
    const { x, y, z } = data.position;
    const len = Math.sqrt(x * x + y * y + z * z);
    if (len < 1) return new THREE.Vector3(0, 1, 0);
    return new THREE.Vector3(x / len, y / len, z / len);
}

function toLocal(ox, oy, oz) {
    return new THREE.Vector3(
        sceneRight.x * ox + sceneRight.y * oy + sceneRight.z * oz,
        0,
        -(sceneForward.x * ox + sceneForward.y * oy + sceneForward.z * oz),
    );
}

// ── Fleet view ──
async function loadFleet() {
    try {
        const res = await fetch('/api/fleet/status');
        fleetData = await res.json();
        updateFleetStats();
        if (!selectedGridId) buildFleetView();
    } catch (e) {
        statusEl.textContent = `Ошибка: ${e.message}`;
    }
}

function updateFleetStats() {
    if (!fleetData) { fleetStats.innerHTML = ''; return; }
    const f = fleetData;
    fleetStats.innerHTML = `
        <span class="stat">Гридов: <span class="stat-val">${f.total_grids}</span></span>
        <span class="stat">Блоков: <span class="stat-val">${f.total_blocks}</span></span>
        <span class="stat">Устр: <span class="stat-val">${f.total_devices}</span></span>
        <span class="stat ${f.total_damaged_blocks > 0 ? 'stat-warn' : ''}">Повреждено: <span class="${f.total_damaged_blocks > 0 ? 'stat-bad' : 'stat-val'}">${f.total_damaged_blocks}</span></span>
    `;
}

function buildFleetView() {
    objectsGroup.clear();
    clearLabels();
    allMeshes = [];
    fleetMeshes = [];

    if (!fleetData || !fleetData.grids || fleetData.grids.length === 0) {
        addLabel('Нет данных о флоте', new THREE.Vector3(0, 5, 0));
        return;
    }

    const grids = fleetData.grids;
    let maxDist = 1;
    for (const g of grids) {
        if (!g.position) continue;
        const d = Math.sqrt(g.position.x ** 2 + g.position.y ** 2 + g.position.z ** 2);
        maxDist = Math.max(maxDist, d);
    }
    const scale = maxDist > 0 ? 500 / maxDist : 1;

    for (const g of grids) {
        if (!g.position) continue;
        const pos = new THREE.Vector3(
            g.position.x * scale,
            g.position.y * scale,
            g.position.z * scale,
        );

        const health = g.health_percent || 100;
        let color = 0x50fa7b;
        if (health < 90) color = 0xf1fa8c;
        if (health < 50) color = 0xffb86c;
        if (health < 25) color = 0xff5555;

        const geo = new THREE.BoxGeometry(3, 3, 3);
        const mat = new THREE.MeshLambertMaterial({ color, wireframe: false, transparent: true, opacity: 0.8 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.copy(pos);
        mesh.userData = { grid_id: g.grid_id, isFleetMarker: true };
        objectsGroup.add(mesh);
        fleetMeshes.push(mesh);
        allMeshes.push(mesh);

        const typeStr = g.is_static ? 'Station' : 'Ship';
        const dmgStr = g.damaged_block_count > 0 ? ` [${g.damaged_block_count} dmg]` : '';
        const labelEl = addLabel(
            `${g.name} (${typeStr})${dmgStr}`,
            pos.clone().add(new THREE.Vector3(0, 5, 0)),
            'fleet-marker',
            true,
        );
        labelEl.addEventListener('click', () => selectGrid(g.grid_id));

        if (g.position) {
            addLabel(
                `(${(g.position.x / 1000).toFixed(1)}k, ${(g.position.y / 1000).toFixed(1)}k, ${(g.position.z / 1000).toFixed(1)}k)`,
                pos.clone().add(new THREE.Vector3(0, 3.5, 0)),
                'nearby',
            );
        }
    }

    for (let i = 0; i < grids.length; i++) {
        for (let j = i + 1; j < grids.length; j++) {
            const a = grids[i], b = grids[j];
            if (!a.position || !b.position) continue;
            const pa = new THREE.Vector3(a.position.x * scale, a.position.y * scale, a.position.z * scale);
            const pb = new THREE.Vector3(b.position.x * scale, b.position.y * scale, b.position.z * scale);
            const lineGeo = new THREE.BufferGeometry().setFromPoints([pa, pb]);
            objectsGroup.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({
                color: 0x1e2a3a, transparent: true, opacity: 0.2,
            })));
        }
    }

    const dist = Math.max(maxDist * scale * 1.5, 50);
    controls.target.set(0, 0, 0);
    camera.position.set(0, dist * 0.8, dist * 0.6);
    camera.up.set(0, 1, 0);
    camera.lookAt(0, 0, 0);
    controls.update();
}

// ── Grid view ──
let lastFocusedGridId = null;
let sceneScale = 1;

function buildScene(data, focusCamera = false) {
    objectsGroup.clear();
    clearLabels();
    allMeshes = [];
    fleetMeshes = [];

    if (!data) {
        addLabel('Выберите грид из списка слева', new THREE.Vector3(0, 5, 0));
        return;
    }

    const blocks = data.blocks || [];
    const nearby = data.nearby || [];
    const subgrids = data.subgrids || [];

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

    let maxExt = 1;
    for (const b of blocks) {
        if (!b.position) continue;
        maxExt = Math.max(maxExt, Math.abs(b.position.x), Math.abs(b.position.y), Math.abs(b.position.z));
    }
    const scale = maxExt > 0 ? 100 / maxExt : 1;
    sceneScale = scale;

    const blockGeo = new THREE.BoxGeometry(1, 1, 1);
    for (const block of blocks) {
        if (!block.position) continue;
        const isDevice = block.isDevice;
        const isDamaged = block.state && (
            block.state.damaged ||
            (typeof block.state.integrity === 'number' && typeof block.state.maxIntegrity === 'number' && block.state.integrity < block.state.maxIntegrity)
        );

        let color;
        if (isDamaged) {
            color = 0xff5555;
        } else if (isDevice) {
            color = getDeviceColor(block.type);
        } else {
            color = 0x1a2332;
        }

        const mat = new THREE.MeshLambertMaterial({
            color,
            transparent: !isDevice || isDamaged,
            opacity: isDamaged ? 0.9 : (isDevice ? 1.0 : 0.6),
        });

        const mesh = new THREE.Mesh(blockGeo, mat);
        mesh.position.set(
            block.position.x,
            block.position.y,
            block.position.z,
        );
        mesh.scale.set(1.5, 1.5, 1.5);
        mesh.userData = { block_id: block.id, isDevice, isDamaged, block };
        objectsGroup.add(mesh);
        allMeshes.push(mesh);

        if (isDamaged && !isDevice) {
            const edgeMat = new THREE.LineBasicMaterial({ color: 0xff5555, transparent: true, opacity: 0.6 });
            const edgeGeo = new THREE.EdgesGeometry(blockGeo);
            const edge = new THREE.LineSegments(edgeGeo, edgeMat);
            edge.position.copy(mesh.position);
            edge.scale.set(1.5, 1.5, 1.5);
            objectsGroup.add(edge);
        }

        if (isDevice) {
            const label = block.name || block.subtype || block.type || '';
            if (label) {
                const lbl = addLabel(label, mesh.position.clone().add(new THREE.Vector3(0, 3, 0)), '', false, 40);
                if (isDamaged) lbl.style.color = '#ff5555';
            }
        }
    }

    const centerGeo = new THREE.BoxGeometry(3, 3, 3);
    const centerMat = new THREE.MeshLambertMaterial({
        color: data.is_static ? 0x50fa7b : 0x8be9fd, wireframe: true,
    });
    objectsGroup.add(new THREE.Mesh(centerGeo, centerMat));
    addLabel(`${data.name || 'Grid'} [${data.is_static ? 'Station' : 'Ship'}]`, new THREE.Vector3(0, 5, 0));

    const mainPos = data.position || { x: 0, y: 0, z: 0 };
    const orient = data.orientation || {};
    const oFwd = orient.forward || [0, 0, -1];
    const oUp = orient.up || [0, 1, 0];
    const oLeft = orient.left || [
        oUp[1] * oFwd[2] - oUp[2] * oFwd[1],
        oUp[2] * oFwd[0] - oUp[0] * oFwd[2],
        oUp[0] * oFwd[1] - oUp[1] * oFwd[0],
    ];

    function orientLocal(wx, wy, wz) {
        const dx = wx - mainPos.x;
        const dy = wy - mainPos.y;
        const dz = wz - mainPos.z;
        return new THREE.Vector3(
            -(dx * oLeft[0] + dy * oLeft[1] + dz * oLeft[2]),
            dx * oUp[0] + dy * oUp[1] + dz * oUp[2],
            -(dx * oFwd[0] + dy * oFwd[1] + dz * oFwd[2]),
        );
    }

    for (const ng of nearby) {
        if (!ng.position) continue;
        const local = orientLocal(ng.position.x, ng.position.y, ng.position.z);
        if (local.length() < 0.5) continue;

        const ngGeo = new THREE.BoxGeometry(4, 4, 4);
        const ngMat = new THREE.MeshLambertMaterial({ color: 0x3a4a5a, wireframe: true, transparent: true, opacity: 0.5 });
        const ngMesh = new THREE.Mesh(ngGeo, ngMat);
        ngMesh.position.copy(local);
        objectsGroup.add(ngMesh);

        const lineGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), local]);
        objectsGroup.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0x1e2a3a, transparent: true, opacity: 0.3 })));

        const distLabel = ng.distance != null ? ` (${(ng.distance / 1000).toFixed(1)}km)` : '';
        addLabel(`${ng.name || 'Grid'}${distLabel}`, local.clone().add(new THREE.Vector3(0, 5, 0)), 'nearby');
    }

    for (const sg of subgrids) {
        if (!sg.position) continue;
        const local = orientLocal(sg.position.x, sg.position.y, sg.position.z);
        if (local.length() < 0.5) continue;

        const sgGeo = new THREE.BoxGeometry(3, 3, 3);
        const sgMat = new THREE.MeshLambertMaterial({ color: 0xbd93f9, wireframe: true, transparent: true, opacity: 0.6 });
        const sgMesh = new THREE.Mesh(sgGeo, sgMat);
        sgMesh.position.copy(local);
        objectsGroup.add(sgMesh);
        addLabel(sg.name || `Sub_${sg.grid_id}`, local.clone().add(new THREE.Vector3(0, 4, 0)), 'subgrid');
    }

    const nearbyDevices = data.nearby_devices || [];
    for (const nd of nearbyDevices) {
        if (!nd.position || !nd.blocks || !nd.blocks.length) continue;
        const ndOrient = nd.orientation || {};
        const ndFwd = ndOrient.forward || [0, 0, -1];
        const ndUp = ndOrient.up || [0, 1, 0];
        const ndLeft = ndOrient.left || [
            ndUp[1] * ndFwd[2] - ndUp[2] * ndFwd[1],
            ndUp[2] * ndFwd[0] - ndUp[0] * ndFwd[2],
            ndUp[0] * ndFwd[1] - ndUp[1] * ndFwd[0],
        ];
        const ndCenter = orientLocal(nd.position.x, nd.position.y, nd.position.z);

        const ndBlockGeo = new THREE.BoxGeometry(1, 1, 1);
        for (const b of nd.blocks) {
            if (!b.position) continue;
            const bx = b.position.x;
            const by = b.position.y;
            const bz = b.position.z;
            const wx = nd.position.x + bx * ndLeft[0] + by * ndUp[0] + bz * ndFwd[0];
            const wy = nd.position.y + bx * ndLeft[1] + by * ndUp[1] + bz * ndFwd[1];
            const wz = nd.position.z + bx * ndLeft[2] + by * ndUp[2] + bz * ndFwd[2];
            const local = orientLocal(wx, wy, wz);
            const color = getDeviceColor(b.type);
            const mat = new THREE.MeshLambertMaterial({ color, transparent: true, opacity: 0.7 });
            const mesh = new THREE.Mesh(ndBlockGeo, mat);
            mesh.position.copy(local);
            mesh.scale.set(1.5, 1.5, 1.5);
            objectsGroup.add(mesh);
        }

        addLabel(nd.name || 'Nearby', ndCenter.clone().add(new THREE.Vector3(0, 6, 0)), 'nearby');
    }

    if (focusCamera || isNewGrid) {
        let maxBlockDist = 1;
        for (const b of blocks) {
            if (!b.position) continue;
            maxBlockDist = Math.max(maxBlockDist, Math.sqrt(b.position.x ** 2 + b.position.y ** 2 + b.position.z ** 2));
        }
        const d = Math.max(maxBlockDist * 2.5, 40);
        controls.target.set(0, 0, 0);
        camera.position.set(0, d, d * 0.01);
        camera.up.set(0, 1, 0);
        camera.lookAt(0, 0, 0);
        controls.update();
        if (data) lastFocusedGridId = data.grid_id;
    }
}

// ── Right panel ──
function showRightPanel() { rightPanel.classList.remove('hidden'); }
function hideRightPanel() { rightPanel.classList.add('hidden'); }

panelClose.addEventListener('click', () => {
    hideRightPanel();
    deselectDevice();
});

function renderGridPanel(data) {
    if (!data) return;
    showRightPanel();
    panelTitle.textContent = data.name || data.grid_id;

    const typeStr = data.is_static ? 'Станция' : 'Корабль';
    const posStr = data.position
        ? `${data.position.x.toFixed(0)}, ${data.position.y.toFixed(0)}, ${data.position.z.toFixed(0)}`
        : '—';
    const speedFromOrient = data.orientation && data.orientation.speed != null ? data.orientation.speed : data.speed;
    const speedStr = speedFromOrient != null ? `${speedFromOrient.toFixed(1)} м/с` : (data.is_static ? '—' : '0 м/с');

    panelGridInfo.innerHTML = `
        <div class="grid-info-row"><span class="label">Тип</span><span class="value">${typeStr}</span></div>
        <div class="grid-info-row"><span class="label">ID</span><span class="value" style="font-size:10px;color:#5a6a7a">${data.grid_id}</span></div>
        <div class="grid-info-row"><span class="label">Позиция</span><span class="value" style="font-size:10px">${posStr}</span></div>
        <div class="grid-info-row"><span class="label">Скорость</span><span class="value" style="color:${(!data.is_static && speedFromOrient > 0.5) ? '#f1fa8c' : '#c0c8d0'}">${speedStr}</span></div>
        <div class="grid-info-row"><span class="label">Блоки</span><span class="value">${data.block_count || 0}</span></div>
        <div class="grid-info-row"><span class="label">Устройства</span><span class="value">${data.device_count || 0}</span></div>
    `;

    const health = data.health_percent != null ? data.health_percent : 100;
    const damaged = data.damaged_block_count || 0;
    panelHealth.innerHTML = `
        <div class="health-text">
            <span>Целостность</span>
            <span style="color:${getHealthColor(health)}">${health}% (${damaged} повреждено)</span>
        </div>
        <div class="health-bar-container">
            <div class="health-bar-fill" style="width:${health}%;background:${getHealthColor(health)}"></div>
        </div>
    `;

    const enableState = data.is_static !== undefined ? (data.is_static ? 'Станция' : 'Корабль') : '—';
    panelActions.innerHTML = `
        <button class="action-btn" onclick="window._gridCommand('rename')">Rename</button>
        <button class="action-btn" onclick="window._gridCommand('power_on')">Power On</button>
        <button class="action-btn" onclick="window._gridCommand('power_off')">Power Off</button>
        <button class="action-btn" onclick="window._gridCommand('convert')">${data.is_static ? 'To Ship' : 'To Station'}</button>
        <button class="action-btn" style="border-color:#8be9fd;color:#8be9fd" onclick="window._openContainers('${data.grid_id}')">&#128230; Контейнеры</button>
        <button class="action-btn" style="border-color:#bd93f9;color:#bd93f9" onclick="window._openVoxelScan('${data.grid_id}')">&#128225; Voxels</button>
        <button class="action-btn" style="border-color:#ffb86c;color:#ffb86c" onclick="window._openOreWindow('${data.grid_id}')">&#9937; Руды</button>
    `;

    renderDeviceList(data.device_details || data.devices || []);
}

function renderDeviceList(devices) {
    if (!devices || devices.length === 0) {
        panelDevices.innerHTML = '<div style="font-size:12px;color:#3a4a5a;padding:8px 0">Нет устройств</div>';
        deviceCountEl.textContent = '0';
        return;
    }

    deviceCountEl.textContent = devices.length;

    const groups = {};
    for (const d of devices) {
        const t = d.type || 'unknown';
        if (!groups[t]) groups[t] = [];
        groups[t].push(d);
    }

    let html = '';
    for (const [type, devs] of Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]))) {
        html += `<div class="device-group open" data-type="${type}">`;
        html += `<div class="device-group-header">${type} (${devs.length})</div>`;
        html += '<div class="device-group-body">';
        for (const d of devs) {
            const dotClass = d.is_damaged ? 'damaged' : (d.enabled ? 'ok' : 'disabled');
            const itemClass = `device-item${d.is_damaged ? ' damaged' : ''}${selectedDeviceId === d.device_id ? ' selected' : ''}`;
            const displayName = d.display_name || d.name || d.subtype || d.type || d.device_id;
            html += `<div class="${itemClass}" data-device-id="${d.device_id}" data-grid-id="${d.grid_id || (gridData && gridData.grid_id)}" data-device-type="${d.raw_type || d.type}">
                <div class="device-dot ${dotClass}"></div>
                <span class="device-name">${displayName}</span>
            </div>`;
        }
        html += '</div></div>';
    }

    panelDevices.innerHTML = html;

    panelDevices.querySelectorAll('.device-group-header').forEach(el => {
        el.addEventListener('click', () => {
            el.parentElement.classList.toggle('open');
        });
    });

    panelDevices.querySelectorAll('.device-item').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            const deviceId = el.dataset.deviceId;
            const gridId = el.dataset.gridId;
            const deviceType = el.dataset.deviceType;
            selectDevice(deviceId, gridId, deviceType, devices);
        });
    });
}

// ── Camera animation ──
let cameraAnimating = false;
let cameraAnimStart = 0;
let cameraAnimDuration = 600;
let cameraAnimFrom = new THREE.Vector3();
let cameraAnimTo = new THREE.Vector3();
let cameraAnimTargetFrom = new THREE.Vector3();
let cameraAnimTargetTo = new THREE.Vector3();

function animateCamera(newPos, newTarget) {
    cameraAnimFrom.copy(camera.position);
    cameraAnimTo.copy(newPos);
    cameraAnimTargetFrom.copy(controls.target);
    cameraAnimTargetTo.copy(newTarget);
    cameraAnimStart = performance.now();
    cameraAnimating = true;
}

function updateCameraAnimation() {
    if (!cameraAnimating) return;
    const elapsed = performance.now() - cameraAnimStart;
    let t = Math.min(elapsed / cameraAnimDuration, 1);
    t = t * t * (3 - 2 * t); // smoothstep
    camera.position.lerpVectors(cameraAnimFrom, cameraAnimTo, t);
    controls.target.lerpVectors(cameraAnimTargetFrom, cameraAnimTargetTo, t);
    controls.update();
    if (t >= 1) cameraAnimating = false;
}

// ── Device modal ──
const deviceModal = document.getElementById('device-modal');
const modalBackdrop = deviceModal.querySelector('.modal-backdrop');
const modalClose = document.getElementById('modal-close');
const modalDeviceName = document.getElementById('modal-device-name');
const modalDeviceType = document.getElementById('modal-device-type');
const modalDeviceIcon = document.getElementById('modal-device-icon');
const modalBody = document.getElementById('modal-body');

let currentDeviceForModal = null;

function closeDeviceModal() {
    deviceModal.classList.add('hidden');
    selectedDeviceId = null;
    currentDeviceForModal = null;
    panelDevices.querySelectorAll('.device-item.selected').forEach(el => el.classList.remove('selected'));
}

modalClose.addEventListener('click', closeDeviceModal);
modalBackdrop.addEventListener('click', closeDeviceModal);

function formatTelemetryValue(key, v) {
    if (v == null) return { text: '—', cls: '' };
    if (typeof v === 'boolean') return { text: v ? 'Yes' : 'No', cls: v ? 'green' : 'red' };
    if (typeof v === 'number') {
        const text = (v % 1 === 0) ? String(v) : v.toFixed(2);
        const lower = key.toLowerCase();
        if (lower.includes('ratio') || lower.includes('level') || lower.includes('percent') || lower.includes('charge') || lower.includes('fill')) {
            const pct = v <= 1 ? v * 100 : v;
            const cls = pct >= 75 ? 'green' : (pct >= 25 ? 'yellow' : 'red');
            return { text: text + (v <= 1 ? '' : '%'), cls };
        }
        return { text, cls: '' };
    }
    if (typeof v === 'object') return { text: JSON.stringify(v), cls: 'cyan' };
    return { text: String(v), cls: '' };
}

function formatStateValue(key, v) {
    if (v == null) return { text: '—', cls: '' };
    if (typeof v === 'boolean') return { text: v ? 'Yes' : 'No', cls: v ? 'green' : 'red' };
    if (typeof v === 'number') return { text: (v % 1 === 0) ? String(v) : v.toFixed(2), cls: '' };
    return { text: String(v), cls: '' };
}

function selectDevice(deviceId, gridId, deviceType, allDevices) {
    const device = allDevices.find(d => d.device_id === deviceId);
    if (!device) return;

    selectedDeviceId = deviceId;
    currentDeviceForModal = device;

    panelDevices.querySelectorAll('.device-item').forEach(el => {
        el.classList.toggle('selected', el.dataset.deviceId === deviceId);
    });

    if (device.position) {
        const target = new THREE.Vector3(
            device.position.x * sceneScale,
            device.position.y * sceneScale,
            device.position.z * sceneScale,
        );
        const dist = Math.max(camera.position.distanceTo(controls.target) * 0.3, 8);
        const offset = new THREE.Vector3(dist * 0.5, dist * 0.6, dist * 0.5);
        const newCamPos = target.clone().add(offset);
        animateCamera(newCamPos, target);
    }

    const displayName = device.display_name || device.name || device.subtype || device.type || device.device_id;
    const state = device.state || {};
    const pos = device.position;
    const posStr = pos ? `${pos.x.toFixed(1)}, ${pos.y.toFixed(1)}, ${pos.z.toFixed(1)}` : '—';

    const statusColor = device.is_damaged ? '#ff5555' : (device.enabled ? '#50fa7b' : '#6272a4');
    const statusText = device.is_damaged ? 'Повреждено' : (device.enabled ? 'Работает' : 'Выключено');

    const typeColors = {
        battery: '#f1fa8c', connector: '#ffb86c', projector: '#bd93f9',
        weapon: '#ff5555', thruster: '#ff79c6', gyroscope: '#50fa7b',
        cargo: '#8be9fd', cockpit: '#bd93f9', remote_control: '#bd93f9',
        drill: '#ffb86c', welder: '#50fa7b', grinder: '#ff5555',
        reactor: '#f1fa8c', solar: '#f1fa8c', assembler: '#8be9fd',
        refinery: '#ffb86c', door: '#6272a4', light: '#f1fa8c',
    };
    const iconColor = typeColors[device.type] || '#6272a4';

    modalDeviceName.textContent = displayName;
    modalDeviceType.textContent = `${device.type}${device.subtype ? ' — ' + device.subtype : ''} · ID: ${device.device_id}`;
    modalDeviceIcon.style.background = `${iconColor}22`;
    modalDeviceIcon.style.color = iconColor;
    modalDeviceIcon.style.border = `1px solid ${iconColor}44`;

    const iconLetters = (device.type || '?').substring(0, 2).toUpperCase();
    modalDeviceIcon.textContent = iconLetters;

    let html = '';

    html += `<div class="modal-section">
        <div class="modal-section-title cyan">Основная информация</div>
        <div class="modal-props">
            <div class="modal-prop"><span class="modal-prop-label">Состояние</span><span class="modal-prop-value" style="color:${statusColor}">${statusText}</span></div>
            <div class="modal-prop"><span class="modal-prop-label">Включён</span><span class="modal-prop-value">${device.enabled ? 'Да' : 'Нет'}</span></div>
            <div class="modal-prop"><span class="modal-prop-label">Повреждён</span><span class="modal-prop-value" style="color:${device.is_damaged ? '#ff5555' : '#50fa7b'}">${device.is_damaged ? 'Да' : 'Нет'}</span></div>
            <div class="modal-prop"><span class="modal-prop-label">Позиция</span><span class="modal-prop-value position-badge">${posStr}</span></div>
        </div>
    </div>`;

    const integrity = state.integrity;
    const maxIntegrity = state.maxIntegrity;
    if (typeof integrity === 'number' || typeof maxIntegrity === 'number') {
        const pct = (typeof integrity === 'number' && typeof maxIntegrity === 'number' && maxIntegrity > 0)
            ? Math.round(integrity / maxIntegrity * 100) : null;
        const hColor = pct !== null ? (pct >= 90 ? '#50fa7b' : (pct >= 50 ? '#f1fa8c' : '#ff5555')) : '#6272a4';
        html += `<div class="modal-section">
            <div class="modal-section-title ${pct !== null && pct < 50 ? 'red' : 'green'}">Целостность</div>
            <div class="modal-props">
                <div class="modal-prop"><span class="modal-prop-label">Текущая</span><span class="modal-prop-value">${typeof integrity === 'number' ? Math.round(integrity) : '—'}</span></div>
                <div class="modal-prop"><span class="modal-prop-label">Максимум</span><span class="modal-prop-value">${typeof maxIntegrity === 'number' ? Math.round(maxIntegrity) : '—'}</span></div>
            </div>
            ${pct !== null ? `<div style="margin-top:6px"><div class="health-text"><span></span><span style="color:${hColor}">${pct}%</span></div><div class="health-bar-container"><div class="health-bar-fill" style="width:${pct}%;background:${hColor}"></div></div></div>` : ''}
        </div>`;
    }

    const stateKeys = Object.keys(state);
    if (stateKeys.length > 0) {
        html += `<div class="modal-section">
            <div class="modal-section-title purple">Параметры блока</div>
            <div class="modal-props">`;
        for (const k of stateKeys) {
            const fv = formatStateValue(k, state[k]);
            html += `<div class="modal-prop"><span class="modal-prop-label">${k}</span><span class="modal-prop-value${fv.cls ? ' ' + fv.cls : ''}">${fv.text}</span></div>`;
        }
        html += '</div></div>';
    }

    if (device.telemetry && typeof device.telemetry === 'object') {
        const entries = Object.entries(device.telemetry).filter(([k]) => !k.startsWith('_'));
        if (entries.length > 0) {
            html += `<div class="modal-section">
                <div class="modal-section-title green">Телеметрия (Redis)</div>
                <div class="modal-telemetry-grid">`;
            for (const [k, v] of entries) {
                const fv = formatTelemetryValue(k, v);
                const isFull = typeof v === 'object' || (typeof v === 'string' && v.length > 30);
                html += `<div class="modal-telemetry-item${isFull ? ' full' : ''}">
                    <span class="modal-telemetry-label">${k}</span>
                    <span class="modal-telemetry-value${fv.cls ? ' ' + fv.cls : ''}">${fv.text}</span>
                </div>`;
            }
            html += '</div>';

            html += `<div style="margin-top:8px">
                <button class="modal-raw-toggle" onclick="this.nextElementSibling.classList.toggle('open')">&#9654; Raw JSON</button>
                <div class="modal-raw-json">${JSON.stringify(device.telemetry, null, 2)}</div>
            </div>`;
            html += '</div>';
        } else {
            html += `<div class="modal-section">
                <div class="modal-section-title green">Телеметрия (Redis)</div>
                <div style="font-size:12px;color:#3a4a5a;padding:4px 0">Нет данных телеметрии</div>
            </div>`;
        }
    } else {
        html += `<div class="modal-section">
            <div class="modal-section-title green">Телеметрия (Redis)</div>
            <div style="font-size:12px;color:#3a4a5a;padding:4px 0">Нет данных телеметрии</div>
        </div>`;
    }

    html += `<div class="modal-section">
        <div class="modal-section-title yellow">Управление</div>
        <div class="modal-actions">
            <button class="action-btn" onclick="window._deviceCommand('${device.device_id}', 'toggle')">Toggle</button>
            <button class="action-btn" onclick="window._deviceCommand('${device.device_id}', 'enable')">Enable</button>
            <button class="action-btn danger" onclick="window._deviceCommand('${device.device_id}', 'disable')">Disable</button>
            <button class="action-btn" onclick="window._refreshDeviceTelemetry('${device.device_id}', '${device.grid_id || (gridData && gridData.grid_id)}', '${device.raw_type || device.type}')">Refresh</button>
        </div>
    </div>`;

    modalBody.innerHTML = html;
    deviceModal.classList.remove('hidden');
}

function deselectDevice() {
    closeDeviceModal();
}

window._deselectDevice = closeDeviceModal;

window._refreshDeviceTelemetry = async function(deviceId, gridId, deviceType) {
    try {
        const res = await fetch(`/api/device/${deviceId}/telemetry?grid_id=${gridId}&device_type=${deviceType}`);
        const data = await res.json();
        if (data.telemetry && currentDeviceForModal && currentDeviceForModal.device_id === deviceId) {
            currentDeviceForModal.telemetry = data.telemetry;
            selectDevice(deviceId, gridId, deviceType,
                gridData ? (gridData.device_details || gridData.devices || []) : [currentDeviceForModal]);
        }
    } catch (e) {
        console.error('Refresh telemetry error:', e);
    }
};

// ── Commands ──
window._gridCommand = async function(action) {
    if (!gridData) return;
    const gridId = gridData.grid_id;
    let command = {};
    if (action === 'rename') {
        const newName = prompt('Новое имя:', gridData.name);
        if (!newName) return;
        command = { cmd: 'rename', name: newName };
    } else if (action === 'power_on') {
        command = { cmd: 'power_on' };
    } else if (action === 'power_off') {
        command = { cmd: 'power_off' };
    } else if (action === 'convert') {
        command = { cmd: gridData.is_static ? 'convert_to_ship' : 'convert_to_station' };
    }
    try {
        await fetch(`/api/grid/${gridId}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command }),
        });
    } catch (e) {
        console.error('Command error:', e);
    }
};

window._deviceCommand = async function(deviceId, action) {
    let command = {};
    if (action === 'enable') command = { cmd: 'enable' };
    else if (action === 'disable') command = { cmd: 'disable' };
    else if (action === 'toggle') command = { cmd: 'toggle' };
    try {
        await fetch(`/api/device/${deviceId}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command }),
        });
    } catch (e) {
        console.error('Device command error:', e);
    }
};

// ── WebSocket ──
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { statusEl.textContent = 'Подключено'; };
    ws.onclose = () => {
        statusEl.textContent = 'Отключено. Переподключение...';
        setTimeout(connectWS, 2000);
    };
    let lastGridPosition = null;

    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'update' && msg.data) {
                gridData = msg.data;
                gridTitle.textContent = `${gridData.name} (${gridData.grid_id})`;
                buildScene(gridData, false);
                renderGridPanel(gridData);
                renderVoxels();

                if (gridData.position && lastGridPosition) {
                    const dx = gridData.position.x - lastGridPosition.x;
                    const dy = gridData.position.y - lastGridPosition.y;
                    const dz = gridData.position.z - lastGridPosition.z;
                    const moved = Math.sqrt(dx*dx + dy*dy + dz*dz);
                    if (moved > 0.5) {
                        const camOffset = camera.position.clone().sub(controls.target);
                        controls.target.set(0, 0, 0);
                        camera.position.copy(camOffset);
                        controls.update();
                    }
                }
                if (gridData.position) {
                    lastGridPosition = { ...gridData.position };
                }
            }
        } catch (err) {
            console.error('WS parse error:', err);
        }
    };
}

// ── Grid selection ──
function selectGrid(gridId) {
    selectedGridId = gridId;
    document.querySelectorAll('.grid-item').forEach(el => el.classList.remove('active'));
    const item = document.querySelector(`.grid-item[data-id="${gridId}"]`);
    if (item) item.classList.add('active');

    lastFocusedGridId = null;
    btnFleetView.classList.remove('active');

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'select_grid', grid_id: gridId }));
    }
}

// ── Fleet view button ──
btnFleetView.addEventListener('click', () => {
    selectedGridId = null;
    lastFocusedGridId = null;
    document.querySelectorAll('.grid-item').forEach(el => el.classList.remove('active'));
    btnFleetView.classList.add('active');
    hideRightPanel();
    deselectDevice();
    gridTitle.textContent = 'Обзор флота';
    loadFleet();
});

// ── Load grids ──
async function loadGrids() {
    try {
        const res = await fetch('/api/grids');
        const data = await res.json();
        gridList.innerHTML = '';
        if (data.error) {
            statusEl.textContent = `Ошибка: ${data.error}`;
            return;
        }
        const grids = data.grids || [];
        if (grids.length === 0) {
            statusEl.textContent = 'Гриды не найдены';
            return;
        }

        const filter = (gridSearch.value || '').toLowerCase();
        const filtered = filter ? grids.filter(g => (g.name || '').toLowerCase().includes(filter)) : grids;

        for (const g of filtered) {
            const el = document.createElement('div');
            el.className = 'grid-item';
            el.dataset.id = g.grid_id;
            const posStr = g.position
                ? `(${(g.position.x / 1000).toFixed(1)}k, ${(g.position.y / 1000).toFixed(1)}k, ${(g.position.z / 1000).toFixed(1)}k)`
                : 'нет позиции';
            const healthColor = getHealthColor(g.health_percent || 100);
            const healthPct = g.health_percent != null ? g.health_percent : 100;
            const typeStr = g.is_static ? 'Станция' : 'Корабль';
            const dmgStr = g.damaged_block_count > 0 ? ` · ${g.damaged_block_count} dmg` : '';
            const speedStr = (!g.is_static && g.speed != null && g.speed > 0.1) ? ` · ${g.speed.toFixed(0)} м/с` : '';
            el.innerHTML = `
                <div class="name">${g.name} <span class="type-badge ${g.is_static ? 'station' : 'ship'}">${typeStr}</span>${speedStr ? `<span class="speed-badge">${g.speed.toFixed(0)} м/с</span>` : ''}</div>
                <div class="meta">${g.block_count} блоков · ${posStr}${dmgStr}</div>
                <div class="health-bar"><div class="health-fill" style="width:${healthPct}%;background:${healthColor}"></div></div>
            `;
            el.addEventListener('click', () => selectGrid(g.grid_id));
            gridList.appendChild(el);
        }
        statusEl.textContent = `Найдено гридов: ${grids.length}`;
    } catch (e) {
        statusEl.textContent = `Ошибка загрузки: ${e.message}`;
    }
}

gridSearch.addEventListener('input', loadGrids);

// ── Raycasting (click on 3D blocks) ──
viewport.addEventListener('click', (e) => {
    const rect = viewport.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(allMeshes);

    if (intersects.length > 0) {
        const hit = intersects[0].object;
        const ud = hit.userData;

        if (ud.isFleetMarker && ud.grid_id) {
            selectGrid(ud.grid_id);
            return;
        }

        if (ud.block && ud.isDevice && gridData) {
            const block = ud.block;
            const devices = gridData.device_details || gridData.devices || [];
            const device = devices.find(d => String(d.device_id) === String(block.id));
            if (device) {
                selectDevice(device.device_id, device.grid_id || gridData.grid_id, device.raw_type || device.type, devices);
            }
        }
    }
});

// ── Voxel scan ──
const ORE_COLORS = {
    'iron': 0xb4643c, 'nickel': 0x80aa50, 'cobalt': 0x3c8cc8,
    'magnesium': 0xdcdcdc, 'silicon': 0xc8be8c, 'silver': 0xbebed2,
    'gold': 0xffd700, 'platinum': 0xb4dcf0, 'uranium': 0x50dc50,
    'uraninite': 0x50dc50, 'ice': 0x8cc8ff, 'stone': 0x808080,
};
const DEFAULT_ORE_COLOR = 0xc850c8;
const SOLID_COLOR = 0x4a5568;

function getOreColor(name) {
    const lower = (name || '').toLowerCase();
    for (const [key, color] of Object.entries(ORE_COLORS)) {
        if (lower.includes(key)) return color;
    }
    return DEFAULT_ORE_COLOR;
}

const voxelGroup = new THREE.Group();
scene.add(voxelGroup);
const allScannedVoxels = {};

const voxelScanMenu = document.getElementById('voxel-scan-menu');
const voxelScanClose = document.getElementById('voxel-scan-close');
const voxelScanGridName = document.getElementById('voxel-scan-grid-name');
const voxelRadius = document.getElementById('voxel-radius');
const voxelCellSize = document.getElementById('voxel-cellsize');
const voxelOreOnly = document.getElementById('voxel-oreonly');
const voxelScanStart = document.getElementById('voxel-scan-start');
const voxelScanCancel = document.getElementById('voxel-scan-cancel');
const voxelScanProgressSection = document.getElementById('voxel-scan-progress-section');
const voxelScanStatus = document.getElementById('voxel-scan-status');
const voxelScanFill = document.getElementById('voxel-scan-fill');

let voxelScanPolling = null;
let currentVoxelGridId = null;

voxelScanClose.addEventListener('click', () => voxelScanMenu.classList.add('hidden'));
voxelScanMenu.querySelector('.modal-backdrop').addEventListener('click', () => voxelScanMenu.classList.add('hidden'));

window._openVoxelScan = function(gridId) {
    currentVoxelGridId = gridId;
    voxelScanGridName.textContent = gridData ? gridData.name : gridId;
    voxelScanMenu.classList.remove('hidden');
    checkScanStatus(gridId);
};

async function checkScanStatus(gridId) {
    try {
        const res = await fetch(`/api/grid/${gridId}/voxel_status`);
        const data = await res.json();
        if (data.scanning) {
            showScanProgress(data);
            startScanPolling(gridId);
        } else {
            hideScanProgress();
            if (data.has_result) {
                voxelScanStatus.textContent = `Готово: ${data.solid_count || 0} вокселей, ${data.ore_count || 0} руды`;
                voxelScanProgressSection.style.display = '';
                loadVoxels(gridId);
            }
        }
    } catch (e) {}
}

function showScanProgress(data) {
    voxelScanProgressSection.style.display = '';
    voxelScanStatus.textContent = data.status || 'Scanning...';
    voxelScanFill.style.width = (data.progress || 0) + '%';
    voxelScanStart.style.display = 'none';
    voxelScanCancel.style.display = '';
}

function hideScanProgress() {
    voxelScanStart.style.display = '';
    voxelScanCancel.style.display = 'none';
}

function startScanPolling(gridId) {
    stopScanPolling();
    voxelScanPolling = setInterval(async () => {
        try {
            const res = await fetch(`/api/grid/${gridId}/voxel_status`);
            const data = await res.json();
            if (data.scanning) {
                showScanProgress(data);
            } else {
                stopScanPolling();
                hideScanProgress();
                voxelScanProgressSection.style.display = '';
                voxelScanStatus.textContent = data.error ? `Ошибка: ${data.error}` : `Готово: ${data.solid_count || 0} вокселей, ${data.ore_count || 0} руды`;
                if (data.has_result) loadVoxels(gridId);
                setTimeout(() => voxelScanMenu.classList.add('hidden'), 1500);
            }
        } catch (e) {}
    }, 500);
}

function stopScanPolling() {
    if (voxelScanPolling) {
        clearInterval(voxelScanPolling);
        voxelScanPolling = null;
    }
}

voxelScanStart.addEventListener('click', async () => {
    if (!currentVoxelGridId) return;
    const radius = parseFloat(voxelRadius.value) || 500;
    const cellSize = parseFloat(voxelCellSize.value) || 10;
    const oreOnly = voxelOreOnly.checked;
    try {
        const res = await fetch(`/api/grid/${currentVoxelGridId}/voxel_scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ radius, cell_size: cellSize, ore_only: oreOnly }),
        });
        const data = await res.json();
        if (data.error) {
            voxelScanStatus.textContent = `Ошибка: ${data.error}`;
            voxelScanProgressSection.style.display = '';
            return;
        }
        showScanProgress({ progress: 0, status: 'Starting scan...', scanning: true });
        startScanPolling(currentVoxelGridId);
    } catch (e) {
        voxelScanStatus.textContent = `Ошибка: ${e.message}`;
        voxelScanProgressSection.style.display = '';
    }
});

voxelScanCancel.addEventListener('click', async () => {
    if (!currentVoxelGridId) return;
    try {
        await fetch(`/api/grid/${currentVoxelGridId}/voxel_cancel`, { method: 'POST' });
        stopScanPolling();
        hideScanProgress();
        voxelScanStatus.textContent = 'Отменено';
        voxelScanProgressSection.style.display = '';
    } catch (e) {}
});

async function loadVoxels(gridId) {
    try {
        const res = await fetch(`/api/grid/${gridId}/voxels`);
        const data = await res.json();
        if (data.error || !data.solid) return;
        mergeAndRenderVoxels(gridId, data);
    } catch (e) {}
}

function mergeAndRenderVoxels(gridId, data) {
    const solid = data.solid || [];
    const oreCells = data.ore_cells || [];
    const contacts = data.contacts || [];
    const metadata = data.metadata || {};
    const cellSize = metadata.cellSize || 10;
    const origin = metadata.origin || [0, 0, 0];

    const key = gridId;
    if (!allScannedVoxels[key]) {
        allScannedVoxels[key] = { solid: {}, ore: {}, contacts: [], cellSize: cellSize };
    }
    const store = allScannedVoxels[key];
    store.cellSize = cellSize;

    for (const pt of solid) {
        const k = `${Math.round(pt[0])},${Math.round(pt[1])},${Math.round(pt[2])}`;
        store.solid[k] = pt;
    }

    for (const cell of oreCells) {
        const pos = cell.position;
        if (!pos || !Array.isArray(pos) || pos.length < 3) continue;
        const k = `${Math.round(pos[0])},${Math.round(pos[1])},${Math.round(pos[2])}`;
        const oreName = cell.ore || cell.material || cell.type || '?';
        store.ore[k] = { pos, ore: oreName };
    }

    store.contacts = contacts;

    renderVoxels();
}

function renderVoxels() {
    voxelGroup.clear();

    if (!gridData || !gridData.position) return;

    const gridPos = gridData.position;
    const orient = gridData.orientation;

    let fwd, up, left;
    if (orient && orient.forward && orient.up) {
        fwd = orient.forward;
        up = orient.up;
        left = orient.left || [
            up[1] * fwd[2] - up[2] * fwd[1],
            up[2] * fwd[0] - up[0] * fwd[2],
            up[0] * fwd[1] - up[1] * fwd[0],
        ];
    } else {
        fwd = [0, 0, -1];
        up = [0, 1, 0];
        left = [1, 0, 0];
    }

    function worldToLocal(wx, wy, wz) {
        const dx = wx - gridPos.x;
        const dy = wy - gridPos.y;
        const dz = wz - gridPos.z;
        return [
            -(dx * left[0] + dy * left[1] + dz * left[2]),
            dx * up[0] + dy * up[1] + dz * up[2],
            -(dx * fwd[0] + dy * fwd[1] + dz * fwd[2]),
        ];
    }

    const solidPositions = [];
    const oreByColor = {};
    const activeGridId = gridData ? gridData.grid_id : null;
    let voxelSize = 8;

    if (activeGridId && allScannedVoxels[activeGridId]) {
        const store = allScannedVoxels[activeGridId];
        voxelSize = store.cellSize || 8;

        for (const k in store.ore) {
            const v = store.ore[k];
            const color = getOreColor(v.ore);
            const colorKey = '#' + color.toString(16).padStart(6, '0');
            if (!oreByColor[colorKey]) oreByColor[colorKey] = [];
            oreByColor[colorKey].push(v.pos);
        }

        for (const k in store.solid) {
            if (store.ore[k]) continue;
            const pt = store.solid[k];
            solidPositions.push(pt);
        }
    }

    if (solidPositions.length > 0) {
        const geo = new THREE.BoxGeometry(voxelSize, voxelSize, voxelSize);
        const mat = new THREE.MeshLambertMaterial({ color: SOLID_COLOR, transparent: true, opacity: 0.2 });
        const instanced = new THREE.InstancedMesh(geo, mat, solidPositions.length);
        const dummy = new THREE.Object3D();
        for (let i = 0; i < solidPositions.length; i++) {
            const pt = solidPositions[i];
            const [lx, ly, lz] = worldToLocal(pt[0], pt[1], pt[2]);
            dummy.position.set(lx, ly, lz);
            dummy.updateMatrix();
            instanced.setMatrixAt(i, dummy.matrix);
        }
        instanced.instanceMatrix.needsUpdate = true;
        voxelGroup.add(instanced);
    }

    for (const [colorKey, positions] of Object.entries(oreByColor)) {
        const color = parseInt(colorKey.slice(1), 16);
        const geo = new THREE.BoxGeometry(voxelSize, voxelSize, voxelSize);
        const mat = new THREE.MeshLambertMaterial({ color, transparent: true, opacity: 0.85 });
        const instanced = new THREE.InstancedMesh(geo, mat, positions.length);
        const dummy = new THREE.Object3D();
        for (let i = 0; i < positions.length; i++) {
            const pt = positions[i];
            const [lx, ly, lz] = worldToLocal(pt[0], pt[1], pt[2]);
            dummy.position.set(lx, ly, lz);
            dummy.updateMatrix();
            instanced.setMatrixAt(i, dummy.matrix);
        }
        instanced.instanceMatrix.needsUpdate = true;
        voxelGroup.add(instanced);
    }

    if (activeGridId && allScannedVoxels[activeGridId]) {
        const store = allScannedVoxels[activeGridId];
        for (const c of (store.contacts || [])) {
            const pos = c.position;
            if (!pos) continue;
            const wx = Array.isArray(pos) ? pos[0] : (pos.x || 0);
            const wy = Array.isArray(pos) ? pos[1] : (pos.y || 0);
            const wz = Array.isArray(pos) ? pos[2] : (pos.z || 0);
            const isPlayer = c.type === 'player';
            const color = isPlayer ? 0xff5555 : 0x5555ff;
            const size = isPlayer ? 12 : 10;
            const [lx, ly, lz] = worldToLocal(wx, wy, wz);
            const geo = new THREE.SphereGeometry(size, 8, 8);
            const mat = new THREE.MeshLambertMaterial({ color });
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(lx, ly, lz);
            voxelGroup.add(mesh);

            const label = c.playerName || c.name || c.displayName || c.id || (isPlayer ? 'Player' : 'Grid');
            const dist = Math.sqrt(lx * lx + ly * ly + lz * lz);
            const distStr = dist > 0 ? ` (${(dist / 1000).toFixed(1)}km)` : '';
            addLabel(label + distStr, mesh.position.clone().add(new THREE.Vector3(0, size + 4, 0)), isPlayer ? 'nearby' : 'subgrid', false, 200);
        }
    }
}

// ── Containers modal ──
const containersModal = document.getElementById('containers-modal');
const containersBody = document.getElementById('containers-body');
const containersGridName = document.getElementById('containers-grid-name');
const containersCloseBtn = document.getElementById('containers-close');

containersCloseBtn.addEventListener('click', () => containersModal.classList.add('hidden'));
containersModal.querySelector('.modal-backdrop').addEventListener('click', () => containersModal.classList.add('hidden'));

function formatAmount(amount) {
    if (amount == null) return '0';
    if (amount >= 1000000) return (amount / 1000000).toFixed(1) + 'M';
    if (amount >= 1000) return (amount / 1000).toFixed(1) + 'k';
    if (amount === Math.floor(amount)) return String(amount);
    return amount.toFixed(1);
}

function getFillBarColor(pct) {
    if (pct >= 90) return '#ff5555';
    if (pct >= 70) return '#f1fa8c';
    return '#50fa7b';
}

window._openContainers = async function(gridId) {
    if (!gridId) return;
    containersGridName.textContent = gridData ? gridData.name : gridId;
    containersBody.innerHTML = '<div style="font-size:12px;color:#5a6a7a;padding:12px 0">Загрузка...</div>';
    containersModal.classList.remove('hidden');

    try {
        const res = await fetch(`/api/grid/${gridId}/containers`);
        const data = await res.json();
        if (data.error) {
            containersBody.innerHTML = `<div style="font-size:12px;color:#ff5555;padding:12px 0">Ошибка: ${data.error}</div>`;
            return;
        }
        const containers = data.containers || [];
        if (containers.length === 0) {
            containersBody.innerHTML = '<div style="font-size:12px;color:#5a6a7a;padding:12px 0">Контейнеры не найдены</div>';
            return;
        }

        let totalItems = 0;
        let totalMass = 0;
        for (const c of containers) {
            for (const inv of (c.inventories || [])) {
                totalItems += (inv.items || []).length;
                totalMass += inv.current_mass || 0;
            }
        }

        let html = `<div style="font-size:11px;color:#5a6a7a;margin-bottom:10px">Контейнеров: ${containers.length} · Позиций: ${totalItems} · Масса: ${formatAmount(totalMass)} кг</div>`;

        for (const c of containers) {
            const invCount = (c.inventories || []).length;
            let totalFill = 0;
            let totalMaxVol = 0;
            let totalCurVol = 0;
            for (const inv of (c.inventories || [])) {
                totalCurVol += inv.current_volume || 0;
                totalMaxVol += inv.max_volume || 0;
            }
            if (totalMaxVol > 0) totalFill = totalCurVol / totalMaxVol;

            const fillPct = Math.round(totalFill * 100);
            const fillColor = getFillBarColor(fillPct);

            const hasItems = totalCurVol > 0;
            html += `<div class="container-card${hasItems ? ' open' : ''}" data-device="${c.device_id}">
                <div class="container-card-header" onclick="this.parentElement.classList.toggle('open')">
                    <div>
                        <span class="container-card-name">${c.display_name}</span>
                        <span class="container-card-meta"> · ${c.type} · ${invCount} инв.</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px">
                        <span class="container-card-meta">${formatAmount(totalCurVol)} / ${formatAmount(totalMaxVol)} л</span>
                        <span class="container-card-toggle">&#9654;</span>
                    </div>
                </div>
                <div class="container-card-body">`;

            if (totalMaxVol > 0) {
                html += `<div class="container-fill-bar"><div class="fill" style="width:${fillPct}%;background:${fillColor}"></div></div>`;
            }

            for (const inv of (c.inventories || [])) {
                const items = inv.items || [];
                if (items.length === 0) {
                    html += `<div class="inventory-empty">${inv.name}: пусто</div>`;
                    continue;
                }
                html += `<div style="font-size:10px;color:#bd93f9;margin:4px 0 2px">${inv.name}${inv.fill_ratio != null ? ` (${Math.round(inv.fill_ratio * 100)}%)` : ''}</div>`;
                html += '<table class="inventory-table"><thead><tr><th>Предмет</th><th>Тип</th><th style="text-align:right">Кол-во</th></tr></thead><tbody>';
                const sorted = [...items].sort((a, b) => (b.amount || 0) - (a.amount || 0));
                for (const item of sorted) {
                    const label = item.display_name || item.subtype || item.type || '?';
                    const typeShort = item.type ? item.type.replace('MyObjectBuilder_', '').replace('_', ' ') : '';
                    html += `<tr>
                        <td class="item-name">${label}</td>
                        <td class="item-type">${typeShort}</td>
                        <td class="amount" style="text-align:right">${formatAmount(item.amount)}</td>
                    </tr>`;
                }
                html += '</tbody></table>';
            }

            html += '</div></div>';
        }

        containersBody.innerHTML = html;
    } catch (e) {
        containersBody.innerHTML = `<div style="font-size:12px;color:#ff5555;padding:12px 0">Ошибка: ${e.message}</div>`;
    }
};

// ── Ore modal ──
const oreModal = document.getElementById('ore-modal');
const oreGridName = document.getElementById('ore-grid-name');
const oreList = document.getElementById('ore-list');
const oreRadius = document.getElementById('ore-radius');
const oreCellSize = document.getElementById('ore-cellsize');
const oreScanStart = document.getElementById('ore-scan-start');
const oreScanCancel = document.getElementById('ore-scan-cancel');
const oreScanRefresh = document.getElementById('ore-refresh');
const oreScanProgressSection = document.getElementById('ore-scan-progress-section');
const oreScanStatus = document.getElementById('ore-scan-status');
const oreScanFill = document.getElementById('ore-scan-fill');

let oreScanPolling = null;
let currentOreGridId = null;

document.getElementById('ore-close').addEventListener('click', () => oreModal.classList.add('hidden'));
oreModal.querySelector('.modal-backdrop').addEventListener('click', () => oreModal.classList.add('hidden'));

const ORE_UI_COLORS = {
    gold: '#ff8800', silver: '#a0a0a0', platinum: '#00ff88',
    iron: '#ff4444', nickel: '#88aa44', cobalt: '#4444ff',
    magnesium: '#ffffff', silicon: '#888888', uranium: '#44ff44',
    ice: '#88ffff', stone: '#808080',
};

function getOreUIColor(material) {
    return ORE_UI_COLORS[(material || '').toLowerCase()] || '#ffb86c';
}

window._openOreWindow = async function(gridId) {
    currentOreGridId = gridId;
    oreGridName.textContent = gridData ? gridData.name : gridId;
    oreScanProgressSection.style.display = 'none';
    oreScanStart.style.display = '';
    oreScanCancel.style.display = 'none';
    oreModal.classList.remove('hidden');
    stopOreScanPolling();
    await loadOres(gridId);
};

async function loadOres(gridId) {
    oreList.innerHTML = 'Загрузка...';
    try {
        const res = await fetch(`/api/grid/${gridId}/ores`);
        const data = await res.json();
        if (data.error) {
            oreList.innerHTML = `<span style="color:#ff5555">Ошибка: ${data.error}</span>`;
            return;
        }
        const ores = data.ores || [];
        if (ores.length === 0) {
            oreList.innerHTML = '<span style="color:#5a6a7a">Нет известных руд. Запустите сканирование.</span>';
            return;
        }
        let html = `<div style="font-size:10px;color:#5a6a7a;margin-bottom:6px">Найдено: ${ores.length}</div>`;
        for (const dep of ores) {
            const color = getOreUIColor(dep.material);
            const distStr = dep.distance_m >= 0 ? `${(dep.distance_m).toFixed(0)} м` : '—';
            const pos = dep.position;
            const posStr = pos ? `${pos[0].toFixed(0)}, ${pos[1].toFixed(0)}, ${pos[2].toFixed(0)}` : '—';
            const countStr = dep.count ? ` (${dep.count} т.)` : '';
            html += `<div class="ore-item" style="border-left:3px solid ${color};padding:6px 8px;margin-bottom:4px;background:var(--bg-dark);border-radius:3px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-weight:600;color:${color}">${dep.material}${countStr}</span>
                    <span style="color:var(--accent-cyan);font-size:11px;font-family:monospace">${distStr}</span>
                </div>
                <div style="font-size:10px;color:#5a6a7a;font-family:monospace;margin-top:2px">
                    GPS:${dep.material}:${posStr}:${color}:
                </div>
            </div>`;
        }
        oreList.innerHTML = html;
    } catch (e) {
        oreList.innerHTML = `<span style="color:#ff5555">Ошибка: ${e.message}</span>`;
    }
}

function showOreScanProgress(data) {
    oreScanProgressSection.style.display = '';
    oreScanStatus.textContent = data.status || 'Scanning...';
    oreScanFill.style.width = (data.progress || 0) + '%';
    oreScanStart.style.display = 'none';
    oreScanCancel.style.display = '';
}

function hideOreScanProgress() {
    oreScanStart.style.display = '';
    oreScanCancel.style.display = 'none';
}

function stopOreScanPolling() {
    if (oreScanPolling) {
        clearInterval(oreScanPolling);
        oreScanPolling = null;
    }
}

function startOreScanPolling(gridId) {
    stopOreScanPolling();
    oreScanPolling = setInterval(async () => {
        try {
            const res = await fetch(`/api/grid/${gridId}/scan_ores_status`);
            const data = await res.json();
            if (data.scanning) {
                showOreScanProgress(data);
            } else {
                stopOreScanPolling();
                hideOreScanProgress();
                oreScanProgressSection.style.display = '';
                if (data.error) {
                    oreScanStatus.textContent = `Ошибка: ${data.error}`;
                } else {
                    oreScanStatus.textContent = `Готово: ${data.result?.ore_count || 0} руд найдено`;
                }
                await loadOres(gridId);
                setTimeout(() => { oreScanProgressSection.style.display = 'none'; }, 3000);
            }
        } catch (e) {}
    }, 500);
}

oreScanStart.addEventListener('click', async () => {
    if (!currentOreGridId) return;
    const radius = parseFloat(oreRadius.value) || 300;
    const cellSize = parseFloat(oreCellSize.value) || 10;
    try {
        const res = await fetch(`/api/grid/${currentOreGridId}/scan_ores`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ radius, cell_size: cellSize }),
        });
        const data = await res.json();
        if (data.error) {
            oreScanStatus.textContent = `Ошибка: ${data.error}`;
            oreScanProgressSection.style.display = '';
            return;
        }
        showOreScanProgress({ progress: 0, status: 'Starting scan...', scanning: true });
        startOreScanPolling(currentOreGridId);
    } catch (e) {
        oreScanStatus.textContent = `Ошибка: ${e.message}`;
        oreScanProgressSection.style.display = '';
    }
});

oreScanCancel.addEventListener('click', async () => {
    if (!currentOreGridId) return;
    try {
        await fetch(`/api/grid/${currentOreGridId}/cancel_ore_scan`, { method: 'POST' });
        stopOreScanPolling();
        hideOreScanProgress();
        oreScanStatus.textContent = 'Отменено';
        oreScanProgressSection.style.display = '';
    } catch (e) {}
});

oreScanRefresh.addEventListener('click', async () => {
    if (!currentOreGridId) return;
    await loadOres(currentOreGridId);
});

// ── Animate ──
function animate() {
    requestAnimationFrame(animate);
    updateCameraAnimation();
    controls.update();
    renderer.render(scene, camera);
    updateLabels();
}

// ── Periodic nearby grid position check ──
let lastNearbyPositions = {};

async function checkNearbyGridPositions() {
    if (!selectedGridId || !gridData) return;
    try {
        const res = await fetch(`/api/grid/${selectedGridId}`);
        const data = await res.json();
        if (data.error) return;

        const nearby = data.nearby || [];
        let changed = false;
        const newPositions = {};
        for (const ng of nearby) {
            if (!ng.position) continue;
            const key = ng.grid_id;
            const pos = `${ng.position.x},${ng.position.y},${ng.position.z}`;
            newPositions[key] = pos;
            if (lastNearbyPositions[key] !== pos) {
                changed = true;
            }
        }
        if (Object.keys(newPositions).length !== Object.keys(lastNearbyPositions).length) {
            changed = true;
        }
        if (changed) {
            lastNearbyPositions = newPositions;
            gridData.nearby = nearby;
            gridData.nearby_devices = data.nearby_devices || [];
            buildScene(gridData, false);
            renderVoxels();
        }
    } catch (e) {}
}

setInterval(checkNearbyGridPositions, 10000);

loadGrids();
loadFleet();
connectWS();
setInterval(loadGrids, 10000);
setInterval(loadFleet, 15000);
buildFleetView();
animate();
