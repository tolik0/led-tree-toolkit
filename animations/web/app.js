const PREVIEW_COLORS = ["#ff6a00", "#ffb84d", "#ff3c2a", "#ffd18f", "#1f7a8c"];

const elements = {
  wsUrl: document.getElementById("wsUrl"),
  ledCount: document.getElementById("ledCount"),
  connectBtn: document.getElementById("connectBtn"),
  disconnectBtn: document.getElementById("disconnectBtn"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  animationSelect: document.getElementById("animationSelect"),
  animationDescription: document.getElementById("animationDescription"),
  brightnessRange: document.getElementById("brightnessRange"),
  brightnessValue: document.getElementById("brightnessValue"),
  frameDelay: document.getElementById("frameDelay"),
  animControls: document.getElementById("animControls"),
  ledOrder: document.getElementById("ledOrder"),
  startBtn: document.getElementById("startBtn"),
  stopBtn: document.getElementById("stopBtn"),
  frameSize: document.getElementById("frameSize"),
  frameRate: document.getElementById("frameRate"),
  modeLabel: document.getElementById("modeLabel"),
  previewCanvas: document.getElementById("previewCanvas"),
  coordsStatus: document.getElementById("coordsStatus"),
  autoRotateToggle: document.getElementById("autoRotateToggle"),
};

const animations = [
  {
    id: "rainbow",
    name: "Rainbow",
    description: "Classic rainbow cycle across LED indices.",
  },
  {
    id: "sphere",
    name: "Sphere",
    description: "Growing colored spheres from the center.",
  },
  {
    id: "radial_pulse",
    name: "Radial pulse",
    description: "Pulses expanding from random points.",
  },
  {
    id: "flame",
    name: "Flame",
    description: "Flickering flame gradient from bottom to top.",
  },
  {
    id: "mic_bass",
    name: "Mic bass pulse",
    description: "Bass-driven pulse using microphone input.",
  },
  {
    id: "mic_spectrum",
    name: "Mic spectrum",
    description: "Spectrum bands mapped over tree height.",
  },
  {
    id: "mic_rise",
    name: "Mic rise",
    description: "Bass-reactive rise from the base in a single color.",
  },
];

let controlSocket = null;
let previewSocket = null;
let coords = [];
let coordsMeta = null;
let previewRotation = 0;
let previewPitch = 0;
let isDraggingPreview = false;
let dragStartX = 0;
let dragStartY = 0;
let dragStartRot = 0;
let dragStartPitch = 0;
let lastFrame = null;
let lastBrightness = 1;
let fpsCount = 0;
let fpsLastTime = performance.now();
let isRunning = false;
let pendingSetTimer = null;
let currentParams = {};

function controlUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/control`;
}

function previewUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/preview`;
}

function updateStatus(online, text) {
  elements.statusDot.classList.toggle("online", online);
  elements.statusText.textContent = text;
}

function setCoordsStatus(message) {
  if (elements.coordsStatus) {
    elements.coordsStatus.textContent = message;
  }
}

function parseCoordsText(text) {
  const lines = text.split(/\r?\n/);
  const parsed = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    const match = line.match(/^LED\s+(\d+):\s*\((.+)\)/);
    if (!match) continue;
    const index = parseInt(match[1], 10);
    let coordsRow = [];
    if (match[2].includes("array")) {
      const arrayMatches = [...match[2].matchAll(/array\(\[([^\]]+)\]/g)];
      for (const arrayMatch of arrayMatches.slice(0, 3)) {
        const nums = arrayMatch[1].match(/[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/g);
        if (!nums || nums.length === 0) continue;
        coordsRow.push(parseFloat(nums[0]));
      }
    } else {
      const numbers = match[2].match(/[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/g);
      if (numbers && numbers.length >= 3) {
        coordsRow = [parseFloat(numbers[0]), parseFloat(numbers[1]), parseFloat(numbers[2])];
      }
    }
    if (coordsRow.length < 3) continue;
    parsed.push({ index, coord: coordsRow });
  }
  return parsed;
}

async function loadCoords() {
  const url = "/coords.txt";
  if (!url) {
    setCoordsStatus("Coords: missing URL");
    return;
  }
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      setCoordsStatus(`Coords: failed to load (${response.status})`);
      return;
    }
    const text = await response.text();
    const parsed = parseCoordsText(text);
    if (!parsed.length) {
      setCoordsStatus("Coords: no points parsed");
      return;
    }
    coords = parsed;
    coordsMeta = computeCoordsMeta(parsed);
    setCoordsStatus(`Coords: loaded ${coords.length} points`);
  } catch (err) {
    console.warn("Failed to load coords:", err);
    setCoordsStatus("Coords: load error");
  }
}

function computeCoordsMeta(points) {
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  for (const point of points) {
    const [x, y, z] = point.coord;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    minZ = Math.min(minZ, z);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    maxZ = Math.max(maxZ, z);
  }
  const center = [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
  const range = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1);
  return { center, range };
}

function connectSockets() {
  if (!controlSocket || controlSocket.readyState > 1) {
    controlSocket = new WebSocket(controlUrl());
    updateStatus(false, "Connecting...");
    controlSocket.addEventListener("open", () => updateStatus(true, "Server connected"));
    controlSocket.addEventListener("close", () => updateStatus(false, "Server disconnected"));
    controlSocket.addEventListener("error", () => updateStatus(false, "Server error"));
  }
  if (!previewSocket || previewSocket.readyState > 1) {
    previewSocket = new WebSocket(previewUrl());
    previewSocket.binaryType = "arraybuffer";
    previewSocket.addEventListener("message", (event) => {
      if (!(event.data instanceof ArrayBuffer)) return;
      const view = new Uint8Array(event.data);
      if (view.length < 4) return;
      lastBrightness = view[0] / 255;
      lastFrame = view.slice(1);
      fpsCount += 1;
    });
  }
}

function disconnectSockets() {
  if (controlSocket) controlSocket.close();
  if (previewSocket) previewSocket.close();
}

function sendControl(payload) {
  if (!controlSocket || controlSocket.readyState !== WebSocket.OPEN) {
    connectSockets();
    setTimeout(() => sendControl(payload), 300);
    return;
  }
  controlSocket.send(JSON.stringify(payload));
}

function scheduleSettingsUpdate() {
  if (!isRunning) return;
  if (pendingSetTimer) {
    clearTimeout(pendingSetTimer);
  }
  pendingSetTimer = setTimeout(() => {
    sendControl({ action: "set", ...buildSettings() });
    pendingSetTimer = null;
  }, 150);
}

function buildSettings() {
  const frameDelay = elements.frameDelay ? parseFloat(elements.frameDelay.value) : 0.02;
  return {
    name: elements.animationSelect.value,
    led_count: parseInt(elements.ledCount.value, 10) || 400,
    brightness: parseInt(elements.brightnessRange.value, 10) || 200,
    frame_delay: Number.isFinite(frameDelay) ? frameDelay : 0.02,
    esp_ws_url: elements.wsUrl.value.trim(),
    led_order: elements.ledOrder ? elements.ledOrder.value : null,
    params: currentParams,
  };
}

function startAnimation() {
  const settings = buildSettings();
  sendControl({ action: "start", ...settings });
  elements.modeLabel.textContent = animations.find((anim) => anim.id === settings.name)?.name || "Running";
  isRunning = true;
}

function stopAnimation() {
  sendControl({ action: "stop" });
  elements.modeLabel.textContent = "Preview";
  isRunning = false;
}

function resizePreviewCanvas() {
  const canvas = elements.previewCanvas;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const pixelRatio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * pixelRatio));
  canvas.height = Math.max(1, Math.floor(rect.height * pixelRatio));
}

function renderPreview(frame) {
  const canvas = elements.previewCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  if (!coordsMeta || coords.length === 0) {
    ctx.fillStyle = "rgba(27, 27, 24, 0.2)";
    ctx.font = `${Math.max(12, width * 0.03)}px sans-serif`;
    ctx.fillText("No coordinates loaded", width * 0.1, height * 0.55);
    return;
  }

  if (elements.autoRotateToggle && elements.autoRotateToggle.checked) {
    previewRotation += 0.006;
    previewPitch += 0.002;
  }

  const scale = 0.45 * Math.min(width, height) / coordsMeta.range;
  const cosY = Math.cos(previewRotation);
  const sinY = Math.sin(previewRotation);
  const cosX = Math.cos(previewPitch);
  const sinX = Math.sin(previewPitch);

  const brightness = lastBrightness || 1;
  if (!frame || frame.length === 0) {
    ctx.fillStyle = "rgba(27, 27, 24, 0.25)";
    const idleStride = Math.max(1, Math.floor(coords.length / 1000));
    for (let i = 0; i < coords.length; i += idleStride) {
      const point = coords[i];
      const [x, y, z] = point.coord;
      let dx = x - coordsMeta.center[0];
      let dy = y - coordsMeta.center[1];
      let dz = z - coordsMeta.center[2];

      const x1 = dx * cosY - dz * sinY;
      const z1 = dx * sinY + dz * cosY;
      const y1 = dy * cosX - z1 * sinX;

      const screenX = width / 2 + x1 * scale;
      const screenY = height / 2 + y1 * scale;
      ctx.beginPath();
      ctx.arc(screenX, screenY, 2, 0, Math.PI * 2);
      ctx.fill();
    }
    return;
  }
  const stride = Math.max(1, Math.floor(coords.length / 800));
  for (let i = 0; i < coords.length; i += stride) {
    const point = coords[i];
    const idx = point.index;
    if (!frame || idx * 3 + 2 >= frame.length) continue;
    const [x, y, z] = point.coord;
    let dx = x - coordsMeta.center[0];
    let dy = y - coordsMeta.center[1];
    let dz = z - coordsMeta.center[2];

    const x1 = dx * cosY - dz * sinY;
    const z1 = dx * sinY + dz * cosY;
    const y1 = dy * cosX - z1 * sinX;
    const z2 = dy * sinX + z1 * cosX;

    const screenX = width / 2 + x1 * scale;
    const screenY = height / 2 + y1 * scale;
    const depth = (z2 / coordsMeta.range + 0.5);
    const size = Math.max(1.4, 4 - depth * 2.5);

    const r = Math.round(frame[idx * 3] * brightness);
    const g = Math.round(frame[idx * 3 + 1] * brightness);
    const b = Math.round(frame[idx * 3 + 2] * brightness);
    ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.9)`;
    ctx.beginPath();
    ctx.arc(screenX, screenY, size, 0, Math.PI * 2);
    ctx.fill();
  }
}

function updateFrameSize() {
  const numLeds = Math.max(1, parseInt(elements.ledCount.value, 10) || 1);
  const bytes = 1 + numLeds * 3;
  elements.frameSize.textContent = `${bytes} bytes`;
}

function updateFrameRate() {
  const now = performance.now();
  const elapsed = now - fpsLastTime;
  if (elapsed >= 1000) {
    const fps = Math.round((fpsCount / elapsed) * 1000);
    elements.frameRate.textContent = `${fps} fps`;
    fpsCount = 0;
    fpsLastTime = now;
  }
}

function populateAnimations() {
  animations.forEach((anim) => {
    const option = document.createElement("option");
    option.value = anim.id;
    option.textContent = anim.name;
    elements.animationSelect.appendChild(option);
  });
  elements.animationSelect.value = animations[0].id;
  elements.animationDescription.textContent = animations[0].description;
}

function updateAnimationDescription() {
  const selection = animations.find((anim) => anim.id === elements.animationSelect.value);
  if (selection) {
    elements.animationDescription.textContent = selection.description;
  }
  buildAnimationControls();
  if (isRunning) {
    startAnimation();
  }
}

function previewLoop() {
  renderPreview(lastFrame);
  updateFrameRate();
  requestAnimationFrame(previewLoop);
}

const paramSchemas = {
  rainbow: [
    { key: "color_step", label: "Color step", min: 1, max: 25, step: 1, default: 10 },
  ],
  sphere: [
    { key: "transition_time", label: "Transition time", min: 0.5, max: 6.0, step: 0.1, default: 2.0 },
    { key: "color_step", label: "Color step", min: 1, max: 40, step: 1, default: 20 },
  ],
  radial_pulse: [
    { key: "pulse_speed", label: "Pulse speed", min: 0.2, max: 5.0, step: 0.1, default: 1.0 },
  ],
  flame: [
    { key: "speed", label: "Flame speed", min: 0.05, max: 0.5, step: 0.01, default: 0.2 },
    { key: "flicker", label: "Flicker", min: 0.2, max: 1.5, step: 0.05, default: 1.0 },
    { key: "core_radius", label: "Core radius", min: 20, max: 200, step: 5, default: 100 },
    { key: "height_fraction", label: "Base height", min: 0.1, max: 0.6, step: 0.05, default: 0.2 },
    { key: "base_color", label: "Base color", type: "color", default: "#ff2800" },
  ],
  mic_bass: [
    { key: "sensitivity", label: "Sensitivity", min: 0.2, max: 3.0, step: 0.1, default: 1.0 },
    { key: "floor", label: "Minimum brightness", min: 0.0, max: 0.3, step: 0.01, default: 0.05 },
    { key: "base_color", label: "Base color", type: "color", default: "#ff2800" },
  ],
  mic_spectrum: [
    { key: "bands", label: "Bands", min: 4, max: 16, step: 1, default: 8 },
    { key: "min_hz", label: "Min Hz", min: 20, max: 200, step: 5, default: 80 },
    { key: "max_hz", label: "Max Hz", min: 1000, max: 8000, step: 100, default: 4000 },
    { key: "sensitivity", label: "Sensitivity", min: 0.2, max: 3.0, step: 0.1, default: 1.0 },
  ],
  mic_rise: [
    { key: "min_hz", label: "Min Hz", min: 20, max: 120, step: 5, default: 40 },
    { key: "max_hz", label: "Max Hz", min: 120, max: 400, step: 10, default: 180 },
    { key: "sensitivity", label: "Sensitivity", min: 0.2, max: 3.0, step: 0.1, default: 1.0 },
    { key: "edge_softness", label: "Edge softness", min: 0.02, max: 0.3, step: 0.01, default: 0.12 },
    { key: "base_color", label: "Base color", type: "color", default: "#ff2800" },
    { key: "floor", label: "Minimum height", min: 0.0, max: 0.2, step: 0.01, default: 0.03 },
    { key: "attack", label: "Rise speed", min: 0.05, max: 0.6, step: 0.01, default: 0.4 },
    { key: "release", label: "Fall speed", min: 0.02, max: 0.4, step: 0.01, default: 0.12 },
  ],
};

function buildAnimationControls() {
  if (!elements.animControls) return;
  const name = elements.animationSelect.value;
  const schema = paramSchemas[name] || [];
  elements.animControls.innerHTML = "";
  const prevParams = { ...currentParams };
  currentParams = { ...prevParams };
  for (const param of schema) {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const label = document.createElement("label");
    label.textContent = param.label;
    wrapper.appendChild(label);

    if (param.type === "color") {
      const input = document.createElement("input");
      input.type = "color";
      input.value = currentParams[param.key] || param.default;
      currentParams[param.key] = input.value;
      input.addEventListener("input", () => {
        currentParams[param.key] = input.value;
        scheduleSettingsUpdate();
      });
      wrapper.appendChild(input);
    } else if (param.type === "select") {
      const select = document.createElement("select");
      for (const option of param.options || []) {
        const opt = document.createElement("option");
        opt.value = option.value;
        opt.textContent = option.label;
        select.appendChild(opt);
      }
      select.value = currentParams[param.key] || param.default;
      currentParams[param.key] = select.value;
      select.addEventListener("change", () => {
        currentParams[param.key] = select.value;
        scheduleSettingsUpdate();
        if (param.key === "plane") {
          buildAnimationControls();
        }
      });
      wrapper.appendChild(select);
    } else if (param.type === "gizmo") {
      if (currentParams.plane !== "custom") {
        continue;
      }
      const gizmoRow = document.createElement("div");
      gizmoRow.className = "gizmo-row";
      const canvas = document.createElement("canvas");
      canvas.width = 180;
      canvas.height = 180;
      canvas.className = "gizmo";
      const flipBtn = document.createElement("button");
      flipBtn.type = "button";
      flipBtn.className = "btn ghost";
      flipBtn.textContent = "Flip";
      gizmoRow.appendChild(canvas);
      gizmoRow.appendChild(flipBtn);
      wrapper.appendChild(gizmoRow);

      let normal = currentParams[param.key] || param.default;
      if (!Array.isArray(normal) || normal.length !== 3) {
        normal = param.default;
      }
      currentParams[param.key] = normal;

      let drag = false;
      const drawGizmo = () => {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const radius = canvas.width * 0.4;
        ctx.strokeStyle = "rgba(27, 27, 24, 0.2)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.stroke();

        const nx = normal[0];
        const ny = normal[1];
        const nz = normal[2];
        const px = cx + nx * radius;
        const py = cy - ny * radius;
        ctx.strokeStyle = "rgba(255, 106, 0, 0.8)";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(px, py);
        ctx.stroke();

        ctx.fillStyle = nz >= 0 ? "#ff6a00" : "#1f7a8c";
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fill();
      };

      const updateFromPointer = (event) => {
        const rect = canvas.getBoundingClientRect();
        const x = (event.clientX - rect.left - rect.width / 2) / (rect.width / 2);
        const y = (rect.height / 2 - (event.clientY - rect.top)) / (rect.height / 2);
        let nx = Math.max(-1, Math.min(1, x));
        let ny = Math.max(-1, Math.min(1, y));
        let length = Math.sqrt(nx * nx + ny * ny);
        if (length > 1) {
          nx /= length;
          ny /= length;
          length = 1;
        }
        const nz = Math.sqrt(Math.max(0, 1 - length * length)) * Math.sign(normal[2] || 1);
        normal = [nx, ny, nz];
        currentParams[param.key] = normal;
        drawGizmo();
        scheduleSettingsUpdate();
      };

      canvas.addEventListener("pointerdown", (event) => {
        drag = true;
        canvas.setPointerCapture(event.pointerId);
        updateFromPointer(event);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (!drag) return;
        updateFromPointer(event);
      });
      canvas.addEventListener("pointerup", (event) => {
        drag = false;
        canvas.releasePointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointerleave", () => {
        drag = false;
      });
      flipBtn.addEventListener("click", () => {
        normal = [normal[0], normal[1], -normal[2]];
        currentParams[param.key] = normal;
        drawGizmo();
        scheduleSettingsUpdate();
      });

      drawGizmo();
    } else {
      const input = document.createElement("input");
      input.type = "range";
      input.min = param.min;
      input.max = param.max;
      input.step = param.step;
      input.value = currentParams[param.key] ?? param.default;
      currentParams[param.key] = parseFloat(input.value);
      const valueRow = document.createElement("div");
      valueRow.className = "range-row";
      const left = document.createElement("span");
      left.textContent = param.min;
      const valueSpan = document.createElement("span");
      valueSpan.textContent = input.value;
      const right = document.createElement("span");
      right.textContent = param.max;
      valueRow.append(left, valueSpan, right);

      input.addEventListener("input", () => {
        valueSpan.textContent = input.value;
        currentParams[param.key] = parseFloat(input.value);
        scheduleSettingsUpdate();
      });
      wrapper.appendChild(input);
      wrapper.appendChild(valueRow);
    }
    elements.animControls.appendChild(wrapper);
  }
}

function attachListeners() {
  elements.connectBtn.addEventListener("click", connectSockets);
  elements.disconnectBtn.addEventListener("click", disconnectSockets);
  elements.startBtn.addEventListener("click", startAnimation);
  elements.stopBtn.addEventListener("click", stopAnimation);
  elements.animationSelect.addEventListener("change", updateAnimationDescription);
  elements.brightnessRange.addEventListener("input", () => {
    elements.brightnessValue.textContent = elements.brightnessRange.value;
    scheduleSettingsUpdate();
  });
  if (elements.frameDelay) {
    elements.frameDelay.addEventListener("input", scheduleSettingsUpdate);
  }
  if (elements.ledOrder) {
    elements.ledOrder.addEventListener("change", scheduleSettingsUpdate);
  }
  elements.ledCount.addEventListener("input", updateFrameSize);
  window.addEventListener("resize", resizePreviewCanvas);
  if (elements.previewCanvas) {
    elements.previewCanvas.addEventListener("pointerdown", (event) => {
      isDraggingPreview = true;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      dragStartRot = previewRotation;
      dragStartPitch = previewPitch;
      elements.previewCanvas.setPointerCapture(event.pointerId);
    });
    elements.previewCanvas.addEventListener("pointermove", (event) => {
      if (!isDraggingPreview) return;
      const dx = event.clientX - dragStartX;
      const dy = event.clientY - dragStartY;
      previewRotation = dragStartRot + dx * 0.01;
      previewPitch = dragStartPitch + dy * 0.01;
    });
    elements.previewCanvas.addEventListener("pointerup", (event) => {
      isDraggingPreview = false;
      elements.previewCanvas.releasePointerCapture(event.pointerId);
    });
    elements.previewCanvas.addEventListener("pointerleave", () => {
      isDraggingPreview = false;
    });
  }
}

function init() {
  populateAnimations();
  updateFrameSize();
  resizePreviewCanvas();
  elements.brightnessValue.textContent = elements.brightnessRange.value;
  elements.modeLabel.textContent = "Preview";
  attachListeners();
  loadCoords();
  updateStatus(false, "Server disconnected");
  buildAnimationControls();

  let previewIndex = 0;
  setInterval(() => {
    if (!lastFrame && currentParams.base_color) {
      previewIndex = (previewIndex + 1) % PREVIEW_COLORS.length;
      currentParams.base_color = PREVIEW_COLORS[previewIndex];
    }
  }, 1800);

  requestAnimationFrame(previewLoop);
}

init();
