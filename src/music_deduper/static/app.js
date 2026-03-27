/* ================================================================
   Music Deduplication — Frontend application logic
   Vanilla JS, no framework. Talks to the FastAPI backend.
   ================================================================ */

// ---- Application state ----

const state = {
  taskId: "",
  groups: [],
  stats: {
    total_tracks: 0,
    total_groups: 0,
    total_duplicates: 0,
    total_reclaimable_display: "0 B",
  },
  allArtists: [],
  pollingHandle: null,
  selectedRoot: "",
  selectedFolderPath: "",
  previewOnly: false,
  backupDir: "",
  rules: [
    { key: "metadata_complete", label: "信息更完整优先", enabled: true },
    { key: "higher_bitrate", label: "码率更高优先", enabled: true },
    { key: "has_cover", label: "带封面优先", enabled: true },
    { key: "larger_file", label: "文件更大优先", enabled: false },
    { key: "shorter_path", label: "路径更短优先", enabled: false },
  ],
};

// ---- Cached DOM references ----

const $ = (selector) => document.querySelector(selector);

const elements = {
  rootSelect: $("#rootSelect"),
  chooseFolderButton: $("#chooseFolderButton"),
  folderInput: $("#folderInput"),
  ruleList: $("#ruleList"),
  previewToggle: $("#previewToggle"),
  backupDirInput: $("#backupDirInput"),
  scanButton: $("#scanButton"),
  stopButton: $("#stopButton"),
  progressText: $("#progressText"),
  progressCount: $("#progressCount"),
  progressFill: $("#progressFill"),
  scanSummary: $("#scanSummary"),
  totalAudioStat: $("#totalAudioStat"),
  duplicateGroupsStat: $("#duplicateGroupsStat"),
  filesToCleanStat: $("#filesToCleanStat"),
  reclaimableStat: $("#reclaimableStat"),
  searchInput: $("#searchInput"),
  artistFilter: $("#artistFilter"),
  resortButton: $("#resortButton"),
  exportButton: $("#exportButton"),
  resultsEmpty: $("#resultsEmpty"),
  resultsList: $("#resultsList"),
  logToggle: $("#logToggle"),
  logContent: $("#logContent"),
  scanLog: $("#scanLog"),
  executeButton: $("#executeButton"),
  executeModal: $("#executeModal"),
  modalBody: $("#modalBody"),
  cancelExecuteButton: $("#cancelExecuteButton"),
  confirmExecuteButton: $("#confirmExecuteButton"),
  groupTemplate: $("#groupTemplate"),
  trackComparisonTemplate: $("#trackComparisonTemplate"),
};

// ---- API helper ----

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `${response.status} ${response.statusText}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  // Blob for file downloads (e.g. export)
  return response.blob();
}

// ---- Initialization ----

function init() {
  bindEvents();
  renderRules();
  loadRoots();
  loadGroups();
}

function bindEvents() {
  elements.chooseFolderButton.addEventListener("click", () =>
    elements.folderInput.click()
  );
  elements.folderInput.addEventListener("change", onChooseFolder);
  elements.previewToggle.addEventListener("change", () => {
    state.previewOnly = elements.previewToggle.checked;
  });
  elements.backupDirInput.addEventListener("input", () => {
    state.backupDir = elements.backupDirInput.value.trim();
  });
  elements.scanButton.addEventListener("click", startScan);
  elements.stopButton.addEventListener("click", stopScan);
  elements.searchInput.addEventListener("input", loadGroups);
  elements.artistFilter.addEventListener("change", loadGroups);
  elements.resortButton.addEventListener("click", onResortGroups);
  elements.exportButton.addEventListener("click", exportReport);
  elements.executeButton.addEventListener("click", openExecuteModal);
  elements.cancelExecuteButton.addEventListener("click", closeExecuteModal);
  elements.confirmExecuteButton.addEventListener("click", executeDedupe);
  elements.logToggle.addEventListener("click", toggleLogPanel);

  // Close modal on backdrop click
  const backdrop = $(".modal-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", closeExecuteModal);
  }
}

// ---- Load drive roots ----

async function loadRoots() {
  try {
    // Actual server returns a plain list of strings
    const roots = await api("/api/roots");
    const rootList = Array.isArray(roots) ? roots : [];

    elements.rootSelect.innerHTML = "";
    rootList.forEach((root) => {
      const option = document.createElement("option");
      option.value = root;
      option.textContent = root;
      elements.rootSelect.appendChild(option);
    });

    if (rootList.length > 0) {
      state.selectedRoot = rootList[0];
      elements.rootSelect.value = state.selectedRoot;
    }
  } catch (err) {
    appendLog("加载盘符失败: " + err.message);
  }

  elements.rootSelect.addEventListener("change", () => {
    state.selectedRoot = elements.rootSelect.value;
    state.selectedFolderPath = "";
  });
}

// ---- Folder chooser (webkitdirectory) ----

function onChooseFolder(event) {
  const files = Array.from(event.target.files || []);
  if (files.length === 0) return;

  const first = files[0];
  const relative = first.webkitRelativePath || first.name;
  const topLevel = relative.split("/")[0];
  state.selectedFolderPath = topLevel;

  elements.rootSelect.innerHTML = "";
  const option = document.createElement("option");
  option.value = topLevel;
  option.textContent = topLevel;
  elements.rootSelect.appendChild(option);
  elements.rootSelect.value = topLevel;
}

// ---- Rule rendering ----

function renderRules() {
  elements.ruleList.innerHTML = "";

  state.rules.forEach((rule, index) => {
    const item = document.createElement("div");
    item.className = "rule-item";

    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = rule.enabled;
    checkbox.dataset.action = "toggle";
    checkbox.dataset.index = index;
    const text = document.createElement("span");
    text.textContent = `${index + 1}. ${rule.label}`;
    label.appendChild(checkbox);
    label.appendChild(text);

    const actions = document.createElement("div");
    actions.className = "rule-actions";

    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "button button-secondary";
    upBtn.dataset.action = "up";
    upBtn.dataset.index = index;
    upBtn.textContent = "上移";

    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "button button-secondary";
    downBtn.dataset.action = "down";
    downBtn.dataset.index = index;
    downBtn.textContent = "下移";

    actions.appendChild(upBtn);
    actions.appendChild(downBtn);

    const header = document.createElement("div");
    header.className = "rule-header";
    header.appendChild(label);
    header.appendChild(actions);

    item.appendChild(header);
    elements.ruleList.appendChild(item);
  });

  // Bind events on rule controls
  elements.ruleList.querySelectorAll("[data-action]").forEach((node) => {
    if (node.type === "checkbox") {
      node.addEventListener("change", onRuleAction);
    } else {
      node.addEventListener("click", onRuleAction);
    }
  });
}

function onRuleAction(event) {
  const action = event.currentTarget.dataset.action;
  const index = Number(event.currentTarget.dataset.index);

  if (action === "toggle") {
    state.rules[index].enabled = event.currentTarget.checked;
    return;
  }
  if (action === "up" && index > 0) {
    [state.rules[index - 1], state.rules[index]] = [
      state.rules[index],
      state.rules[index - 1],
    ];
  }
  if (action === "down" && index < state.rules.length - 1) {
    [state.rules[index + 1], state.rules[index]] = [
      state.rules[index],
      state.rules[index + 1],
    ];
  }
  renderRules();
}

// ---- Scan lifecycle ----

async function startScan() {
  const selectedPath = elements.rootSelect.value.trim();
  if (!selectedPath) {
    alert("请选择扫描目录");
    return;
  }

  try {
    // Actual server uses query param: POST /api/scan?root=...
    const payload = await api(
      `/api/scan?root=${encodeURIComponent(selectedPath)}`,
      { method: "POST" }
    );

    state.taskId = payload.task_id;
    elements.progressText.textContent = "扫描中";
    elements.progressCount.textContent = "0";
    elements.progressFill.style.width = "8%";
    elements.scanButton.disabled = true;
    appendLog(`开始扫描: ${selectedPath}`);
    startPolling();
  } catch (err) {
    appendLog("启动扫描失败: " + err.message);
    elements.scanButton.disabled = false;
  }
}

function startPolling() {
  stopPolling();
  state.pollingHandle = window.setInterval(async () => {
    if (!state.taskId) return;

    try {
      const payload = await api(`/api/scan/${state.taskId}/status`);

      // Actual server returns flat fields, not nested progress object
      updateProgress(
        payload.progress_message || "",
        payload.processed_files || 0,
        payload.groups_found || 0
      );
      renderLog(payload.log || []);

      if (payload.status === "done" || payload.status === "stopped") {
        stopPolling();
        elements.scanButton.disabled = false;
        const summary =
          payload.status === "stopped"
            ? "扫描已停止。"
            : `扫描结束，共识别 ${state.stats.total_tracks} 首音频，发现 ${state.stats.total_groups} 组重复。`;
        elements.scanSummary.textContent = summary;
        await loadGroups();
      }

      if (payload.status === "error") {
        stopPolling();
        elements.scanButton.disabled = false;
        appendLog("扫描失败: " + (payload.error || "unknown error"));
        elements.progressText.textContent = "扫描失败";
      }
    } catch (err) {
      // Network error during polling — don't crash, just log
      console.error("Polling error:", err);
    }
  }, 1000);
}

function stopPolling() {
  if (state.pollingHandle) {
    window.clearInterval(state.pollingHandle);
    state.pollingHandle = null;
  }
}

async function stopScan() {
  if (!state.taskId) return;
  try {
    await api(`/api/scan/${state.taskId}/stop`, { method: "POST" });
    appendLog("已请求停止扫描。");
  } catch (err) {
    appendLog("停止请求失败: " + err.message);
  }
}

function updateProgress(message, processedFiles, groupsFound) {
  elements.progressText.textContent = message || "扫描中";
  elements.progressCount.textContent = `${processedFiles} 首音频`;
  // Use processed files to estimate progress (cap at 95% until done)
  const width = Math.min(95, 8 + processedFiles * 0.5);
  elements.progressFill.style.width = `${width}%`;
}

// ---- Load & render groups ----

async function loadGroups() {
  try {
    const search = elements.searchInput.value.trim();
    const artist = elements.artistFilter.value.trim();
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (artist) params.set("artist", artist);
    const qs = params.toString();
    const payload = await api(`/api/groups${qs ? "?" + qs : ""}`);

    state.groups = payload.groups || [];
    // Actual server stats field names
    state.stats = {
      total_tracks: payload.stats.total_tracks || 0,
      total_groups: payload.stats.total_groups || 0,
      total_duplicates: payload.stats.total_duplicates || 0,
      total_reclaimable_display: payload.stats.total_reclaimable_display || "0 B",
    };

    // Collect unique artists from all groups for the filter dropdown
    collectArtors();

    renderStats();
    renderArtistFilter();
    renderGroups();
  } catch (err) {
    console.error("loadGroups error:", err);
  }
}

function collectArtors() {
  const artistSet = new Set();
  state.groups.forEach((group) => {
    (group.tracks || []).forEach((track) => {
      const name = track.artist && track.artist.trim() ? track.artist.trim() : null;
      if (name) artistSet.add(name);
    });
  });
  state.allArtists = Array.from(artistSet).sort();
}

function renderStats() {
  elements.totalAudioStat.textContent = String(state.stats.total_tracks);
  elements.duplicateGroupsStat.textContent = String(state.stats.total_groups);
  elements.filesToCleanStat.textContent = String(state.stats.total_duplicates);
  elements.reclaimableStat.textContent = state.stats.total_reclaimable_display;
}

function renderArtistFilter() {
  const currentValue = elements.artistFilter.value;
  elements.artistFilter.innerHTML = '<option value="">全部歌手</option>';
  state.allArtists.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    if (name === currentValue) option.selected = true;
    elements.artistFilter.appendChild(option);
  });
}

function renderGroups() {
  elements.resultsList.innerHTML = "";
  elements.resultsEmpty.hidden = state.groups.length > 0;

  state.groups.forEach((group) => {
    const template = elements.groupTemplate.content;
    const fragment = template.cloneNode(true);

    const card = fragment.querySelector(".group-card");
    const summaryButton = fragment.querySelector(".group-summary");
    const title = fragment.querySelector(".group-title");
    const meta = fragment.querySelector(".group-meta");
    const reclaim = fragment.querySelector(".group-reclaim");
    const details = fragment.querySelector(".group-details");

    title.textContent = group.key;
    const dupCount = (group.duplicate_tracks || []).length;
    meta.textContent = `保留 1 首，重复 ${dupCount} 首`;
    // Actual server uses reclaimable_display
    reclaim.textContent = group.reclaimable_display || "0 B";

    summaryButton.addEventListener("click", () => {
      const isHidden = details.hasAttribute("hidden");
      if (isHidden) {
        details.removeAttribute("hidden");
        renderGroupDetails(group, details);
      } else {
        details.setAttribute("hidden", "");
        details.innerHTML = "";
      }
    });

    card.dataset.groupId = group.id;
    elements.resultsList.appendChild(fragment);
  });
}

// ---- Group details: side-by-side comparison ----

function renderGroupDetails(group, container) {
  container.innerHTML = "";

  const keepTrack = group.keep_track;
  const duplicateTracks = group.duplicate_tracks || [];

  // For each duplicate track, show a comparison pair
  if (duplicateTracks.length > 0) {
    duplicateTracks.forEach((dupTrack) => {
      const fragment = elements.trackComparisonTemplate.content.cloneNode(true);

      const keepCard = fragment.querySelector(".track-card-keep");
      const dupCard = fragment.querySelector(".track-card-duplicate");
      const keepDetails = keepCard.querySelector(".track-details");
      const dupDetails = dupCard.querySelector(".track-details");
      const keepButton = keepCard.querySelector(".switch-keep");
      const dupButton = dupCard.querySelector(".switch-keep");

      fillTrackDetails(keepDetails, keepTrack);
      fillTrackDetails(dupDetails, dupTrack);

      // Switch keep: clicking the duplicate button keeps the duplicate instead
      dupButton.dataset.path = dupTrack.path;
      dupButton.dataset.groupId = group.id;
      dupButton.addEventListener("click", onSwitchKeep);

      // Hide the keep button (already keeping this track)
      keepButton.style.display = "none";

      container.appendChild(fragment);
    });
  } else {
    // No duplicates — just show the keep track
    container.innerHTML =
      '<p class="empty-state" style="padding:16px">该分组无重复文件。</p>';
  }
}

function fillTrackDetails(container, track) {
  const rows = [
    ["标题", track.title || "(空)"],
    ["歌手", track.artist || "(空)"],
    ["专辑", track.album || "(空)"],
    ["码率", track.bitrate_kbps ? `${track.bitrate_kbps} kbps` : "-"],
    [
      "时长",
      track.duration_seconds ? formatDuration(track.duration_seconds) : "-",
    ],
    ["封面", track.has_cover ? "有" : "无"],
    ["年份", track.year || "-"],
    ["流派", track.genre || "-"],
    ["轨道", track.track_number || "-"],
    ["格式", track.format_info || track.metadata_source || "-"],
    ["路径", track.relative_path || track.path || "-"],
  ];

  container.innerHTML = rows
    .map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`)
    .join("");
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---- Switch keep track ----

async function onSwitchKeep(event) {
  const groupId = event.currentTarget.dataset.groupId;
  const trackPath = event.currentTarget.dataset.path;

  try {
    // Actual server uses query param: PUT /api/groups/{id}/keep?path=...
    await api(
      `/api/groups/${encodeURIComponent(groupId)}/keep?path=${encodeURIComponent(trackPath)}`,
      { method: "PUT" }
    );
    await loadGroups();
  } catch (err) {
    console.error("onSwitchKeep error:", err);
    appendLog("切换保留失败: " + err.message);
  }
}

// ---- Resort groups ----

function onResortGroups() {
  state.groups.sort(
    (a, b) => (b.reclaimable_bytes || 0) - (a.reclaimable_bytes || 0)
  );
  renderGroups();
}

// ---- Export report ----

async function exportReport() {
  try {
    const blob = await api("/api/export");
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "dedup-report.json";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  } catch (err) {
    appendLog("导出报告失败: " + err.message);
  }
}

// ---- Execute modal ----

function openExecuteModal() {
  if (state.previewOnly) {
    alert("当前处于仅预览模式，不会执行移动。");
    return;
  }

  if (state.groups.length === 0) {
    alert("没有可处理的重复分组。");
    return;
  }

  const duplicateCount = state.groups.reduce(
    (sum, g) => sum + (g.duplicate_tracks || []).length,
    0
  );
  const backupDir = elements.backupDirInput.value.trim() || "默认备份目录";
  elements.modalBody.textContent = `将处理 ${state.groups.length} 个重复分组（共 ${duplicateCount} 个重复文件），移动到 ${backupDir}。此操作不可撤销。`;
  elements.executeModal.classList.add("visible");
}

function closeExecuteModal() {
  elements.executeModal.classList.remove("visible");
}

async function executeDedupe() {
  try {
    // Actual server takes no body
    const payload = await api("/api/execute", { method: "POST" });

    closeExecuteModal();

    const moved = payload.moved || 0;
    const backupDir = payload.backup_dir || "未知";
    const errors = payload.errors || [];

    appendLog(
      `执行去重完成，移动 ${moved} 个文件到 ${backupDir}`
    );

    if (errors.length > 0) {
      errors.forEach((e) => appendLog("错误: " + e));
    }

    await loadGroups();
  } catch (err) {
    closeExecuteModal();
    appendLog("执行去重失败: " + err.message);
  }
}

// ---- Log panel ----

function toggleLogPanel() {
  const expanded =
    elements.logToggle.getAttribute("aria-expanded") === "true";
  elements.logToggle.setAttribute("aria-expanded", String(!expanded));
  elements.logContent.hidden = expanded;
}

function appendLog(message) {
  const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const line = `[${ts}] ${message}`;
  const existing = elements.scanLog.textContent;
  elements.scanLog.textContent = existing ? existing + "\n" + line : line;
  // Auto-scroll to bottom
  elements.scanLog.scrollTop = elements.scanLog.scrollHeight;

  // Auto-open log panel if hidden
  if (elements.logContent.hidden) {
    elements.logContent.hidden = false;
    elements.logToggle.setAttribute("aria-expanded", "true");
  }
}

function renderLog(logLines) {
  if (!logLines || logLines.length === 0) return;
  elements.scanLog.textContent = logLines.join("\n");
  elements.scanLog.scrollTop = elements.scanLog.scrollHeight;
}

// ---- Bootstrap ----

document.addEventListener("DOMContentLoaded", init);
