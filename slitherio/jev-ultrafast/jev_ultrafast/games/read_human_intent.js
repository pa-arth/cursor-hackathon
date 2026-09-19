(() => {
  const human = window.__slitherHuman;
  if (!human) return null;
  return {
    dir: human.dir || null,
    boosting: !!human.boosting,
    x: human.x,
    y: human.y,
    age_ms: human.ts ? Date.now() - human.ts : null,
  };
})()
