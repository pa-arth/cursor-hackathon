const COLLECTOR = "http://127.0.0.1:8787";

const defaultState = () => ({
  recording: false,
  paused: false,
  episodeId: null,
  intent: "",
  success: null,
  stepCount: 0,
  allowlist: [],
  collectorOk: null,
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
    body: JSON.stringify(body),
  });
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
      try {
        if (msg.command === "start") {
          const intent = String(msg.intent || "").trim();
          if (!intent) throw new Error("intent required");
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
          await postJSON(`/v1/episodes/${state.episodeId}/complete`, {
            success: msg.success,
            notes: msg.notes || null,
          });
          Object.assign(state, {
            recording: false,
            paused: false,
            success: msg.success,
            lastError: null,
          });
        } else if (msg.command === "ping") {
          const res = await fetch(`${COLLECTOR}/health`);
          state.collectorOk = res.ok;
        } else if (msg.command === "sync") {
          if (msg.allowlist) state.allowlist = msg.allowlist;
        }
        await saveState(state);
        await broadcastSession(state);
        chrome.runtime.sendMessage({ type: "capture:state", state }).catch(() => {});
        sendResponse({ ok: true, state });
      } catch (err) {
        state.lastError = String(err.message || err);
        state.collectorOk = false;
        await saveState(state);
        sendResponse({ ok: false, error: state.lastError, state });
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

// Re-inject session into newly loaded tabs while recording.
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
