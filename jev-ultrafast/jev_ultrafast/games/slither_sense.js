/** Read slither.io runtime state into a compact, decision-friendly summary. */
(() => {
  if (!window.playing || !window.slither) return null;
  const me = window.slither;
  if (me.dead_amt > 0.5) return {game: "slither.io", alive: false, nickname: me.nk || "", length: me.sct || 0};
  const DIRS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"];
  const rad2deg = (r) => ((r * 180) / Math.PI + 360) % 360;
  const octantFromDeg = (deg) => DIRS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
  const octant = (dx, dy) => octantFromDeg(rad2deg(Math.atan2(dy, dx)));
  const dist = (dx, dy) => Math.hypot(dx, dy);
  const angDiff = (a, b) => {
    let d = Math.abs(a - b) % 360;
    return d > 180 ? 360 - d : d;
  };
  const opposite = {N: "S", NE: "SW", E: "W", SE: "NW", S: "N", SW: "NE", W: "E", NW: "SE"};

  const headingDeg = rad2deg(me.wang != null ? me.wang : me.ang);
  const stickyDir = octantFromDeg(headingDeg);

  const foods = [];
  const density = Object.fromEntries(DIRS.map((d) => [d, 0]));
  const clump = Object.fromEntries(DIRS.map((d) => [d, 0]));
  let foodAlongHeading = 0;
  let massAlongHeading = 0;
  let massForward = 0, massBehind = 0, massTotal = 0;

  if (window.foods) {
    for (let i = 0; i < window.foods.length; i++) {
      const f = window.foods[i];
      if (!f) continue;
      const dx = f.xx - me.xx, dy = f.yy - me.yy;
      const d = dist(dx, dy);
      if (!Number.isFinite(d) || d < 1 || d > 3500) continue;
      const bearing = rad2deg(Math.atan2(dy, dx));
      const dir = octantFromDeg(bearing);
      const size = f.sz || f.rad || 1;
      const mass = size / (1 + d / 220);
      density[dir]++;
      clump[dir] += mass;
      foods.push({dir, dist: Math.round(d), size, mass: Math.round(mass * 100) / 100, bearing: Math.round(bearing)});
      massTotal += mass;
      const ahead = angDiff(bearing, headingDeg) <= 70;
      const behind = angDiff(bearing, headingDeg) >= 110;
      if (ahead) massForward += mass;
      if (behind) massBehind += mass;
      if (angDiff(bearing, headingDeg) <= 40) {
        foodAlongHeading++;
        massAlongHeading += mass;
      }
    }
  }
  foods.sort((a, b) => b.mass - a.mass || a.dist - b.dist);

  // Void/edge proxy: running into emptiness while food is behind you.
  const voidAhead = massTotal > 5 && massForward < massBehind * 0.35 && massAlongHeading < 3;
  const voidPressure = Object.fromEntries(DIRS.map((d) => [d, 0]));
  if (voidAhead) {
    voidPressure[stickyDir] += 1.2;
    // also penalize near-heading dirs
    const i = DIRS.indexOf(stickyDir);
    voidPressure[DIRS[(i + 7) % 8]] += 0.7;
    voidPressure[DIRS[(i + 1) % 8]] += 0.7;
  }

  const threats = [];
  const threatByDir = Object.fromEntries(DIRS.map((d) => [d, 0]));
  let nearestThreatDist = 1e9, nearestThreatDir = null;
  if (window.slithers) {
    for (let i = 0; i < window.slithers.length; i++) {
      const o = window.slithers[i];
      if (!o || o === me) continue;
      const dx = o.xx - me.xx, dy = o.yy - me.yy;
      const d = dist(dx, dy);
      if (!Number.isFinite(d) || d < 1 || d > 4500) continue;
      const dir = octant(dx, dy);
      const length = o.sct || 0;
      const pressure = (length + 4) / (1 + d / 220);
      threatByDir[dir] += pressure;
      // smear into adjacent cones — side-swipes kill small snakes
      const idx = DIRS.indexOf(dir);
      threatByDir[DIRS[(idx + 7) % 8]] += pressure * 0.45;
      threatByDir[DIRS[(idx + 1) % 8]] += pressure * 0.45;
      if (d < nearestThreatDist) {
        nearestThreatDist = d;
        nearestThreatDir = dir;
      }
      threats.push({
        dir,
        dist: Math.round(d),
        length,
        name: (o.nk || o.onk || "snake").slice(0, 16),
      });
    }
  }
  threats.sort((a, b) => a.dist - b.dist);

  const THREAT_W = 22;
  const VOID_W = 35;
  const UNSAFE_THREAT = 2.0;
  const score = {};
  for (const d of DIRS) {
    score[d] = (clump[d] || 0) - THREAT_W * (threatByDir[d] || 0) - VOID_W * (voidPressure[d] || 0);
  }

  const isUnsafe = (d) => (threatByDir[d] || 0) >= UNSAFE_THREAT || (voidPressure[d] || 0) >= 0.9;

  let bestClumpDir = "E", bestClumpMass = -1;
  for (const d of DIRS) {
    if (clump[d] > bestClumpMass) {
      bestClumpMass = clump[d];
      bestClumpDir = d;
    }
  }

  // Safest food dir: max score among SAFE directions only.
  let safest = null, safestScore = -1e9;
  for (const d of DIRS) {
    if (isUnsafe(d)) continue;
    if (score[d] > safestScore) {
      safestScore = score[d];
      safest = d;
    }
  }
  if (!safest) {
    // all unsafe — flee opposite nearest threat, else opposite sticky
    safest = opposite[nearestThreatDir || stickyDir] || "N";
  }

  const stickySafe = !isUnsafe(stickyDir);
  const stickyScore = score[stickyDir] || 0;
  let recommendDir = safest;
  if (
    stickySafe &&
    !voidAhead &&
    foodAlongHeading >= 3 &&
    stickyScore >= safestScore * 0.75
  ) {
    recommendDir = stickyDir;
  }
  // Panic: very close threat — flee opposite immediately.
  if (nearestThreatDist < 280 && nearestThreatDir) {
    const flee = opposite[nearestThreatDir];
    if (flee && !isUnsafe(flee)) recommendDir = flee;
    else recommendDir = safest;
  }

  const round = (obj) => Object.fromEntries(Object.keys(obj).map((k) => [k, Math.round((obj[k] || 0) * 10) / 10]));

  return {
    game: "slither.io",
    alive: true,
    nickname: me.nk || me.onk || "",
    length: me.sct || 0,
    heading_deg: Math.round(headingDeg),
    heading_dir: stickyDir,
    boost_speed: Math.round((me.tsp || 0) * 10) / 10,
    nearest_foods: foods.slice(0, 10).map(({dir, dist, size}) => ({dir, dist, size})),
    food_density_by_direction: density,
    clump_mass_by_direction: round(clump),
    threat_pressure_by_direction: round(threatByDir),
    void_pressure_by_direction: round(voidPressure),
    safety_score_by_direction: round(score),
    best_clump_dir: bestClumpDir,
    best_clump_mass: Math.round(bestClumpMass * 10) / 10,
    safest_food_dir: safest,
    food_along_heading: foodAlongHeading,
    mass_along_heading: Math.round(massAlongHeading * 10) / 10,
    mass_forward: Math.round(massForward * 10) / 10,
    mass_behind: Math.round(massBehind * 10) / 10,
    void_ahead: voidAhead,
    sticky_heading_dir: stickyDir,
    recommended_dir: recommendDir,
    nearest_threat_dist: nearestThreatDist < 1e8 ? Math.round(nearestThreatDist) : null,
    nearby_snakes: threats.slice(0, 8),
    food_count_nearby: foods.length,
    goal_hint:
      "ALWAYS prefer RECOMMENDED/SAFEST. NEVER choose UNSAFE. Ignore BEST_CLUMP when it conflicts with safety. If void_ahead, turn toward food mass. Flee close threats.",
  };
})()
