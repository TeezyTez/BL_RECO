const form = document.querySelector("#recognizeForm");
const fileInput = document.querySelector("#document");
const fileName = document.querySelector("#fileName");
const textInput = document.querySelector("#text");
const warnings = document.querySelector("#warnings");
const quality = document.querySelector("#quality");
const fieldGrid = document.querySelector("#fieldGrid");
const ediOutput = document.querySelector("#ediOutput");
const sampleBtn = document.querySelector("#sampleBtn");
const clearBtn = document.querySelector("#clearBtn");
const tabs = document.querySelectorAll(".tab");
const configStatus = document.querySelector("#configStatus");
const jobList = document.querySelector("#jobList");
const jobSearch = document.querySelector("#jobSearch");
const refreshJobsBtn = document.querySelector("#refreshJobsBtn");
const saveReviewBtn = document.querySelector("#saveReviewBtn");
const copyOutputBtn = document.querySelector("#copyOutputBtn");
const downloadOutputBtn = document.querySelector("#downloadOutputBtn");

let lastResult = null;
let activeTab = "edifact";
let activeJobId = "";

const labels = {
  bill_of_lading_no: "提单号",
  booking_no: "订舱号",
  shipper: "发货人",
  consignee: "收货人",
  notify_party: "通知方",
  carrier: "承运人",
  vessel: "船名",
  voyage: "航次",
  place_of_receipt: "收货地",
  port_of_loading: "装货港",
  port_of_discharge: "卸货港",
  place_of_delivery: "交货地",
  container_no: "箱号",
  seal_no: "铅封号",
  packages: "件数/包装",
  gross_weight: "毛重",
  measurement: "体积",
  freight_terms: "运费条款",
  goods_description: "货物描述",
  marks_and_nos: "唛头/标记",
  containers: "箱明细"
};

const partyFields = new Set(["shipper", "consignee", "notify_party"]);
const multiLineFields = new Set(["goods_description", "marks_and_nos"]);

const sampleText = `BILL OF LADING NO: COSU6254813900
BOOKING NO: SHABK240001
SHIPPER
NINGBO EVERLIGHT EXPORT CO., LTD.
88 PORT ROAD, NINGBO, CHINA
CONSIGNEE
GLOBAL HOME SUPPLY INC.
1200 MARKET STREET, LOS ANGELES, CA, USA
NOTIFY PARTY
GLOBAL HOME SUPPLY INC.
VESSEL / VOYAGE: COSCO SHIPPING GEMINI / 036E
CARRIER: COSCO SHIPPING LINES
PORT OF LOADING: NINGBO, CHINA
PORT OF DISCHARGE: LOS ANGELES, USA
PLACE OF DELIVERY: CHICAGO, USA
CONTAINER NO: CSLU1234567
SEAL NO: CN998877
PACKAGES: 960 CARTONS
GROSS WEIGHT: 18450 KGS
MEASUREMENT: 68.5 CBM
FREIGHT TERMS: FREIGHT PREPAID
DESCRIPTION OF GOODS
HOUSEHOLD CERAMIC TABLEWARE`;

fileInput.addEventListener("change", () => {
  syncFileName();
});

sampleBtn.addEventListener("click", () => {
  textInput.value = sampleText;
});

clearBtn.addEventListener("click", () => {
  form.reset();
  fileName.textContent = "选择 PDF 或图片";
  warnings.hidden = true;
  fieldGrid.innerHTML = "";
  quality.textContent = "等待识别";
  ediOutput.textContent = "上传或粘贴提单内容后生成 EDI。";
  lastResult = null;
  activeJobId = "";
  setResultActions(false);
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    activeTab = tab.dataset.tab;
    renderOutput();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  syncFileName();
  if (!fileInput.files.length && !textInput.value.trim()) {
    const message = "请重新选择 PDF/图片，或粘贴提单文本后再识别。";
    ediOutput.textContent = message;
    renderWarnings([message]);
    return;
  }
  ediOutput.textContent = "识别中...";
  warnings.hidden = true;
  const body = new FormData(form);
  setBusy(true);
  try {
    const payload = await requestJson("/api/recognize", { method: "POST", body });
    applyResult(payload.job || payload);
    textInput.value = payload.text || textInput.value;
    await loadJobs();
  } catch (error) {
    ediOutput.textContent = error.message;
  } finally {
    setBusy(false);
  }
});

refreshJobsBtn.addEventListener("click", () => loadJobs());
jobSearch.addEventListener("input", debounce(() => loadJobs(jobSearch.value), 250));

saveReviewBtn.addEventListener("click", async () => {
  if (!activeJobId || !lastResult) return;
  try {
    const payload = await requestJson(`/api/jobs/${activeJobId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: readEditorFields(), status: "reviewed" })
    });
    applyResult(payload);
    await loadJobs(jobSearch.value);
  } catch (error) {
    renderWarnings([error.message]);
  }
});

copyOutputBtn.addEventListener("click", async () => {
  if (!lastResult) return;
  await navigator.clipboard.writeText(currentOutputText());
  copyOutputBtn.textContent = "已复制";
  setTimeout(() => {
    copyOutputBtn.textContent = "复制";
  }, 1200);
});

downloadOutputBtn.addEventListener("click", () => {
  if (!activeJobId) return;
  const fmt = activeTab === "json" ? "json" : activeTab === "flat" ? "flat" : "edifact";
  window.location.href = `/api/jobs/${activeJobId}/export/${fmt}`;
});

async function init() {
  await loadConfig();
  await loadJobs();
}

async function loadConfig() {
  try {
    const config = await requestJson("/api/config");
    configStatus.textContent = config.vision_configured
      ? `${config.vision_provider} · ${config.vision_model || "未命名模型"}`
      : "未配置多模态";
    configStatus.classList.toggle("ok", Boolean(config.vision_configured));
  } catch {
    configStatus.textContent = "配置不可读";
  }
}

async function loadJobs(query = "") {
  const params = query ? `?q=${encodeURIComponent(query)}` : "";
  const payload = await requestJson(`/api/jobs${params}`);
  renderJobs(payload.jobs || []);
}

function renderJobs(jobs) {
  if (!jobs.length) {
    jobList.innerHTML = `<div class="empty">暂无记录</div>`;
    return;
  }
  jobList.innerHTML = "";
  jobs.forEach((job) => {
    const fields = job.fields || {};
    const title = fields.bill_of_lading_no || job.source || job.id;
    const route = [fields.port_of_loading, fields.port_of_discharge].filter(Boolean).join(" → ");
    const item = document.createElement("button");
    item.type = "button";
    item.className = `job-item ${job.id === activeJobId ? "active" : ""}`;
    item.innerHTML = `
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(route || fields.vessel || "未识别航线")}</span>
      <small>${escapeHtml(job.engine)} · ${formatDate(job.updated_at)}</small>
    `;
    item.addEventListener("click", () => openJob(job.id));
    jobList.appendChild(item);
  });
}

async function openJob(jobId) {
  const job = await requestJson(`/api/jobs/${jobId}`);
  applyResult(job);
  await loadJobs(jobSearch.value);
}

function applyResult(result) {
  lastResult = normalizeResult(result);
  activeJobId = lastResult.id || lastResult.job?.id || "";
  renderFields(lastResult.fields);
  renderQuality(lastResult.quality, lastResult.engine, lastResult.status);
  renderWarnings(lastResult.warnings);
  renderOutput();
  setResultActions(Boolean(lastResult));
}

function normalizeResult(result) {
  if (result.job) return { ...result.job, text: result.text, source: result.source, engine: result.engine };
  return result;
}

function renderFields(fields) {
  fieldGrid.innerHTML = "";
  Object.entries(labels).forEach(([key, label]) => {
    const raw = fields?.[key];
    const card = document.createElement("label");
    card.className = "field";
    if (key === "containers" || key === "marks_and_nos" || key === "goods_description") card.classList.add("wide");
    card.dataset.field = key;
    card.innerHTML = `<strong>${label}</strong>${editorFor(key, raw)}`;
    fieldGrid.appendChild(card);
  });
}

function editorFor(key, value) {
  if (partyFields.has(key)) {
    return `
      <input data-field="${key}.name" value="${escapeAttribute(value?.name || "")}" placeholder="名称">
      <textarea data-field="${key}.address" rows="2" placeholder="地址">${escapeHtml(value?.address || "")}</textarea>
    `;
  }
  if (key === "containers") {
    return `<textarea data-field="${key}" rows="5" placeholder="箱明细 JSON">${escapeHtml(JSON.stringify(value || [], null, 2))}</textarea>`;
  }
  if (multiLineFields.has(key)) {
    return `<textarea data-field="${key}" rows="3">${escapeHtml(value || "")}</textarea>`;
  }
  return `<input data-field="${key}" value="${escapeAttribute(value || "")}">`;
}

function readEditorFields() {
  const fields = {};
  Object.keys(labels).forEach((key) => {
    if (partyFields.has(key)) {
      fields[key] = {
        name: readInput(`${key}.name`),
        address: readInput(`${key}.address`)
      };
    } else if (key === "containers") {
      const raw = readInput(key).trim();
      try {
        fields[key] = raw ? JSON.parse(raw) : [];
      } catch {
        throw new Error("箱明细必须是有效 JSON。");
      }
    } else {
      fields[key] = readInput(key);
    }
  });
  return fields;
}

function readInput(name) {
  return fieldGrid.querySelector(`[data-field="${CSS.escape(name)}"]`)?.value || "";
}

function renderQuality(stats, engine = "", status = "") {
  const percent = Math.round((stats?.score || 0) * 100);
  const engineText = engine?.endsWith("_vision") ? "Mimo 多模态" : "规则";
  quality.textContent = `${percent}% · ${engineText}${status === "reviewed" ? " · 已校对" : ""}`;
}

function renderWarnings(items) {
  const normalized = normalizeWarnings(items);
  if (!normalized.length) {
    warnings.hidden = true;
    warnings.textContent = "";
    return;
  }
  warnings.hidden = false;
  warnings.innerHTML = normalized.map(escapeHtml).join("<br>");
}

function normalizeWarnings(items) {
  if (typeof items === "string") return items.trim() ? [items.trim()] : [];
  if (!Array.isArray(items)) return [];
  if (items.length && items.every((item) => typeof item === "string" && item.length === 1)) {
    const joined = items.join("").trim();
    return joined ? [joined] : [];
  }
  return items.map((item) => String(item || "").trim()).filter(Boolean);
}

function renderOutput() {
  if (!lastResult) return;
  ediOutput.textContent = currentOutputText();
}

function currentOutputText() {
  if (!lastResult) return "";
  if (activeTab === "json") return JSON.stringify(lastResult.fields, null, 2);
  if (activeTab === "flat") return lastResult.edi?.flat || "";
  return lastResult.edi?.edifact_ifcsum || "";
}

function setBusy(isBusy) {
  form.querySelectorAll("button, input, textarea").forEach((item) => {
    if (item.id !== "clearBtn") item.disabled = isBusy;
  });
}

function setResultActions(enabled) {
  saveReviewBtn.disabled = !enabled;
  copyOutputBtn.disabled = !enabled;
  downloadOutputBtn.disabled = !enabled || !activeJobId;
}

function syncFileName() {
  const selected = fileInput.files[0]?.name || "";
  fileName.textContent = selected || "选择 PDF 或图片";
  fileName.classList.toggle("empty", !selected);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let payload = {};
  if (contentType.includes("application/json")) {
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error("服务返回了无效 JSON，请稍后重试。");
    }
  } else {
    const message = htmlToText(text) || `服务返回了 ${response.status} 错误。`;
    throw new Error(message);
  }
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

function htmlToText(value) {
  return String(value || "")
    .replace(new RegExp("<style[\\s\\S]*?</style>", "gi"), "")
    .replace(new RegExp("<script[\\s\\S]*?</script>", "gi"), "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 500);
}

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function debounce(fn, delay) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("\n", "&#10;");
}

init();
syncFileName();
