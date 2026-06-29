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

let lastResult = null;
let activeTab = "edifact";

const labels = {
  booking_no: "订舱号",
  bill_of_lading_no: "提单号",
  shipper: "发货人",
  consignee: "收货人",
  notify_party: "通知方",
  carrier: "承运人",
  vessel: "船名",
  voyage: "航次",
  port_of_loading: "装货港",
  port_of_discharge: "卸货港",
  place_of_delivery: "交货地",
  container_no: "箱号",
  seal_no: "铅封号",
  packages: "件数/包装",
  gross_weight: "毛重",
  measurement: "体积",
  freight_terms: "运费条款",
  goods_description: "货物描述"
};

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
  fileName.textContent = fileInput.files[0]?.name || "选择 PDF 或图片";
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
  ediOutput.textContent = "识别中...";
  warnings.hidden = true;

  const body = new FormData(form);
  try {
    const response = await fetch("/api/recognize", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "识别失败");
    lastResult = payload;
    renderFields(payload.fields);
    renderQuality(payload.quality);
    renderWarnings(payload.warnings);
    renderOutput();
  } catch (error) {
    ediOutput.textContent = error.message;
  }
});

function renderFields(fields) {
  fieldGrid.innerHTML = "";
  Object.entries(labels).forEach(([key, label]) => {
    const raw = fields[key];
    const value = formatValue(raw);
    const card = document.createElement("div");
    card.className = "field";
    card.innerHTML = `<strong>${label}</strong><span>${escapeHtml(value || "未识别")}</span>`;
    fieldGrid.appendChild(card);
  });
}

function renderQuality(stats) {
  const percent = Math.round((stats?.score || 0) * 100);
  quality.textContent = `${percent}% 完整度`;
}

function renderWarnings(items) {
  if (!items?.length) {
    warnings.hidden = true;
    warnings.textContent = "";
    return;
  }
  warnings.hidden = false;
  warnings.innerHTML = items.map(escapeHtml).join("<br>");
}

function renderOutput() {
  if (!lastResult) return;
  if (activeTab === "json") {
    ediOutput.textContent = JSON.stringify(lastResult.fields, null, 2);
  } else if (activeTab === "flat") {
    ediOutput.textContent = lastResult.edi.flat;
  } else {
    ediOutput.textContent = lastResult.edi.edifact_ifcsum;
  }
}

function formatValue(value) {
  if (!value) return "";
  if (typeof value === "object") {
    return [value.name, value.address].filter(Boolean).join("\n");
  }
  return String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
