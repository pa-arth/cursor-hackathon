const $ = (id) => document.getElementById(id);

function parseAllowlist(raw) {
  return String(raw || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

function render(state) {
  const recording = !!state.recording;
  const paused = !!state.paused;
  $("intent").value = state.intent || $("intent").value;
  $("intent").disabled = recording;
  $("allowlist").disabled = recording;
  $("start").disabled = recording;
  $("pause").disabled = !recording;
  $("pause").textContent = paused ? "Resume" : "Pause";
  $("done").disabled = !recording;
  $("episode").textContent = state.episodeId || "—";
  $("steps").textContent = String(state.stepCount || 0);

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

  if (state.lastError) {
    $("error").hidden = false;
    $("error").textContent = state.lastError;
  } else {
    $("error").hidden = true;
  }
}

async function command(payload) {
  const res = await chrome.runtime.sendMessage({ type: "capture:command", ...payload });
  if (res?.state) render(res.state);
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

$("done").addEventListener("click", () =>
  command({
    command: "done",
    success: $("success").checked,
  })
);

$("ping").addEventListener("click", () => command({ command: "ping" }));

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "capture:state" && msg.state) render(msg.state);
});

(async () => {
  const { state } = await chrome.runtime.sendMessage({ type: "capture:getState" });
  if (state?.allowlist?.length) $("allowlist").value = state.allowlist.join(", ");
  if (state) render(state);
  await command({ command: "ping" });
})();
