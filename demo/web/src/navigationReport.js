const text = (value, limit) =>
  typeof value === "string" && value.trim().length > 0 && value.length <= limit;

const outcomes = [
  "success",
  "collision",
  "timeout",
  "rejected",
  "crash",
  "harness_error",
  "goal_not_verified",
  "invalid",
];
export function validateNavigationReport(value) {
  const fail = () => {
    throw new Error(
      "Choose an evaluation.json produced by evaluate-navigation.",
    );
  };
  if (
    !value ||
    value.schema_version !== 1 ||
    !text(value.suite_id, 256) ||
    !["PASS", "REGRESSION", "INCONCLUSIVE", "INVALID"].includes(value.status) ||
    !["synthetic", "simulator"].includes(value.evidence_kind) ||
    !Array.isArray(value.reasons) ||
    !value.reasons.every((r) => text(r, 4096)) ||
    !Array.isArray(value.attempts) ||
    !value.attempts.length ||
    value.attempts.length > 10000 ||
    !Number.isSafeInteger(value.scheduled_pairs) ||
    value.scheduled_pairs < 1 ||
    value.scheduled_pairs > 5000
  )
    fail();
  if (
    value.independent_maps != null &&
    (!Number.isInteger(value.independent_maps) || value.independent_maps < 0)
  )
    fail();
  if (value.evidence_kind === "synthetic" && value.status === "PASS") fail();
  for (const row of value.attempts) {
    if (
      !row ||
      !text(row.scenario_id, 256) ||
      !Number.isSafeInteger(row.seed) ||
      row.seed < 0 ||
      !["baseline", "candidate"].includes(row.configuration) ||
      !outcomes.includes(row.outcome) ||
      ![null, true, false].includes(row.collision) ||
      !(row.reason == null || text(row.reason, 4096))
    )
      fail();
    for (const key of ["completion_s", "path_length_m"]) {
      if (
        row[key] !== null &&
        !(
          typeof row[key] === "number" &&
          Number.isFinite(row[key]) &&
          row[key] >= 0 &&
          row[key] <= Number.MAX_SAFE_INTEGER
        )
      )
        fail();
    }
  }
  const pairs = pairAttempts(value.attempts);
  if (
    pairs.length !== value.scheduled_pairs ||
    pairs.some((p) => !p.baseline || !p.candidate)
  )
    fail();
  if (value.independent_maps > pairs.length) fail();
  for (const row of value.attempts) {
    if (
      row.outcome === "success" &&
      (row.collision !== false || !(row.completion_s > 0))
    )
      fail();
    if (row.outcome === "collision" && row.collision !== true) fail();
    if (row.outcome !== "success" && row.completion_s !== null) fail();
  }
  if (
    value.status === "PASS" &&
    value.attempts.some((r) => r.outcome === "invalid")
  )
    fail();
  for (const key of ["success_delta", "time_ratio"]) {
    const metric = value[key];
    if (
      metric !== null &&
      (!metric ||
        !Number.isFinite(metric.estimate) ||
        !Array.isArray(metric.ci95) ||
        metric.ci95.length !== 2 ||
        !metric.ci95.every(Number.isFinite) ||
        metric.ci95[0] > metric.ci95[1])
    )
      fail();
  }
  if (
    value.success_delta &&
    [value.success_delta.estimate, ...value.success_delta.ci95].some(
      (n) => n < -1 || n > 1,
    )
  )
    fail();
  if (
    value.time_ratio &&
    [value.time_ratio.estimate, ...value.time_ratio.ci95].some((n) => n <= 0)
  )
    fail();
  return value;
}

export const categories = [
  "All",
  "Regressions",
  "Improvements",
  "Unchanged",
  "Needs review",
];
export function pairAttempts(attempts) {
  const groups = new Map();
  for (const row of attempts) {
    const key = JSON.stringify([row.scenario_id, row.seed]);
    if (!groups.has(key))
      groups.set(key, { key, scenario: row.scenario_id, seed: row.seed });
    if (groups.get(key)[row.configuration])
      throw new Error("Duplicate scenario/configuration in report.");
    groups.get(key)[row.configuration] = row;
  }
  return [...groups.values()]
    .map((pair) => {
      const b = pair.baseline,
        c = pair.candidate;
      let category = "Needs review",
        change = "Evidence needs review",
        rule = "One or both attempts has missing or invalid evidence.";
      if (
        b &&
        c &&
        !["invalid", "harness_error"].includes(b.outcome) &&
        !["invalid", "harness_error"].includes(c.outcome)
      ) {
        if (c.collision === true && b.collision === false) {
          category = "Regressions";
          change = "New collision";
          rule =
            "Any new candidate collision in a previously collision-free pair.";
        } else if (b.outcome === "success" && c.outcome !== "success") {
          category = "Regressions";
          change = "Lost success";
          rule = "Baseline succeeded; candidate did not.";
        } else if (b.outcome !== "success" && c.outcome === "success") {
          category = "Improvements";
          change = "New success";
          rule = "Candidate succeeded where baseline did not.";
        } else if (b.outcome === c.outcome) {
          category = "Unchanged";
          change = "Same outcome";
          rule = "Both attempts have the same outcome; efficiency may differ.";
        } else {
          change = "Different failures";
          rule =
            "Different failure outcomes require inspection; no automatic ranking.";
        }
      }
      return { ...pair, category, change, rule };
    })
    .sort(
      (a, b) =>
        categories.indexOf(a.category) - categories.indexOf(b.category) ||
        a.scenario.localeCompare(b.scenario) ||
        a.seed - b.seed,
    );
}
