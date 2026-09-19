/** Capture the human player's mouse aim + boost for gold FT labels. */
(() => {
  if (window.__slitherHumanInstalled) return "ok";
  window.__slitherHumanInstalled = true;
  const DIRS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"];
  const state = { x: null, y: null, boosting: false, dir: null, ts: 0 };
  window.__slitherHuman = state;

  const updateAim = (clientX, clientY) => {
    state.x = clientX;
    state.y = clientY;
    state.ts = Date.now();
    const dx = clientX - innerWidth / 2;
    const dy = clientY - innerHeight / 2;
    if (!Number.isFinite(dx) || !Number.isFinite(dy) || Math.hypot(dx, dy) < 12) return;
    const deg = (((Math.atan2(dy, dx) * 180) / Math.PI) + 360) % 360;
    state.dir = DIRS[Math.round(deg / 45) % 8];
  };

  const onMove = (event) => updateAim(event.clientX, event.clientY);
  window.addEventListener("pointermove", onMove, true);
  window.addEventListener("mousemove", onMove, true);
  window.addEventListener("pointerdown", () => { state.boosting = true; }, true);
  window.addEventListener("pointerup", () => { state.boosting = false; }, true);
  window.addEventListener("mousedown", () => { state.boosting = true; }, true);
  window.addEventListener("mouseup", () => { state.boosting = false; }, true);
  window.addEventListener(
    "keydown",
    (event) => {
      if (event.code === "Space") state.boosting = true;
    },
    true,
  );
  window.addEventListener(
    "keyup",
    (event) => {
      if (event.code === "Space") state.boosting = false;
    },
    true,
  );
  return "ok";
})()
