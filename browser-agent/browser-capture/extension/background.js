const COLLECTOR = "http://127.0.0.1:8787";

const defaultState = () => ({
  recording: false,
  paused: false,
  episodeId: null,
  intent: "",
  intentSource: null,
  success: null,
  stepCount: 0,
  allowlist: [],
  collectorOk: null,
  apiKeyConfigured: null,
  lastError: null,
});

async function loadState() {
  const { captureState } = await chrome.storage.session.get("captureState");
  return { ...defaultState(), ...(captureState || {}) };
}

async function saveState(state) {
  await chrome.storage.session.set({ captureState: state });
}

async function postJSON(path, body) {
  const res = await fetch(`${COLLECTOR}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function deleteJSON(path) {
  const res = await fetch(`${COLLECTOR}${path}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function getJSON(path) {
  const res = await fetch(`${COLLECTOR}${path}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function broadcastSession(state) {
  const session = {
    recording: state.recording,
    paused: state.paused,
    episodeId: state.episodeId,
    intent: state.intent,
    allowlist: state.allowlist,
  };
  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs.map((tab) =>
      chrome.tabs.sendMessage(tab.id, { type: "capture:setSession", session }).catch(() => {})
    )
  );
}

function newEpisodeId() {
  if (crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "").slice(0, 24);
  return `ep_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

chrome.runtime.onInstalled.addListener(() => {
  if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg?.type === "capture:step") {
      const state = await loadState();
      if (!state.recording || state.paused || !state.episodeId) {
        sendResponse({ ok: false, error: "not recording" });
        return;
      }
      if (msg.episodeId !== state.episodeId) {
        sendResponse({ ok: false, error: "stale episode" });
        return;
      }
      try {
        const result = await postJSON(`/v1/episodes/${state.episodeId}/steps`, msg.step);
        state.stepCount = result.step;
        state.lastError = null;
        await saveState(state);
        chrome.runtime.sendMessage({ type: "capture:state", state }).catch(() => {});
        sendResponse({ ok: true, step: result.step });
      } catch (err) {
        state.lastError = String(err.message || err);
        await saveState(state);
        sendResponse({ ok: false, error: state.lastError });
      }
      return;
    }

    if (msg?.type === "capture:command") {
      const state = await loadState();
      let settings = null;
      try {
        if (msg.command === "start") {
          const intent = String(msg.intent || "").trim();
          const episodeId = newEpisodeId();
          let startUrl = null;
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (tab?.url) startUrl = tab.url;
          await postJSON("/v1/episodes", {
            id: episodeId,
            intent,
            start_url: startUrl,
            allowlist: msg.allowlist || [],
            source: "human_extension",
          });
          Object.assign(state, {
            recording: true,
            paused: false,
            episodeId,
            intent,
            intentSource: intent ? "human" : "pending",
            allowlist: msg.allowlist || [],
            stepCount: 0,
            success: null,
            lastError: null,
            collectorOk: true,
          });
        } else if (msg.command === "pause") {
          state.paused = true;
        } else if (msg.command === "resume") {
          state.paused = false;
        } else if (msg.command === "done") {
          if (!state.episodeId) throw new Error("no episode");
          const result = await postJSON(`/v1/episodes/${state.episodeId}/complete`, {
            success: msg.success,
            notes: msg.notes || null,
            intent: msg.intent || state.intent || "",
            suggest_intent: msg.suggest_intent !== false,
          });
          Object.assign(state, {
            recording: false,
            paused: false,
            success: msg.success,
            intent: result.intent || state.intent || "",
            intentSource: result.intent_source || null,
            lastError: result.warning || null,
          });
        } else if (msg.command === "ping") {
          const res = await getJSON("/health");
          state.collectorOk = !!res.ok;
          state.apiKeyConfigured = !!res.api_key_configured;
        } else if (msg.command === "loadSettings") {
          settings = await getJSON("/v1/settings");
          state.apiKeyConfigured = !!settings.configured;
          state.collectorOk = true;
        } else if (msg.command === "saveKey") {
          settings = await postJSON("/v1/settings/api-key", {
            api_key: msg.api_key,
            base_url: msg.base_url,
            model: msg.model,
          });
          state.apiKeyConfigured = !!settings.configured;
          state.collectorOk = true;
          state.lastError = null;
        } else if (msg.command === "clearKey") {
          settings = await deleteJSON("/v1/settings/api-key");
          state.apiKeyConfigured = false;
          state.lastError = null;
        } else if (msg.command === "sync") {
          if (msg.allowlist) state.allowlist = msg.allowlist;
        }
        await saveState(state);
        await broadcastSession(state);
        chrome.runtime.sendMessage({ type: "capture:state", state }).catch(() => {});
        sendResponse({ ok: true, state, settings });
      } catch (err) {
        state.lastError = String(err.message || err);
        if (msg.command !== "saveKey" && msg.command !== "loadSettings") {
          state.collectorOk = false;
        }
        await saveState(state);
        sendResponse({ ok: false, error: state.lastError, state, settings });
      }
      return;
    }

    if (msg?.type === "capture:getState") {
      sendResponse({ ok: true, state: await loadState() });
      return;
    }

    sendResponse({ ok: false, error: "unknown" });
  })();
  return true;
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.status !== "complete") return;
  const state = await loadState();
  if (!state.recording) return;
  chrome.tabs
    .sendMessage(tabId, {
      type: "capture:setSession",
      session: {
        recording: state.recording,
        paused: state.paused,
        episodeId: state.episodeId,
        intent: state.intent,
        allowlist: state.allowlist,
      },
    })
    .catch(() => {});
});
