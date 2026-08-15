const $ = (id) => document.getElementById(id);

const KEY_FIELDS = [
  "MODAL_TOKEN_ID",
  "MODAL_TOKEN_SECRET",
  "HF_TOKEN",
  "GITHUB_TOKEN",
  "CIVITAI_TOKEN",
];

let catalog = null;
let catalogs = [];
const uploadsByParam = {};

function splitPrompts(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.includes("\n---")) {
    return trimmed
      .split(/\n---\n/)
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return trimmed
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || path);
  return data;
}

function appendLog(node, line) {
  node.textContent = `${node.textContent}${line}\n`.slice(-8000);
  node.scrollTop = node.scrollHeight;
}

async function pollJob(jobId, logNode) {
  let cursor = 0;
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    const logs = job.logs || [];
    logs.slice(cursor).forEach((line) => appendLog(logNode, line));
    cursor = logs.length;
    if (job.status === "ok") return job;
    if (job.status === "error") throw new Error(job.error || "job failed");
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
}

function setPill(runtime) {
  const pill = $("status-pill");
  if (runtime.serve_running) {
    pill.textContent = "GPU 运行中";
    pill.dataset.state = "ready";
  } else if (runtime.deployed || (runtime.gpu_mode === "deploy" && runtime.base_url)) {
    pill.textContent = "已部署";
    pill.dataset.state = "ready";
  } else if (runtime.base_url) {
    pill.textContent = "已有地址";
    pill.dataset.state = "ready";
  } else {
    pill.textContent = "未连接";
    pill.dataset.state = "off";
  }
}

function hasPromptParam() {
  return (catalog?.params || []).some((item) => item.id === "prompt" || item.bind === "prompt");
}

function imageSpecs() {
  return (catalog?.params || []).filter((item) => item.type === "image");
}

function renderParams(spec, defaults) {
  const root = $("params");
  root.innerHTML = "";
  spec
    .filter((item) => item.type !== "image" && item.id !== "prompt" && item.id !== "negative")
    .forEach((item) => {
      const label = document.createElement("label");
      label.textContent = item.title || item.id;
      const input = document.createElement("input");
      input.id = `param-${item.id}`;
      input.type = item.type === "text" ? "text" : "number";
      if (item.minimum != null) input.min = item.minimum;
      if (item.maximum != null) input.max = item.maximum;
      if (item.step != null) input.step = item.step;
      input.value = defaults[item.id] ?? item.default ?? "";
      if (item.help) input.title = item.help;
      label.appendChild(input);
      root.appendChild(label);
    });
  const neg = spec.find((item) => item.id === "negative");
  if (neg) {
    const label = document.createElement("label");
    label.textContent = neg.title;
    label.style.gridColumn = "1 / -1";
    const input = document.createElement("input");
    input.id = "param-negative";
    input.type = "text";
    input.value = defaults.negative || "";
    label.appendChild(input);
    root.appendChild(label);
  }
}

function thumbFor(file, url) {
  const wrap = document.createElement("div");
  if (url) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = file.name;
    wrap.appendChild(img);
  }
  const name = document.createElement("span");
  name.textContent = file.name;
  wrap.appendChild(name);
  return wrap;
}

function renderUploads() {
  const root = $("uploads");
  const specs = imageSpecs();
  root.hidden = specs.length === 0;
  root.innerHTML = "";
  specs.forEach((spec) => {
    uploadsByParam[spec.id] = uploadsByParam[spec.id] || [];
    const zone = document.createElement("label");
    zone.className = "dropzone";
    zone.innerHTML = `<strong>${spec.title || spec.id}</strong>${spec.help || "点击或拖入图片，可多张"}`;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp,image/gif";
    input.multiple = true;
    input.hidden = true;
    const thumbs = document.createElement("div");
    thumbs.className = "thumbs";
    const redraw = () => {
      thumbs.innerHTML = "";
      uploadsByParam[spec.id].forEach((item) => thumbs.appendChild(thumbFor(item.file, item.url)));
    };
    const addFiles = async (fileList) => {
      for (const file of fileList) {
        const stored = await fetch("/api/uploads", {
          method: "POST",
          headers: { "X-Filename": file.name },
          body: file,
        }).then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "upload failed");
          return data;
        });
        uploadsByParam[spec.id].push({
          file,
          name: stored.name,
          url: stored.url,
        });
      }
      redraw();
    };
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (event) => event.preventDefault());
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      addFiles(event.dataTransfer.files).catch((error) => appendLog($("job-log"), String(error)));
    });
    input.addEventListener("change", () => {
      addFiles(input.files).catch((error) => appendLog($("job-log"), String(error)));
      input.value = "";
    });
    zone.appendChild(input);
    zone.appendChild(thumbs);
    root.appendChild(zone);
    redraw();
  });
}

function readParams() {
  const params = {};
  document.querySelectorAll("[id^='param-']").forEach((input) => {
    const key = input.id.slice("param-".length);
    params[key] = input.type === "number" ? Number(input.value) : input.value;
  });
  return params;
}

function collectedImages() {
  const images = {};
  imageSpecs().forEach((spec) => {
    const names = (uploadsByParam[spec.id] || []).map((item) => item.name);
    if (names.length) images[spec.id] = names;
  });
  return images;
}

function addCards(results) {
  const gallery = $("gallery");
  results.forEach((item) => {
    const files = item.files || item.images || [];
    files.forEach((src) => {
      const card = document.createElement("article");
      card.className = "card";
      const lower = String(src).toLowerCase();
      if (/\.(png|jpe?g|webp|gif)(\?|$)/.test(lower)) {
        const img = document.createElement("img");
        img.src = src;
        img.alt = "";
        card.appendChild(img);
      } else {
        const link = document.createElement("a");
        link.href = src;
        link.textContent = src.split("/").pop();
        link.style.display = "block";
        link.style.padding = "24px 12px";
        card.appendChild(link);
      }
      const p = document.createElement("p");
      p.textContent = `${item.prompt || item.image || ""}\nseed ${item.seed ?? "-"}`;
      card.appendChild(p);
      gallery.prepend(card);
    });
  });
}

function gpuLabel(recipe, name) {
  if (name === recipe.gpu && name === recipe.gpu_inference) return name;
  if (name === recipe.gpu) return `${name}（测试）`;
  if (name === recipe.gpu_inference) return `${name}（正式推理）`;
  return name;
}

function applyCatalog(recipe) {
  catalog = recipe;
  Object.keys(uploadsByParam).forEach((key) => delete uploadsByParam[key]);
  $("recipe-chip").textContent = recipe.title;
  $("recipe-heading").textContent = recipe.title;
  $("recipe-summary").textContent = recipe.summary || "";
  $("gpu").innerHTML = (recipe.gpu_choices || [recipe.gpu])
    .map((name) => `<option value="${name}">${gpuLabel(recipe, name)}</option>`)
    .join("");
  $("gpu").value = recipe.gpu;
  $("prompt-wrap").hidden = !hasPromptParam();
  renderParams(recipe.params || [], recipe.defaults || {});
  renderUploads();
}

async function selectCatalog(id) {
  const recipe = await api(`/api/catalogs/${id}`);
  applyCatalog(recipe);
  await api("/api/catalog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalog: id }),
  });
}

async function refreshStatus() {
  const data = await api("/api/status");
  const masked = data.keys.masked || {};
  KEY_FIELDS.forEach((key) => {
    const field = $(key);
    if (field && !field.value) field.placeholder = masked[key] || field.placeholder;
  });
  $("key-state").textContent = data.keys.uses_cli_auth
    ? "Modal：使用本机 CLI 登录。HF：" + (data.keys.has_hf ? "已配置" : "未配置")
    : "Modal token 已保存。HF：" + (data.keys.has_hf ? "已配置" : "未配置");
  if (data.runtime.base_url) $("base-url").value = data.runtime.base_url;
  if (data.runtime.gpu && catalog && (catalog.gpu_choices || []).includes(data.runtime.gpu)) {
    $("gpu").value = data.runtime.gpu;
  }
  setPill(data.runtime);
  return data;
}

async function boot() {
  const list = await api("/api/catalogs");
  catalogs = list.catalogs || [];
  const status = await refreshStatus();
  const preferred =
    status.runtime.catalog ||
    list.default ||
    "z-image";
  const selected =
    catalogs.find((item) => item.id === preferred) ||
    catalogs.find((item) => item.id === "z-image") ||
    catalogs[0];
  $("recipe").innerHTML = catalogs
    .map((item) => `<option value="${item.id}">${item.title}</option>`)
    .join("");
  if (!selected) return;
  $("recipe").value = selected.id;
  await selectCatalog(selected.id);
  await refreshStatus();
}

$("recipe").onchange = async () => {
  try {
    await selectCatalog($("recipe").value);
  } catch (error) {
    appendLog($("job-log"), String(error.message || error));
  }
};

$("save-keys").onclick = async () => {
  const body = {};
  KEY_FIELDS.forEach((key) => {
    const value = $(key).value.trim();
    if (value) body[key] = value;
  });
  await api("/api/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  KEY_FIELDS.forEach((key) => ($(key).value = ""));
  await refreshStatus();
};

$("save-url").onclick = async () => {
  await api("/api/base-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: $("base-url").value.trim() }),
  });
  await refreshStatus();
};

async function runAction(button, path, extra, logNode) {
  button.disabled = true;
  try {
    const payload = { catalog: catalog.id, gpu: $("gpu").value, ...extra };
    const started = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const job = await pollJob(started.job_id, logNode);
    if (job.result?.base_url) $("base-url").value = job.result.base_url;
    await refreshStatus();
    return job;
  } finally {
    button.disabled = false;
  }
}

$("hydrate").onclick = () => runAction($("hydrate"), "/api/hydrate", {}, $("runtime-log"));
$("serve").onclick = () => runAction($("serve"), "/api/serve", {}, $("runtime-log"));
$("stop").onclick = async () => {
  await api("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await refreshStatus();
};

$("generate").onclick = async () => {
  const prompts = hasPromptParam() ? splitPrompts($("prompts").value) : [];
  const images = collectedImages();
  const imageCount = Object.values(images).reduce((sum, list) => sum + list.length, 0);
  $("gen-count").textContent = hasPromptParam()
    ? `${prompts.length} 条`
    : `${imageCount} 张`;
  if (hasPromptParam() && !prompts.length) return;
  if (imageSpecs().some((spec) => spec.required) && !imageCount) {
    appendLog($("job-log"), "请先上传输入图");
    return;
  }
  $("generate").disabled = true;
  $("job-log").textContent = "";
  try {
    const started = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        catalog: catalog.id,
        base_url: $("base-url").value.trim(),
        prompts,
        images,
        params: readParams(),
        keep_gpu: $("keep-gpu").checked,
      }),
    });
    const job = await pollJob(started.job_id, $("job-log"));
    addCards(job.result?.results || []);
  } catch (error) {
    appendLog($("job-log"), String(error.message || error));
  } finally {
    $("generate").disabled = false;
    await refreshStatus();
  }
};

boot().catch((error) => appendLog($("job-log"), String(error)));
