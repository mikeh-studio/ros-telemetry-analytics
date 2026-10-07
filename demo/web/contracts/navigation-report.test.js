import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  writeFileSync,
  rmSync,
  existsSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { resolve, join } from "node:path";
import { createHash } from "node:crypto";
import {
  validateNavigationReport,
  pairAttempts,
  MAX_REPORT_BYTES,
  MAX_REPORT_PAIRS,
} from "../src/navigationReport.js";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const localPython = resolve(root, ".venv/bin/python");
const python =
  process.env.PYTHON || (existsSync(localPython) ? localPython : "python3");
const fixture = JSON.parse(
  readFileSync(resolve(root, "examples/navigation_regression_synthetic.json")),
);

function evaluate(input, exitCode) {
  const work = mkdtempSync(join(tmpdir(), "navigation-contract-"));
  try {
    const source = join(work, "input.json");
    const output = join(work, "output");
    writeFileSync(
      source,
      input === fixture
        ? readFileSync(
            resolve(root, "examples/navigation_regression_synthetic.json"),
          )
        : JSON.stringify(input, null, 2) + "\n",
    );
    const result = spawnSync(
      python,
      [
        "-m",
        "ros_telemetry_analytics",
        "evaluate-navigation",
        "--input",
        source,
        "--output",
        output,
      ],
      { cwd: root, encoding: "utf8", timeout: 30000, maxBuffer: 1024 * 1024 },
    );
    assert.ifError(result.error);
    assert.equal(result.status, exitCode, result.stderr);
    const bytes = readFileSync(join(output, "evaluation.json"));
    assert.ok(
      bytes.length <= MAX_REPORT_BYTES,
      `CLI output exceeds viewer limit: ${bytes.length} bytes`,
    );
    return validateNavigationReport(JSON.parse(bytes));
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

test("bundled viewer example matches current CLI output exactly", () => {
  const report = evaluate(fixture, 1);
  const bundled = JSON.parse(
    readFileSync(
      new URL("../src/examples/navigation-synthetic.json", import.meta.url),
    ),
  );
  assert.deepEqual(report, bundled);
});

test("rejected baseline and colliding candidate agree in CLI and viewer", () => {
  const input = structuredClone(fixture);
  Object.assign(input.attempts[0], {
    termination: "rejected",
    elapsed_s: 0,
    ground_truth: [],
    contact_heartbeat_s: [],
    obstacle_contacts: [],
  });
  const report = evaluate(input, 1);
  assert.equal(report.status, "REGRESSION");
  assert.equal(pairAttempts(report.attempts)[0].change, "New collision");
});

test("missing attempts remain importable INVALID evidence", () => {
  const input = structuredClone(fixture);
  input.attempts.pop();
  const report = evaluate(input, 2);
  assert.equal(report.status, "INVALID");
  assert.equal(pairAttempts(report.attempts)[0].category, "Needs review");
});

test("synthetic successes remain INCONCLUSIVE", () => {
  const input = structuredClone(fixture);
  input.attempts[1].obstacle_contacts = [];
  assert.equal(evaluate(input, 3).status, "INCONCLUSIVE");
});

test("declared simulator PASS output imports without changing the decision", () => {
  // Software-contract fixture only; this does not authenticate simulator provenance.
  const input = structuredClone(fixture);
  input.evidence_kind = "simulator";
  input.scenarios = Array.from({ length: 20 }, (_, seed) => ({
    ...fixture.scenarios[0],
    scenario_id: `map-${seed}`,
    seed,
    map_sha256: createHash("sha256").update(String(seed)).digest("hex"),
  }));
  input.attempts = input.scenarios.flatMap((scenario) =>
    fixture.attempts.map((attempt) => ({
      ...attempt,
      scenario_id: scenario.scenario_id,
      seed: scenario.seed,
      run_id: `${scenario.seed}-${attempt.configuration}`,
      obstacle_contacts: [],
    })),
  );
  assert.equal(evaluate(input, 0).status, "PASS");
});

test("maximum CLI schedule fits the viewer pair and byte limits", () => {
  assert.equal(
    MAX_REPORT_PAIRS,
    10000,
    "Viewer must cover the documented CLI maximum",
  );
  const input = structuredClone(fixture);
  input.scenarios = Array.from({ length: MAX_REPORT_PAIRS }, (_, seed) => ({
    ...fixture.scenarios[0],
    seed,
  }));
  input.attempts = input.scenarios.flatMap((scenario) =>
    fixture.attempts.map((attempt) => ({
      ...attempt,
      seed: scenario.seed,
      run_id: `${scenario.seed}-${attempt.configuration}`,
    })),
  );
  const report = evaluate(input, 1);
  assert.equal(report.scheduled_pairs, MAX_REPORT_PAIRS);
  assert.equal(report.attempts.length, 2 * MAX_REPORT_PAIRS);
});
