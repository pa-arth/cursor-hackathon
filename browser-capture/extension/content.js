(() => {
  if (window.__browserCaptureInstalled) return;
  window.__browserCaptureInstalled = true;

  let session = { recording: false, paused: false, episodeId: null, intent: "", allowlist: [] };
  let pendingFill = null;
  let pendingSelect = null;
  let lastScrollY = window.scrollY;
  let scrollTimer = null;
  let stepQueue = Promise.resolve();

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "capture:setSession") {
      session = { ...session, ...msg.session };
      sendResponse({ ok: true });
      return true;
    }
    if (msg?.type === "capture:getStatus") {
      sendResponse({ ok: true, session, url: location.href });
      return true;
    }
    return false;
  });

  function ruleHost(rule) {
    const r = String(rule || "").trim().toLowerCase();
    if (!r) return "";
    try {
      if (r.includes("://")) return new URL(r).hostname;
    } catch (_) {}
    // Strip paths / query if pasted without scheme.
    return r.split("/")[0].split("?")[0];
  }

  function hostAllowed() {
    if (!session.allowlist || !session.allowlist.length) return true;
    const host = location.hostname.toLowerCase();
    return session.allowlist.some((rule) => {
      const allowed = ruleHost(rule);
      if (!allowed) return false;
      return host === allowed || host.endsWith("." + allowed) || allowed.endsWith("." + host);
    });
  }

  function active() {
    return session.recording && !session.paused && session.episodeId && hostAllowed();
  }

  function enqueue(step) {
    stepQueue = stepQueue
      .then(() =>
        chrome.runtime.sendMessage({
          type: "capture:step",
          episodeId: session.episodeId,
          step,
        })
      )
      .catch((err) => console.warn("[browser-capture]", err));
  }

  function recordMapped(gesture, observation, action, extra = {}) {
    enqueue({
      ts: new Date().toISOString(),
      url: location.href,
      mapped: true,
      gesture,
      observation: slimObservation(observation),
      action: action
        ? {
            id: action.id,
            kind: action.kind,
            label: action.label,
            node: action.node,
            role: action.role,
            value: action.value,
            text: extra.text,
            delta: action.delta,
          }
        : null,
      ...extra,
    });
  }

  function recordUnmapped(gesture, detail) {
    enqueue({
      ts: new Date().toISOString(),
      url: location.href,
      mapped: false,
      gesture,
      observation: null,
      action: null,
      detail,
    });
  }

  document.addEventListener(
    "pointerdown",
    (event) => {
      if (!active() || event.button !== 0) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("select,input,textarea,[contenteditable='true']")) return;

      const observation = observePage();
      const nodeId = nodeIdFor(target);
      const action = pickAction(observation, nodeId, "click");
      if (action) recordMapped("click", observation, action);
      else recordUnmapped("click", { tag: target.tagName });
    },
    true
  );

  document.addEventListener(
    "focusin",
    (event) => {
      if (!active()) return;
      const el = event.target;
      if (!(el instanceof Element)) return;
      const observation = observePage();
      const nodeId = nodeIdFor(el);
      if (el.tagName === "SELECT") {
        pendingFill = null;
        pendingSelect = { observation, nodeId };
        return;
      }
      pendingSelect = null;
      const action = pickAction(observation, nodeId, "fill");
      if (!action || action.kind !== "fill") {
        pendingFill = null;
        return;
      }
      pendingFill = {
        observation,
        action,
        startValue: "value" in el ? String(el.value) : el.innerText.trim(),
      };
    },
    true
  );

  function commitFill(el) {
    if (!active() || !pendingFill) return;
    const text = "value" in el ? String(el.value) : el.innerText.trim();
    if (text === pendingFill.startValue) {
      pendingFill = null;
      return;
    }
    recordMapped("fill", pendingFill.observation, pendingFill.action, { text });
    pendingFill = null;
  }

  document.addEventListener(
    "change",
    (event) => {
      if (!active()) return;
      const el = event.target;
      if (el instanceof HTMLSelectElement) {
        // Use pre-change observation: selected option is absent after change.
        const observation = pendingSelect?.observation || observePage();
        const nodeId = pendingSelect?.nodeId ?? nodeIdFor(el);
        const action = pickAction(observation, nodeId, "select", el.value);
        if (action) recordMapped("select", observation, action, { text: el.value });
        else recordUnmapped("select", { value: el.value });
        pendingSelect = null;
        return;
      }
      if (el instanceof Element) commitFill(el);
    },
    true
  );

  document.addEventListener(
    "focusout",
    (event) => {
      if (!active()) return;
      const el = event.target;
      if (el instanceof Element) commitFill(el);
    },
    true
  );

  window.addEventListener(
    "scroll",
    () => {
      if (!active()) return;
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        const y = window.scrollY;
        const delta = y - lastScrollY;
        lastScrollY = y;
        if (Math.abs(delta) < 80) return;
        const observation = observePage();
        const kind = delta > 0 ? "scroll_down" : "scroll_up";
        const action = observation.actions.find((a) => a.id === kind);
        if (action) recordMapped("scroll", observation, action);
      }, 280);
    },
    { passive: true }
  );

  // Keep lastScrollY fresh after programmatic / user scrolls while idle.
})();
