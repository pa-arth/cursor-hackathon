const $ = (id) => document.getElementById(id);

function ruleHost(rule) {
  const r = String(rule || "").trim().toLowerCase();
  if (!r) return "";
  try {
    if (r.includes("://")) return new URL(r).hostname;
  } catch (_) {}
  return r.split("/")[0].split("?")[0];
}

function parseAllowlist(raw) {
  return String(raw || "")
    .split(",")
    .map(ruleHost)
    .filter(Boolean);
}

function render(state) {
  const recording = !!state.recording;
  const paused = !!state.paused;
  if (state.intent) $("intent").value = state.intent;
  $("allowlist").disabled = recording;
  $("start").disabled = recording;
  $("pause").disabled = !recording;
  $("pause").textContent = paused ? "Resume" : "Pause";
  $("done").disabled = !recording;
  $("done").textContent = recording ? "Done · suggest intent" : "Done";
  $("episode").textContent = state.episodeId || "—";
  $("steps").textContent = String(state.stepCount || 0);
  $("intentSource").textContent = state.intentSource || "—";

  const rec = $("recState");
  if (!recording) {
    rec.textContent = "idle";
    rec.className = "pill muted";
  } else if (paused) {
    rec.textContent = "paused";
    rec.className = "pill muted";
  } else {
    rec.textContent = "recording";
    rec.className = "pill live";
  }

  const col = $("collector");
  if (state.collectorOk === true) {
    col.textContent = "collector ok";
    col.className = "pill ok";
  } else if (state.collectorOk === false) {
    col.textContent = "collector down";
    col.className = "pill bad";
  } else {
    col.textContent = "collector…";
    col.className = "pill muted";
  }

  const key = $("keyState");
  if (state.apiKeyConfigured) {
    key.textContent = "api key ok";
    key.className = "pill ok";
  } else {
    key.textContent = "no api key";
    key.className = "pill muted";
  }

  if (state.lastError) {
    $("error").hidden = false;
    $("error").textContent = state.lastError;
  } else {
    $("error").hidden = true;
  }
}

function renderSettings(settings) {
  if (!settings) return;
  if (settings.base_url) $("baseUrl").value = settings.base_url;
  if (settings.model) $("model").value = settings.model;
  $("keyHint").textContent = settings.configured
    ? `Stored via ${settings.backend}${settings.hint ? ` · ${settings.hint}` : ""}`
    : "No key saved yet";
}

async function command(payload) {
  const res = await chrome.runtime.sendMessage({ type: "capture:command", ...payload });
  if (res?.state) render(res.state);
  if (res?.settings) renderSettings(res.settings);
  if (!res?.ok && res?.error) {
    $("error").hidden = false;
    $("error").textContent = res.error;
  }
  return res;
}

$("start").addEventListener("click", () =>
  command({
    command: "start",
    intent: $("intent").value,
    allowlist: parseAllowlist($("allowlist").value),
  })
);

$("pause").addEventListener("click", async () => {
  const { state } = await chrome.runtime.sendMessage({ type: "capture:getState" });
  await command({ command: state?.paused ? "resume" : "pause" });
});

$("done").addEventListener("click", async () => {
  $("done").disabled = true;
  $("done").textContent = "Suggesting…";
  const res = await command({
    command: "done",
    success: $("success").checked,
    intent: $("intent").value,
    suggest_intent: true,
  });
  if (res?.state?.intent) $("intent").value = res.state.intent;
  if (res?.ok) {
    $("error").hidden = true;
  }
});

$("saveKey").addEventListener("click", () =>
  command({
    command: "saveKey",
    api_key: $("apiKey").value,
    base_url: $("baseUrl").value,
    model: $("model").value,
  }).then((res) => {
    if (res?.ok) $("apiKey").value = "";
  })
);

$("clearKey").addEventListener("click", () => command({ command: "clearKey" }));

$("ping").addEventListener("click", () => command({ command: "ping" }));

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "capture:state" && msg.state) render(msg.state);
});

(async () => {
  const { state } = await chrome.runtime.sendMessage({ type: "capture:getState" });
  if (state?.allowlist?.length) $("allowlist").value = state.allowlist.join(", ");
  if (state?.intent) $("intent").value = state.intent;
  if (state) render(state);
  await command({ command: "ping" });
  await command({ command: "loadSettings" });
})();
