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
const panelDeviceDetail = document.getElementById('panel-device-detail');
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

function addLabel(text, position, className = '', clickable = false) {
    const el = document.createElement('div');
    el.className = 'label-3d ' + className;
    el.textContent = text;
    if (clickable) el.style.cursor = 'pointer';
    viewport.appendChild(el);
    labels.push({ el, position: position.clone(), clickable });
    return el;
}

function updateLabels() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    const halfW = w / 2;
    const halfH = h / 2;
    for (const label of labels) {
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
            block.position.x * scale,
            block.position.y * scale,
            block.position.z * scale,
        );
        const s = Math.max(0.8, 1.5 * scale);
        mesh.scale.set(s, s, s);
        mesh.userData = { block_id: block.id, isDevice, isDamaged, block };
        objectsGroup.add(mesh);
        allMeshes.push(mesh);

        if (isDamaged && !isDevice) {
            const edgeMat = new THREE.LineBasicMaterial({ color: 0xff5555, transparent: true, opacity: 0.6 });
            const edgeGeo = new THREE.EdgesGeometry(blockGeo);
            const edge = new THREE.LineSegments(edgeGeo, edgeMat);
            edge.position.copy(mesh.position);
            edge.scale.set(s, s, s);
            objectsGroup.add(edge);
        }

        if (isDevice) {
            const label = block.name || block.subtype || block.type || '';
            if (label) {
                const lbl = addLabel(label, mesh.position.clone().add(new THREE.Vector3(0, s * 0.7, 0)));
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
        const ox = sg.position.x - mainPos.x;
        const oy = sg.position.y - mainPos.y;
        const oz = sg.position.z - mainPos.z;
        const local = toLocal(ox, oy, oz);
        const dist = local.length() * scale;
        if (dist < 1) continue;
        local.multiplyScalar(scale);

        const sgGeo = new THREE.BoxGeometry(3, 3, 3);
        const sgMat = new THREE.MeshLambertMaterial({ color: 0xbd93f9, wireframe: true, transparent: true, opacity: 0.6 });
        const sgMesh = new THREE.Mesh(sgGeo, sgMat);
        sgMesh.position.copy(local);
        objectsGroup.add(sgMesh);
        addLabel(sg.name || `Sub_${sg.grid_id}`, local.clone().add(new THREE.Vector3(0, 4, 0)), 'subgrid');
    }

    if (focusCamera || isNewGrid) {
        let maxBlockDist = 1;
        for (const b of blocks) {
            if (!b.position) continue;
            maxBlockDist = Math.max(maxBlockDist, Math.sqrt(b.position.x ** 2 + b.position.y ** 2 + b.position.z ** 2));
        }
        const d = Math.max(maxBlockDist * scale * 2.5, 40);
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

    panelGridInfo.innerHTML = `
        <div class="grid-info-row"><span class="label">Тип</span><span class="value">${typeStr}</span></div>
        <div class="grid-info-row"><span class="label">ID</span><span class="value" style="font-size:10px;color:#5a6a7a">${data.grid_id}</span></div>
        <div class="grid-info-row"><span class="label">Позиция</span><span class="value" style="font-size:10px">${posStr}</span></div>
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
            html += `<div class="${itemClass}" data-device-id="${d.device_id}" data-grid-id="${d.grid_id || (gridData && gridData.grid_id)}" data-device-type="${d.raw_type || d.type}">
                <div class="device-dot ${dotClass}"></div>
                <span class="device-name">${d.name || d.device_id}</span>
                <span class="device-type">${d.type}</span>
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

function selectDevice(deviceId, gridId, deviceType, allDevices) {
    selectedDeviceId = deviceId;
    panelDevices.querySelectorAll('.device-item').forEach(el => {
        el.classList.toggle('selected', el.dataset.deviceId === deviceId);
    });

    const device = allDevices.find(d => d.device_id === deviceId);
    if (!device) {
        panelDeviceDetail.classList.add('hidden');
        return;
    }

    panelDeviceDetail.classList.remove('hidden');

    const state = device.state || {};
    const integrity = state.integrity != null ? Math.round(state.integrity) : '—';
    const maxIntegrity = state.maxIntegrity != null ? Math.round(state.maxIntegrity) : '—';
    const pos = device.position;
    const posStr = pos ? `${pos.x.toFixed(1)}, ${pos.y.toFixed(1)}, ${pos.z.toFixed(1)}` : '—';

    let telemetryHtml = '';
    if (device.telemetry && typeof device.telemetry === 'object') {
        const entries = Object.entries(device.telemetry).filter(([k]) => !k.startsWith('_'));
        if (entries.length > 0) {
            telemetryHtml = '<div class="telemetry-grid">';
            for (const [k, v] of entries.slice(0, 12)) {
                const val = typeof v === 'number' ? (v % 1 === 0 ? v : v.toFixed(2)) : (v != null ? String(v) : '—');
                telemetryHtml += `<div class="telemetry-item"><span class="telemetry-label">${k}</span><span class="telemetry-value">${val}</span></div>`;
            }
            telemetryHtml += '</div>';
        }
    }

    panelDeviceDetail.innerHTML = `
        <div class="device-detail-header">
            <span class="device-detail-name">${device.name || device.device_id}</span>
            <button class="device-detail-close" onclick="window._deselectDevice()">&times;</button>
        </div>
        <div class="grid-info-row"><span class="label">Тип</span><span class="value">${device.type}</span></div>
        <div class="grid-info-row"><span class="label">ID</span><span class="value" style="font-size:10px;color:#5a6a7a">${device.device_id}</span></div>
        <div class="grid-info-row"><span class="label">Состояние</span><span class="value" style="color:${device.is_damaged ? '#ff5555' : (device.enabled ? '#50fa7b' : '#6272a4')}">${device.is_damaged ? 'Повреждено' : (device.enabled ? 'Работает' : 'Выкл')}</span></div>
        <div class="grid-info-row"><span class="label">Целостность</span><span class="value">${integrity} / ${maxIntegrity}</span></div>
        <div class="grid-info-row"><span class="label">Позиция</span><span class="value position-badge">${posStr}</span></div>
        <div style="margin-top:8px;display:flex;gap:6px">
            <button class="action-btn${device.enabled ? '' : ' active'}" onclick="window._deviceCommand('${device.device_id}', 'enable')">${device.enabled ? 'Disable' : 'Enable'}</button>
            <button class="action-btn" onclick="window._deviceCommand('${device.device_id}', 'toggle')">Toggle</button>
        </div>
        ${telemetryHtml ? '<div style="margin-top:10px;font-size:11px;color:#50fa7b;margin-bottom:4px">Телеметрия</div>' + telemetryHtml : ''}
    `;
}

function deselectDevice() {
    selectedDeviceId = null;
    panelDevices.querySelectorAll('.device-item.selected').forEach(el => el.classList.remove('selected'));
    panelDeviceDetail.classList.add('hidden');
}

window._deselectDevice = deselectDevice;

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
    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'update' && msg.data) {
                gridData = msg.data;
                gridTitle.textContent = `${gridData.name} (${gridData.grid_id})`;
                buildScene(gridData, false);
                renderGridPanel(gridData);
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
            const dmgStr = g.damaged_block_count > 0 ? ` · ${g.damaged_block_count} dmg` : '';
            el.innerHTML = `
                <div class="name">${g.name}</div>
                <div class="meta">${g.is_static ? 'Станция' : 'Корабль'} · ${g.block_count} блоков · ${posStr}${dmgStr}</div>
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

// ── Animate ──
function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
    updateLabels();
}

loadGrids();
loadFleet();
connectWS();
setInterval(loadGrids, 10000);
setInterval(loadFleet, 15000);
buildFleetView();
animate();
