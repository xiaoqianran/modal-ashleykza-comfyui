const $ = (id) => document.getElementById(id);

const KEY_FIELDS = [
  "MODAL_TOKEN_ID",
  "MODAL_TOKEN_SECRET",
  "HF_TOKEN",
  "GITHUB_TOKEN",
  "CIVITAI_TOKEN",
];

let catalog = null;

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
  if (runtime.serve_running || runtime.base_url) {
    pill.textContent = runtime.serve_running ? "GPU 运行中" : "已有地址";
    pill.dataset.state = "ready";
  } else {
    pill.textContent = "未连接";
    pill.dataset.state = "off";
  }
}

function renderParams(spec, defaults) {
  const root = $("params");
  root.innerHTML = "";
  spec
    .filter((item) => item.id !== "prompt" && item.id !== "negative")
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

function readParams() {
  const params = {};
  document.querySelectorAll("[id^='param-']").forEach((input) => {
    const key = input.id.slice("param-".length);
    params[key] = input.type === "number" ? Number(input.value) : input.value;
  });
  return params;
}

function addCards(results) {
  const gallery = $("gallery");
  results.forEach((item) => {
      (item.images || []).forEach((src) => {
        const card = document.createElement("article");
        card.className = "card";
        const img = document.createElement("img");
        img.src = src;
        img.alt = "";
        const p = document.createElement("p");
        p.textContent = `${item.prompt}\nseed ${item.seed}`;
        card.appendChild(img);
        card.appendChild(p);
        gallery.prepend(card);
      });
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
  if (data.runtime.gpu) $("gpu").value = data.runtime.gpu;
  setPill(data.runtime);
  return data;
}

async function boot() {
  const list = await api("/api/catalogs");
  const recipe = (list.catalogs || [])[0];
  if (!recipe) return;
  $("recipe-chip").textContent = recipe.title;
  catalog = await api(`/api/catalogs/${recipe.id}`);
  $("gpu").innerHTML = (catalog.gpu_choices || [catalog.gpu])
    .map((name) => `<option value="${name}">${name}</option>`)
    .join("");
  $("gpu").value = catalog.gpu;
  renderParams(catalog.params || [], catalog.defaults || {});
  await refreshStatus();
}

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
  const prompts = splitPrompts($("prompts").value);
  $("gen-count").textContent = `${prompts.length} 条`;
  if (!prompts.length) return;
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
