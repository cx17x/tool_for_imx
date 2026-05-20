const form = document.getElementById("configForm");
const adminToken = document.getElementById("adminToken");
const apiStatus = document.getElementById("apiStatus");
const configPath = document.getElementById("configPath");
const resultOutput = document.getElementById("resultOutput");
const validateButton = document.getElementById("validateButton");
const applyButton = document.getElementById("applyButton");

const sectionTitles = {
  model: "Model",
  detection: "Detection",
  tracker: "Tracker",
  motion: "Motion Vector",
  video: "Video / MJPEG",
};

let schema = {};
let currentConfig = {};

function setStatus(element, label, ok) {
  element.textContent = label;
  element.classList.toggle("status-ok", ok);
  element.classList.toggle("status-waiting", !ok);
}

function showResult(payload) {
  resultOutput.textContent = JSON.stringify(payload, null, 2);
}

function getToken() {
  return sessionStorage.getItem("imx_admin_token") || "";
}

function setToken(value) {
  sessionStorage.setItem("imx_admin_token", value);
}

function fieldId(key) {
  return `field-${key}`;
}

function buildForm() {
  const sections = {};
  for (const [key, field] of Object.entries(schema)) {
    const section = field.section || "detection";
    if (!sections[section]) {
      const panel = document.createElement("section");
      panel.className = "panel";
      panel.innerHTML = `
        <div class="panel-header">
          <h2>${sectionTitles[section] || section}</h2>
        </div>
        <div class="form-grid"></div>
      `;
      sections[section] = panel.querySelector(".form-grid");
      form.appendChild(panel);
    }
    sections[section].appendChild(buildField(key, field, currentConfig[key]));
  }
}

function buildField(key, field, value) {
  const label = document.createElement("label");
  label.className = field.type === "boolean" ? "field checkbox-field" : "field";
  label.htmlFor = fieldId(key);

  if (field.type === "boolean") {
    label.innerHTML = `
      <input id="${fieldId(key)}" name="${key}" type="checkbox" ${value ? "checked" : ""}>
      <span>${field.label}</span>
    `;
    return label;
  }

  const title = document.createElement("span");
  title.textContent = field.label;
  label.appendChild(title);

  if (field.type === "select") {
    const select = document.createElement("select");
    select.id = fieldId(key);
    select.name = key;
    for (const optionValue of field.options || []) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = optionValue === value;
      select.appendChild(option);
    }
    label.appendChild(select);
    return label;
  }

  const input = document.createElement("input");
  input.id = fieldId(key);
  input.name = key;
  input.value = value ?? "";
  input.type = field.type === "string" ? "text" : "number";
  if (field.min != null) {
    input.min = String(field.min);
  }
  if (field.max != null) {
    input.max = String(field.max);
  }
  if (field.step != null) {
    input.step = String(field.step);
  }
  label.appendChild(input);
  return label;
}

function collectConfig() {
  const nextConfig = {};
  for (const [key, field] of Object.entries(schema)) {
    const input = document.getElementById(fieldId(key));
    if (field.type === "boolean") {
      nextConfig[key] = input.checked;
    } else if (field.type === "integer") {
      nextConfig[key] = Number.parseInt(input.value, 10);
    } else if (field.type === "number") {
      nextConfig[key] = Number.parseFloat(input.value);
    } else {
      nextConfig[key] = input.value;
    }
  }
  return nextConfig;
}

async function postConfig(path) {
  setToken(adminToken.value);
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": getToken(),
    },
    body: JSON.stringify({ config: collectConfig() }),
  });
  const payload = await response.json();
  showResult(payload);
  setStatus(apiStatus, payload.ok ? "ok" : "error", payload.ok);
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  currentConfig = payload.config || currentConfig;
  return payload;
}

async function loadConfig() {
  adminToken.value = getToken();
  const response = await fetch("/api/config", { cache: "no-store" });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus(apiStatus, "error", false);
    showResult(payload);
    return;
  }
  schema = payload.schema || {};
  currentConfig = payload.config || {};
  configPath.textContent = payload.config_path || "";
  form.replaceChildren();
  buildForm();
  setStatus(apiStatus, payload.token_required ? "token required" : "no token", !payload.token_required);
  showResult(payload);
}

adminToken.addEventListener("input", () => setToken(adminToken.value));
validateButton.addEventListener("click", () => {
  postConfig("/api/config/validate").catch((error) => showResult({ ok: false, error: error.message }));
});
applyButton.addEventListener("click", () => {
  applyButton.disabled = true;
  validateButton.disabled = true;
  setStatus(apiStatus, "restarting", false);
  postConfig("/api/config/apply")
    .catch((error) => showResult({ ok: false, error: error.message }))
    .finally(() => {
      applyButton.disabled = false;
      validateButton.disabled = false;
    });
});

loadConfig();
