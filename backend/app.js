const agents = [
  { id: "obstacle", name: "Obstacle avoidance specialist", normal: "Path clear", active: "Obstacle ahead. Detour recommended", severity: "danger" },
  { id: "tactile", name: "Tactile paving specialist", normal: "Continuous tactile paving", active: "Tactile paving blocked for 1.8 m", severity: "warn" },
  { id: "route", name: "Safe path specialist", normal: "Right boundary is safe", active: "Replan: turn left 25 degrees", severity: "warn" },
  { id: "traffic", name: "Traffic light specialist", normal: "Green light. Check before proceeding", active: "Red light. Stop and wait", severity: "danger" },
  { id: "crossing", name: "Crossing specialist", normal: "Outside the crossing", active: "Vehicle approaching. Wait for a second confirmation", severity: "danger" },
  { id: "finding", name: "Object search specialist", normal: "No target requested", active: "Cup 2 m ahead to the right", severity: "warn" },
  { id: "scene", name: "Scene description specialist", normal: "Sidewalk, tactile paving and crossing", active: "Crowding and occlusion detected", severity: "warn" },
  { id: "intent", name: "Intent recognition specialist", normal: "Navigation intent: continue straight", active: "Intent changed to object search", severity: "warn" },
];

const scenarios = {
  sidewalk: {
    title: "Green light 4 m ahead. Continue along the tactile paving",
    subtitle: "Wrist cue D1 indicates a distant approach. Keep a slow pace.",
    activeAgents: ["scene"],
    glasses: "Capture the scene ahead, obstacles, traffic signals and tactile paving.",
    phone: "Relay cloud-coordinated guidance to speech and wrist feedback.",
    bracelet: "D1: light 0.15-second pulse every 2 seconds (3-5 m).",
    priority: "Informational",
    wristCue: "D1",
    description: "Optional context available",
  },
  blocked: {
    title: "Tactile paving blocked. Step left around it, then continue straight",
    subtitle: "Wrist cue W1 indicates a hazard. Slow down and detour.",
    activeAgents: ["obstacle", "tactile", "route", "scene"],
    glasses: "Detect partial tactile paving obstruction and lateral walkable space.",
    phone: "Relay coordinated obstacle, tactile paving and path guidance for a short detour.",
    bracelet: "W1: two strong 0.25-second pulses. Hazard warning.",
    priority: "Warning",
    wristCue: "W1",
    description: "Optional context suppressed",
  },
  crossing: {
    title: "Red light. Stop before the curb and wait",
    subtitle: "Wrist cue W3 indicates emergency stop. Speech conveys only essential risk information.",
    activeAgents: ["traffic", "crossing", "obstacle", "scene"],
    glasses: "Detect signals, crosswalks, vehicle motion and pedestrian flow.",
    phone: "Relay prioritized crossing guidance while object search and casual speech are suspended.",
    bracelet: "W3: one strong 1-second pulse and four rapid short pulses. Emergency stop.",
    priority: "Danger",
    wristCue: "W3",
    description: "Optional context suppressed",
  },
  finding: {
    title: "Target 2 m ahead to the right. Approach slowly",
    subtitle: "Wrist cue D2 indicates a medium-distance approach. Speech confirms target type and distance.",
    activeAgents: ["finding", "intent", "obstacle", "route"],
    glasses: "Locate the partly occluded target while checking hazards underfoot.",
    phone: "Relay the change from navigation to object search and the updated feedback priority.",
    bracelet: "D2: light 0.15-second pulse every second (1.5-3 m).",
    priority: "Informational",
    wristCue: "D2",
    description: "Optional context available",
  },
};

const apiScenarioMap = {
  sidewalk: "sidewalk",
  blocked: "blocked",
  crossing: "crossing",
  finding: "finding",
};

const agentList = document.querySelector("#agentList");
const scenarioButtons = document.querySelectorAll(".scenario");
const mainInstruction = document.querySelector("#mainInstruction");
const secondaryInstruction = document.querySelector("#secondaryInstruction");
const glassesText = document.querySelector("#glassesText");
const phoneText = document.querySelector("#phoneText");
const braceletText = document.querySelector("#braceletText");
const priorityText = document.querySelector("#priorityText");
const speechState = document.querySelector("#speechState");
const wristState = document.querySelector("#wristState");
const descriptionState = document.querySelector("#descriptionState");
const dataSource = document.querySelector("#dataSource");
const systemStatus = document.querySelector("#systemStatus");
const mediaInput = document.querySelector("#mediaInput");
const targetQuery = document.querySelector("#targetQuery");
const analyzeMediaButton = document.querySelector("#analyzeMediaButton");
const mediaStatus = document.querySelector("#mediaStatus");
const mediaPreview = document.querySelector("#mediaPreview");
const mediaPreviewImage = document.querySelector("#mediaPreviewImage");
const mediaPreviewVideo = document.querySelector("#mediaPreviewVideo");
const mediaFileMeta = document.querySelector("#mediaFileMeta");
const mediaSceneSummary = document.querySelector("#mediaSceneSummary");
const mediaEvidenceChips = document.querySelector("#mediaEvidenceChips");
const processedResultImage = document.querySelector("#processedResultImage");
const processedCanvas = document.querySelector("#processedCanvas");
const processedPlaceholder = document.querySelector("#processedPlaceholder");
const annotationList = document.querySelector("#annotationList");
let apiBase = "";
let mediaObjectUrl = "";
let lastDetectedSceneType = "";

const candidateApiBases = [
  "http://127.0.0.1:8012",
  "http://127.0.0.1:8011",
  "http://127.0.0.1:8010",
  "http://127.0.0.1:8009",
  "",
  "http://127.0.0.1:8008",
  "http://127.0.0.1:8007",
  "http://127.0.0.1:8006",
  "http://127.0.0.1:8005",
  "http://127.0.0.1:8004",
  "http://127.0.0.1:8003",
  "http://127.0.0.1:8002",
  "http://127.0.0.1:8000",
];

async function detectApiBase() {
  for (const base of candidateApiBases) {
    try {
      const response = await fetch(`${base}/api/scenarios`, { cache: "no-store" });
      if (response.ok) {
        apiBase = base;
        const label = base || window.location.origin || "current page";
        mediaStatus.textContent = `Backend connected: ${label}`;
        return base;
      }
    } catch (error) {
      // Try the next candidate.
    }
  }
  mediaStatus.textContent = "Python backend unavailable. Start it with: LIBEREYE_ENABLE_STRONG_VISION=1 python -m libereye.server --port 8012";
  return "";
}

async function apiFetch(path, options) {
  if (!apiBase) {
    await detectApiBase();
  }
  const response = await fetch(`${apiBase}${path}`, options);
  return response;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 KB";
  }
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function previewSelectedMedia() {
  const file = mediaInput.files && mediaInput.files[0];
  if (!file) {
    mediaPreview.hidden = true;
    mediaFileMeta.textContent = "No media selected";
    mediaSceneSummary.textContent = "Select an image or video to view an analysis summary.";
    mediaEvidenceChips.innerHTML = "";
    resetProcessedResult();
    return;
  }

  if (mediaObjectUrl) {
    URL.revokeObjectURL(mediaObjectUrl);
  }
  mediaObjectUrl = URL.createObjectURL(file);
  mediaPreview.hidden = false;
  mediaFileMeta.textContent = `${file.name} · ${file.type || "unknown type"} · ${formatBytes(file.size)}`;
  mediaSceneSummary.textContent = "Media loaded. Select Analyze media to start the specialist analysis.";
  mediaEvidenceChips.innerHTML = "";
  resetProcessedResult("Media loaded. Waiting for model analysis.");

  if (file.type.startsWith("video/")) {
    mediaPreviewImage.hidden = true;
    mediaPreviewImage.removeAttribute("src");
    mediaPreviewVideo.hidden = false;
    mediaPreviewVideo.src = mediaObjectUrl;
    mediaPreviewVideo.load();
  } else {
    mediaPreviewVideo.hidden = true;
    mediaPreviewVideo.removeAttribute("src");
    mediaPreviewImage.hidden = false;
    mediaPreviewImage.src = mediaObjectUrl;
  }
}

async function prepareMediaUpload(file) {
  if (!file.type.startsWith("image/")) {
    return file;
  }
  const supportedImageExtensions = [".jpg", ".jpeg", ".png", ".webp", ".bmp"];
  const lowerName = file.name.toLowerCase();
  if (supportedImageExtensions.some((extension) => lowerName.endsWith(extension))) {
    return file;
  }
  return convertImageToJpeg(file);
}

async function convertImageToJpeg(file) {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await loadImage(objectUrl);
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth || image.width;
    canvas.height = image.naturalHeight || image.height;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0);
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((value) => {
        if (value) {
          resolve(value);
        } else {
          reject(new Error("The browser could not convert this image format"));
        }
      }, "image/jpeg", 0.92);
    });
    const outputName = file.name.replace(/\.[^.]+$/, "") || "uploaded-image";
    return new File([blob], `${outputName}.jpg`, { type: "image/jpeg" });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The browser could not read this image"));
    image.src = src;
  });
}

function chip(text, severity = "") {
  const element = document.createElement("span");
  element.className = `media-chip ${severity}`.trim();
  element.textContent = text;
  return element;
}

function resetProcessedResult(message = "Model results appear after analysis") {
  processedResultImage.hidden = true;
  processedResultImage.removeAttribute("src");
  processedCanvas.hidden = true;
  processedPlaceholder.hidden = false;
  processedPlaceholder.textContent = message;
  annotationList.innerHTML = "";
}

function renderProcessedResult(evidence) {
  const visualization = evidence && evidence.visualization;
  const hasServerImage = visualization && visualization.image_data;

  if (hasServerImage) {
    processedResultImage.hidden = false;
    processedResultImage.src = visualization.image_data;
    processedCanvas.hidden = true;
    processedPlaceholder.hidden = true;
  } else {
    drawClientProcessedOverlay(evidence);
  }

  renderAnnotationList(evidence);
}

function drawClientProcessedOverlay(evidence) {
  const source = !mediaPreviewImage.hidden ? mediaPreviewImage : !mediaPreviewVideo.hidden ? mediaPreviewVideo : null;
  if (!source) {
    resetProcessedResult("No media available to render.");
    return;
  }

  if (source.tagName === "IMG" && !source.complete) {
    source.addEventListener("load", () => drawClientProcessedOverlay(evidence), { once: true });
    processedPlaceholder.hidden = false;
    processedPlaceholder.textContent = "Results appear when the image loads.";
    return;
  }

  if (source.tagName === "VIDEO" && source.readyState < 2) {
    source.addEventListener("loadeddata", () => drawClientProcessedOverlay(evidence), { once: true });
    processedPlaceholder.hidden = false;
    processedPlaceholder.textContent = "Results appear when the video keyframe loads.";
    return;
  }

  const width = source.videoWidth || source.naturalWidth || source.clientWidth;
  const height = source.videoHeight || source.naturalHeight || source.clientHeight;
  if (!width || !height) {
    resetProcessedResult("Media dimensions unavailable. Results cannot be drawn.");
    return;
  }

  processedCanvas.width = width;
  processedCanvas.height = height;
  const context = processedCanvas.getContext("2d");
  context.clearRect(0, 0, width, height);
  context.drawImage(source, 0, 0, width, height);
  drawRegionBands(context, width, height, evidence.semantic_regions || []);
  drawObjectBoxes(context, width, height, evidence);

  processedResultImage.hidden = true;
  processedCanvas.hidden = false;
  processedPlaceholder.hidden = true;
}

function drawRegionBands(context, width, height, regions) {
  const visibleRegions = regions
    .filter((region) => region.coverage >= 0.025 || region.label === "tactile_paving")
    .sort((a, b) => b.coverage - a.coverage)
    .slice(0, 5);

  visibleRegions.forEach((region) => {
    const [x, bandWidth] = directionBand(region.direction, width);
    const y = Math.floor(height * 0.5);
    const bandHeight = height - y;
    context.fillStyle = regionColor(region.label, 0.28);
    context.fillRect(x, y, bandWidth, bandHeight);
    drawCanvasLabel(
      context,
      `${regionDisplayName(region.label)} coverage ${Math.round(region.coverage * 100)}%`,
      x + 10,
      y + 12,
      regionColor(region.label, 0.95)
    );
  });
}

function drawObjectBoxes(context, width, height, evidence) {
  const frameSize = evidence.frame_size || {};
  const scaleX = width / (frameSize.width || width);
  const scaleY = height / (frameSize.height || height);

  (evidence.detected_objects || [])
    .filter((object) => object.bbox && object.bbox.length === 4)
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, 8)
    .forEach((object) => {
      const [rawX, rawY, rawW, rawH] = object.bbox;
      const x = rawX * scaleX;
      const y = rawY * scaleY;
      const boxWidth = rawW * scaleX;
      const boxHeight = rawH * scaleY;
      if (boxWidth <= 2 || boxHeight <= 2) {
        return;
      }
      const label = objectLabelText(object);
      context.strokeStyle = "#2f73c7";
      context.lineWidth = Math.max(3, Math.round(width / 320));
      context.strokeRect(x, y, boxWidth, boxHeight);
      drawCanvasLabel(context, label, x, Math.max(8, y - 28), "rgba(28, 89, 166, 0.95)");
    });
}

function drawCanvasLabel(context, text, x, y, background) {
  context.save();
  const fontSize = Math.max(14, Math.min(20, Math.round(processedCanvas.width / 48)));
  context.font = `700 ${fontSize}px -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif`;
  const metrics = context.measureText(text);
  const boxWidth = Math.min(metrics.width + 16, processedCanvas.width - x - 4);
  const boxHeight = fontSize + 12;
  context.fillStyle = background;
  context.fillRect(x, y, boxWidth, boxHeight);
  context.fillStyle = "#fff";
  context.fillText(text, x + 8, y + fontSize + 2, Math.max(40, boxWidth - 16));
  context.restore();
}

function directionBand(direction, width) {
  if (direction === "left") {
    return [0, Math.floor(width / 3)];
  }
  if (direction === "right") {
    return [Math.floor((width * 2) / 3), Math.ceil(width / 3)];
  }
  if (direction === "center") {
    return [Math.floor(width / 3), Math.ceil(width / 3)];
  }
  return [0, width];
}

function regionColor(label, alpha = 1) {
  const colors = {
    vegetation: `rgba(42, 150, 87, ${alpha})`,
    tactile_paving: `rgba(236, 176, 42, ${alpha})`,
    crosswalk: `rgba(245, 247, 250, ${alpha})`,
    road_or_asphalt: `rgba(87, 96, 111, ${alpha})`,
    walkable_pavement: `rgba(47, 115, 199, ${alpha})`,
    person: `rgba(211, 84, 0, ${alpha})`,
    bicycle: `rgba(31, 138, 112, ${alpha})`,
    car: `rgba(191, 72, 80, ${alpha})`,
    bus: `rgba(191, 72, 80, ${alpha})`,
    truck: `rgba(191, 72, 80, ${alpha})`,
  };
  return colors[label] || `rgba(168, 84, 42, ${alpha})`;
}

function renderAnnotationList(evidence) {
  annotationList.innerHTML = "";
  const labels = evidence.visualization && Array.isArray(evidence.visualization.labels)
    ? evidence.visualization.labels
    : fallbackAnnotationLabels(evidence);

  if (!labels.length) {
    const empty = document.createElement("span");
    empty.className = "annotation-empty";
    empty.textContent = "No distinct objects returned. Showing scene regions.";
    annotationList.appendChild(empty);
    return;
  }

  labels.slice(0, 10).forEach((annotation) => {
    const item = document.createElement("span");
    item.className = `annotation-item ${annotation.type === "region" ? "region" : "object"}`;
    item.textContent = formatAnnotation(annotation);
    annotationList.appendChild(item);
  });
}

function fallbackAnnotationLabels(evidence) {
  return [
    ...(evidence.detected_objects || []).map((object) => ({
      type: "object",
      raw_label: object.label,
      direction: object.direction,
      distance_m: object.distance_m,
      confidence: object.confidence,
      bbox: object.bbox,
    })),
    ...(evidence.semantic_regions || []).map((region) => ({
      type: "region",
      raw_label: region.label,
      direction: region.direction,
      coverage: region.coverage,
      confidence: region.confidence,
    })),
  ];
}

function formatAnnotation(annotation) {
  const direction = directionDisplayName(annotation.direction);
  if (annotation.type === "region") {
    const coverage = typeof annotation.coverage === "number" ? ` coverage ${Math.round(annotation.coverage * 100)}%` : "";
    return `Region: ${regionDisplayName(annotation.raw_label || annotation.label)} ${direction}${coverage}`;
  }
  const distance = annotation.distance_m ? ` ${Number(annotation.distance_m).toFixed(1)}m` : "";
  const confidence = typeof annotation.confidence === "number" ? ` confidence score ${annotation.confidence.toFixed(2)}` : "";
  return `Object: ${objectDisplayName(annotation.raw_label || annotation.label)} ${direction}${distance}${confidence}`;
}

function objectLabelText(object) {
  const distance = object.distance_m ? ` ${Number(object.distance_m).toFixed(1)}m` : "";
  return `${objectDisplayName(object.label)}${distance}`;
}

function directionDisplayName(direction = "unknown") {
  const labels = { left: "on the left", center: "ahead", right: "on the right", unknown: "nearby" };
  return labels[direction] || "nearby";
}

function objectDisplayName(label = "") {
  const labels = {
    person: "pedestrian",
    bicycle: "bicycle",
    car: "car",
    motorcycle: "motorcycle",
    bus: "bus",
    truck: "truck",
    "traffic light": "traffic light",
    traffic_light: "traffic light",
    traffic_light_red: "red light",
    traffic_light_green: "green light",
    traffic_light_yellow: "yellow light",
    bench: "bench",
    backpack: "backpack",
    chair: "chair",
    obstacle: "obstacle",
    person_or_obstacle: "pedestrian/obstacle",
    segmented_object: "segmented object",
  };
  return labels[label] || String(label).replaceAll("_", " ");
}

function regionDisplayName(label = "") {
  const labels = {
    vegetation: "vegetation",
    tactile_paving: "tactile paving",
    crosswalk: "crosswalk",
    road_or_asphalt: "roadway/asphalt",
    walkable_pavement: "walkable pavement",
    person: "pedestrian region",
    bicycle: "bicycle region",
    car: "vehicle region",
    bus: "bus region",
    truck: "vehicle region",
    obstacle: "obstacle region",
    person_or_obstacle: "obstacle region",
    segmented_object: "segmented region",
  };
  return labels[label] || String(label).replaceAll("_", " ");
}

function renderMediaEvidence(evidence) {
  if (!evidence) {
    mediaSceneSummary.textContent = "Media analyzed, but no evidence details were returned.";
    mediaEvidenceChips.innerHTML = "";
    resetProcessedResult("The backend returned no visualization results.");
    return;
  }

  const perception = evidence.perception || {};
  const semanticRegions = evidence.semantic_regions || [];
  const objects = evidence.detected_objects || [];
  const backend = evidence.vision_backend && evidence.vision_backend.active
    ? (evidence.vision_backend.models && evidence.vision_backend.models.length
        ? evidence.vision_backend.models.join(" + ")
        : evidence.vision_backend.model || "Ultralytics")
    : "Heuristic fallback";

  mediaSceneSummary.textContent = conciseMediaSummary(evidence);
  mediaEvidenceChips.innerHTML = "";
  renderProcessedResult(evidence);
  if (evidence.scene_label) {
    mediaEvidenceChips.appendChild(chip(`Detected scene: ${evidence.scene_label}`, evidence.scene_type === "crossing" ? "warn" : ""));
  }
  mediaEvidenceChips.appendChild(chip(`Model: ${backend}`));
  if (Array.isArray(evidence.semantic_sources) && evidence.semantic_sources.length) {
    mediaEvidenceChips.appendChild(chip(`Semantic sources: ${formatSemanticSources(evidence.semantic_sources)}`));
  }
  if (evidence.media_type === "video" && evidence.sampled_frames) {
    mediaEvidenceChips.appendChild(chip(`Video keyframes: ${evidence.sampled_frames} sampled`));
  }
  if (shouldShowTrafficLight(evidence, perception)) {
    mediaEvidenceChips.appendChild(chip(`Traffic light: ${perception.traffic_light}`));
  }
  if (perception.obstacle_distance_m && perception.obstacle_distance_m <= 2.0) {
    mediaEvidenceChips.appendChild(chip(
      `Obstacle: ${Number(perception.obstacle_distance_m).toFixed(1)} m`,
      perception.obstacle_distance_m <= 2.0 ? "danger" : ""
    ));
  }
  if (evidence.depth_estimate && evidence.depth_estimate.center_depth_m) {
    mediaEvidenceChips.appendChild(chip(`Center depth: ${Number(evidence.depth_estimate.center_depth_m).toFixed(1)} m`));
  }
  semanticRegions
    .filter((region) => region.coverage >= 0.08 || region.label === "tactile_paving")
    .slice(0, 3)
    .forEach((region) => {
    mediaEvidenceChips.appendChild(chip(`Region: ${formatRegion(region)}`));
  });
  objects.slice(0, 4).forEach((object) => {
    const distance = object.distance_m ? ` ${Number(object.distance_m).toFixed(1)}m` : "";
    mediaEvidenceChips.appendChild(chip(`Object: ${objectDisplayName(object.label)} ${directionDisplayName(object.direction)}${distance}`));
  });
  (evidence.detected_texts || []).slice(0, 3).forEach((text) => {
    mediaEvidenceChips.appendChild(chip(`Text: ${text}`));
  });
  (evidence.sign_candidates || []).slice(0, 2).forEach((sign) => {
    mediaEvidenceChips.appendChild(chip(`Sign: ${sign}`));
  });
}

function conciseMediaSummary(evidence) {
  if (!evidence) {
    return "Media analyzed.";
  }
  const perception = evidence.perception || {};
  const parts = [];
  if (evidence.scene_label) {
    parts.push(evidence.scene_label);
  }
  if (evidence.scene_description) {
    parts.push(evidence.scene_description);
  }
  if (shouldShowTrafficLight(evidence, perception)) {
    parts.push(`Light: ${perception.traffic_light}`);
  }
  if (perception.obstacle_distance_m && perception.obstacle_distance_m <= 2.0) {
    parts.push(`Obstacle ${Number(perception.obstacle_distance_m).toFixed(1)} m away`);
  }
  return parts.slice(0, 4).join(" · ") || "Scene unclear. Slow down and check.";
}

function formatSemanticSources(sources) {
  const labels = {
    model: "Model",
    tactile_color_texture: "Tactile paving color/texture",
    crossing_model: "Crossing model",
    scene_color_texture: "Scene color/texture",
    none: "None",
  };
  return sources.map((source) => labels[source] || source).join("+");
}

function glassesDescription(evidence) {
  if (!evidence) {
    return "Waiting for glasses segmentation results.";
  }
  return evidence.glasses_description || summarizeMediaEvidence(evidence);
}

function applyDetectedScene(evidence) {
  if (!evidence || !evidence.scene_type) {
    return;
  }
  const sceneType = evidence.scene_type;
  if (apiScenarioMap[sceneType]) {
    document.body.dataset.scenario = sceneType;
    scenarioButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.scenario === sceneType);
    });
  }
  if (sceneType !== lastDetectedSceneType) {
    lastDetectedSceneType = sceneType;
    speakSceneSwitch(evidence.scene_switch_message || `Switched to ${evidence.scene_label || sceneType}.`);
  }
}

function speakSceneSwitch(message) {
  if (!message || !("speechSynthesis" in window)) {
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(message);
  utterance.lang = "en-US";
  utterance.rate = 1;
  utterance.volume = 1;
  window.speechSynthesis.speak(utterance);
}

function formatRegion(region) {
  const regionLabels = {
    vegetation: "vegetation",
    tactile_paving: "tactile paving",
    crosswalk: "crosswalk",
    road_or_asphalt: "roadway/asphalt",
    walkable_pavement: "walkable pavement",
  };
  const coverage = typeof region.coverage === "number" ? ` coverage ${Math.round(region.coverage * 100)}%` : "";
  return `${regionLabels[region.label] || region.label} ${directionDisplayName(region.direction)}${coverage}`;
}

function renderAgents(activeIds, apiResults = null) {
  agentList.innerHTML = "";

  if (apiResults) {
    apiResults.forEach((result) => {
      const row = document.createElement("article");
      row.className = `agent ${result.severity === "info" ? "" : result.severity}`;
      appendAgentContent(
        row,
        result.agent_name,
        result.status,
        result.focus || ""
      );
      agentList.appendChild(row);
    });
    return;
  }

  agents.forEach((agent) => {
    const isActive = activeIds.includes(agent.id);
    const row = document.createElement("article");
    row.className = `agent ${isActive ? agent.severity : ""}`;
    appendAgentContent(row, agent.name, isActive ? agent.active : agent.normal);
    agentList.appendChild(row);
  });
}

function appendAgentContent(row, name, status, focus = "") {
  const dot = document.createElement("span");
  dot.className = "agent-dot";
  dot.setAttribute("aria-hidden", "true");

  const copy = document.createElement("div");
  copy.className = "agent-copy";

  const title = document.createElement("strong");
  title.textContent = name;

  const statusText = document.createElement("span");
  statusText.textContent = status;

  copy.append(title, statusText);
  if (focus) {
    const focusText = document.createElement("small");
    focusText.textContent = focus;
    copy.appendChild(focusText);
  }
  row.append(dot, copy);
}

function applyLocalScenario(name) {
  const scenario = scenarios[name];
  document.body.dataset.scenario = name;
  mainInstruction.textContent = scenario.title;
  secondaryInstruction.textContent = scenario.subtitle;
  glassesText.textContent = scenario.glasses;
  phoneText.textContent = scenario.phone;
  braceletText.textContent = scenario.bracelet;
  priorityText.textContent = scenario.priority;
  speechState.textContent = "Example action guidance";
  wristState.textContent = scenario.wristCue;
  descriptionState.textContent = scenario.description;
  systemStatus.textContent = "Synthetic scenario";
  dataSource.textContent = "Local example with scripted instructions and specialist states. The scene is illustrative; no sensor observations or participant measurements are used.";

  scenarioButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === name);
  });

  renderAgents(scenario.activeAgents);
}

function applyApiPlan(name, plan) {
  document.body.dataset.scenario = name;
  mainInstruction.textContent = plan.main_instruction;
  secondaryInstruction.textContent = plan.secondary_instruction;
  const audioCue = plan.spatial_audio && plan.spatial_audio[0];
  const avoidance = plan.avoidance_plan;
  glassesText.textContent = audioCue
    ? `Spatial audio: ${audioCue.azimuth_deg} degrees, ${audioCue.message}`
    : "First-person perception shared with obstacle, tactile paving, traffic light, crossing, object search and scene specialists.";
  phoneText.textContent = avoidance
    ? `Avoidance: ${avoidance.action} (${avoidance.heading_delta_deg} degrees). ${avoidance.rationale}`
    : `Relayed cloud guidance: ${plan.voice_message}`;
  const braceletCue = plan.haptics[0];
  braceletText.textContent = braceletCue
    ? `${braceletCue.pattern}: ${braceletCue.meaning}`
    : "No wrist cue selected.";
  const priorityLabels = { info: "Informational", warn: "Warning", danger: "Danger" };
  priorityText.textContent = priorityLabels[plan.priority] || "Unspecified";
  const shouldSpeak = plan.context_plan && plan.context_plan.should_speak;
  speechState.textContent = shouldSpeak === true
    ? "Speech requested"
    : shouldSpeak === false ? "Speech suppressed" : "Unspecified";
  wristState.textContent = braceletCue ? braceletCue.pattern : "None";
  descriptionState.textContent = plan.description_gate === true
    ? "Optional context available"
    : plan.description_gate === false ? "Optional context suppressed" : "Unspecified";
  const fromMedia = name === "media";
  systemStatus.textContent = fromMedia ? "Uploaded media" : "Synthetic scenario";
  dataSource.textContent = fromMedia
    ? "Uploaded media analyzed by the configured perception pipeline and legacy coordinator. Model or heuristic sources appear with the media evidence. Priority is a policy category, not a risk probability; no user cognitive load is measured."
    : "Server replay of a synthetic scenario through the legacy coordinator. Instructions and specialist states come from scripted input, not live sensors or participant measurements.";

  scenarioButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === name);
  });

  renderAgents([], plan.agent_results);
}

function summarizeMediaEvidence(evidence) {
  if (!evidence) {
    return "Media analyzed by the specialist coordinator.";
  }
  const perception = evidence.perception || {};
  const backend = evidence.vision_backend && evidence.vision_backend.active
    ? `Model: ${evidence.vision_backend.model || "Ultralytics"}`
    : "Model: heuristic fallback";
  const parts = [
    evidence.scene_label ? `Scene: ${evidence.scene_label}` : `Type: ${evidence.media_type || "media"}`,
    backend,
    evidence.scene_description || "",
    perception.obstacle_distance_m && perception.obstacle_distance_m <= 2.0 ? `Obstacle ${Number(perception.obstacle_distance_m).toFixed(1)} m away` : "",
    shouldShowTrafficLight(evidence, perception) ? `Light: ${perception.traffic_light}` : "",
    evidence.detected_texts && evidence.detected_texts.length ? `Text: ${evidence.detected_texts.slice(0, 3).join(", ")}` : "",
  ].filter(Boolean);
  return parts.slice(0, 5).join(" · ");
}

function shouldShowTrafficLight(evidence, perception) {
  const light = perception.traffic_light || evidence.traffic_light;
  return light && light !== "unknown" && (evidence.scene_type === "crossing" || light === "red" || light === "yellow");
}

async function analyzeMedia() {
  const file = mediaInput.files && mediaInput.files[0];
  if (!file) {
    mediaStatus.textContent = "Select an image or video first.";
    return;
  }
  previewSelectedMedia();

  const form = new FormData();
  let uploadFile = file;
  try {
    uploadFile = await prepareMediaUpload(file);
  } catch (error) {
    mediaStatus.textContent = `Image conversion failed: ${error.message}. Uploading the original file...`;
  }
  form.append("media", uploadFile);
  if (targetQuery.value.trim()) {
    form.append("target_query", targetQuery.value.trim());
  }

  analyzeMediaButton.disabled = true;
  mediaStatus.textContent = "Analyzing media and coordinating specialists...";

  try {
    const response = await apiFetch("/api/analyze-media", {
      method: "POST",
      body: form,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `API status ${response.status}`);
    }
    applyApiPlan("media", payload);
    glassesText.textContent = glassesDescription(payload.media_evidence);
    renderMediaEvidence(payload.media_evidence);
    applyDetectedScene(payload.media_evidence);
    mediaStatus.textContent = `Analysis complete: ${summarizeMediaEvidence(payload.media_evidence)}`;
  } catch (error) {
    mediaStatus.textContent = `Media analysis failed: ${error.message}. Check that the Python backend is running: LIBEREYE_ENABLE_STRONG_VISION=1 python -m libereye.server --port 8012`;
  } finally {
    analyzeMediaButton.disabled = false;
  }
}

async function setScenario(name) {
  lastDetectedSceneType = "";
  applyLocalScenario(name);

  try {
    const response = await apiFetch(`/api/analyze?scenario=${apiScenarioMap[name]}`);
    if (!response.ok) {
      throw new Error(`API status ${response.status}`);
    }
    const plan = await response.json();
    applyApiPlan(name, plan);
  } catch (error) {
    console.info("Using static demo data because the Python API is unavailable.", error);
  }
}

scenarioButtons.forEach((button) => {
  button.addEventListener("click", () => setScenario(button.dataset.scenario));
});

analyzeMediaButton.addEventListener("click", analyzeMedia);
mediaInput.addEventListener("change", previewSelectedMedia);

detectApiBase();
setScenario("sidewalk");
