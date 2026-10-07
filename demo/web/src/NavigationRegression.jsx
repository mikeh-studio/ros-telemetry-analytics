import { useEffect, useRef, useState } from "react";
import example from "./examples/navigation-synthetic.json";
import "./NavigationRegression.css";

import {
  validateNavigationReport,
  pairAttempts,
  categories,
} from "./navigationReport";

const number = (v, unit = "") =>
  v == null ? "Unavailable" : `${v.toFixed(2)}${unit}`;
const label = (v) => (v ? v.replaceAll("_", " ") : "Missing attempt");
const contact = (row) =>
  row?.collision == null
    ? "Unknown"
    : row.collision
      ? "Observed"
      : "None observed";
const delta = (b, c, unit) =>
  b == null || c == null
    ? "Unavailable"
    : `${c - b > 0 ? "+" : ""}${(c - b).toFixed(2)}${unit}`;

export default function NavigationRegression() {
  const [report, setReport] = useState(example);
  const [source, setSource] = useState("Bundled example");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("All");
  const [selected, setSelected] = useState(null);
  const [lastSelected, setLastSelected] = useState(null);
  const importVersion = useRef(0);
  useEffect(
    () => () => {
      importVersion.current += 1;
    },
    [],
  );
  const fileInput = useRef(null),
    heading = useRef(null),
    evaluation = useRef(null);
  const returnTarget = useRef(null),
    scrollPosition = useRef(0);
  const pairs = pairAttempts(report.attempts);
  const visible = pairs.filter(
    (p) => filter === "All" || p.category === filter,
  );
  const active = pairs.find((p) => p.key === selected);
  const position = visible.findIndex((p) => p.key === selected);
  const regressions = pairs.filter((p) => p.category === "Regressions");
  const collisions = pairs.filter((p) => p.change === "New collision").length;
  const valid = report.attempts.filter(
    (r) => !["invalid", "harness_error"].includes(r.outcome),
  ).length;
  const collisionDecision = report.status === "REGRESSION" && collisions > 0;
  const successes = (role) =>
    report.attempts.filter(
      (r) => r.configuration === role && r.outcome === "success",
    ).length;
  const matched = pairs.filter(
    (p) =>
      p.baseline?.outcome === "success" && p.candidate?.outcome === "success",
  ).length;
  useEffect(() => {
    if (selected) {
      setLastSelected(selected);
      heading.current?.focus();
    }
  }, [selected]);
  function open(pair, target) {
    if (!selected) {
      scrollPosition.current = window.scrollY;
      returnTarget.current = target;
    }
    setSelected(pair.key);
  }
  function back() {
    setSelected(null);
    requestAnimationFrame(() => {
      returnTarget.current?.focus({ preventScroll: true });
      window.scrollTo?.(0, scrollPosition.current);
    });
  }
  async function load(event) {
    const input = event.target;
    const file = input.files?.[0];
    const version = ++importVersion.current;
    input.value = "";
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024)
        throw new Error("Choose a report smaller than 10 MB.");
      const next = validateNavigationReport(JSON.parse(await file.text()));
      if (version !== importVersion.current) return;
      setReport(next);
      setSource(file.name);
      setSelected(null);
      setLastSelected(null);
      setFilter("All");
      setError("");
      setNotice(`Loaded ${next.suite_id}.`);
    } catch (err) {
      if (version !== importVersion.current) return;
      setError(
        err instanceof SyntaxError
          ? "This file is not valid JSON."
          : err.message,
      );
    }
  }
  function review(event) {
    if (regressions.length) {
      setFilter("Regressions");
      open(regressions[0], event.currentTarget);
    } else {
      evaluation.current.open = true;
      evaluation.current.querySelector("summary").focus();
    }
  }
  const baseline = active?.baseline,
    candidate = active?.candidate;
  return (
    <div
      className={`navigation-regression ${active ? "nav-inspecting" : ""}`}
      onKeyDown={(e) => {
        if (e.key === "Escape" && active) back();
      }}
    >
      <header className="nav-heading">
        <div>
          <p className="nav-eyebrow">SAVED EVALUATION</p>
          <h2>Navigation comparison</h2>
          <div className="nav-source">
            <span>{report.suite_id}</span>
            <span className="nav-badge">
              {report.evidence_kind === "synthetic"
                ? "Synthetic example"
                : "Simulator · declared"}
            </span>
          </div>
        </div>
        <button onClick={() => fileInput.current.click()}>
          Import comparison
        </button>
        <input
          ref={fileInput}
          hidden
          aria-label="Load navigation evaluation"
          type="file"
          accept=".json,application/json"
          onChange={load}
        />
      </header>
      <p className="nav-announcement" role="status">
        {notice}
      </p>
      {error && (
        <p role="alert" className="nav-error">
          {error} The previous report is still displayed.
        </p>
      )}
      <section className="nav-overview" aria-label="Comparison summary">
        <div className={`nav-decision nav-${report.status.toLowerCase()}`}>
          <div>
            <span className="nav-eyebrow">BASELINE → CANDIDATE</span>
            <h3>
              {
                {
                  REGRESSION: "Regression detected",
                  PASS: "Suite gates passed",
                  INVALID: "Evidence incomplete",
                  INCONCLUSIVE: "More evidence needed",
                }[report.status]
              }
            </h3>
            <p>
              {collisionDecision
                ? `${collisions} of ${pairs.length} scenario/seed pairs introduced a candidate collision.`
                : report.reasons.join(" ")}
            </p>
            <p className="nav-rule">
              {collisionDecision
                ? "Rule: any new paired collision requires investigation."
                : `Evaluator decision: ${report.status}. Pair labels below are descriptive.`}
            </p>
          </div>
          <button className="nav-primary" onClick={review}>
            {regressions.length
              ? `Review ${regressions.length} regression${regressions.length === 1 ? "" : "s"}`
              : "Review comparison metrics"}
            <span aria-hidden="true"> →</span>
          </button>
        </div>
        <p className="nav-context">
          {report.evidence_kind === "synthetic"
            ? "Synthetic evidence tests the evaluator; it does not measure robot performance."
            : "Saved decision; simulator provenance is declared by the file, not authenticated."}{" "}
          Configuration names and revisions are not included in this report.
        </p>
        <div className="nav-metrics">
          <article>
            <span>Successful attempts</span>
            <strong>
              {successes("baseline")} / {pairs.length} <span>→</span>{" "}
              {successes("candidate")} / {pairs.length}
            </strong>
            <small>Baseline → candidate</small>
          </article>
          <article>
            <span>Valid scoring evidence</span>
            <strong>
              {valid} / {pairs.length * 2}
            </strong>
            <small>Includes every scheduled attempt</small>
          </article>
          <article>
            <span>Completion-time ratio</span>
            <strong>
              {report.time_ratio
                ? number(report.time_ratio.estimate, "×")
                : "Not comparable"}
            </strong>
            <small>{matched} pairs where both succeeded</small>
          </article>
          <article>
            <span>Independent maps</span>
            <strong>{report.independent_maps ?? "Unavailable"}</strong>
            <small>{pairs.length} scheduled scenario/seed pairs</small>
          </article>
        </div>
      </section>
      <div className="nav-results">
        <section className="nav-list" aria-label="Scenario comparisons">
          <div className="nav-section-heading">
            <h3>Scenario comparisons</h3>
            <span>
              {visible.length} of {pairs.length}
            </span>
          </div>
          <div className="nav-filters" aria-label="Filter scenarios">
            {categories.map((name) => (
              <button
                key={name}
                aria-pressed={filter === name}
                onClick={() => {
                  setFilter(name);
                  setSelected(null);
                }}
              >
                {name}{" "}
                <span>
                  {name === "All"
                    ? pairs.length
                    : pairs.filter((p) => p.category === name).length}
                </span>
              </button>
            ))}
          </div>
          <div className="nav-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Scenario / seed</th>
                  <th>Baseline</th>
                  <th>Candidate</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((pair) => (
                  <tr
                    key={pair.key}
                    className={
                      (selected || lastSelected) === pair.key
                        ? "nav-selected"
                        : ""
                    }
                  >
                    <td>
                      <button
                        aria-label={`Inspect ${pair.scenario}, seed ${pair.seed}`}
                        aria-pressed={(selected || lastSelected) === pair.key}
                        onClick={(e) => open(pair, e.currentTarget)}
                      >
                        {pair.scenario}
                        <small>Seed {pair.seed}</small>
                      </button>
                    </td>
                    <td>{label(pair.baseline?.outcome)}</td>
                    <td>{label(pair.candidate?.outcome)}</td>
                    <td>
                      <span
                        className={
                          pair.category === "Regressions" ? "nav-negative" : ""
                        }
                      >
                        {pair.change}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!visible.length && (
            <p className="nav-empty">
              No scenarios in this filter. Choose All to see the full
              comparison.
            </p>
          )}
        </section>
        {active && (
          <section className="nav-detail" aria-label="Paired scenario evidence">
            <button className="nav-back" onClick={back}>
              ← Back to comparison
            </button>
            <div className="nav-section-heading">
              <div>
                <p className="nav-eyebrow">
                  PAIRED EVIDENCE · SEED {active.seed}
                </p>
                <h3 ref={heading} tabIndex={-1}>
                  {active.scenario}
                </h3>
              </div>
              <span className="nav-badge">
                {position + 1} / {visible.length}
              </span>
            </div>
            <div className="nav-finding">
              <strong>{active.change}</strong>
              <p>{active.rule}</p>
            </div>
            <table className="nav-evidence-table">
              <thead>
                <tr>
                  <th>Evidence</th>
                  <th>Baseline</th>
                  <th>Candidate</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>Outcome</th>
                  <td>{label(baseline?.outcome)}</td>
                  <td>{label(candidate?.outcome)}</td>
                </tr>
                <tr>
                  <th>Completion</th>
                  <td>{number(baseline?.completion_s, " s")}</td>
                  <td>{number(candidate?.completion_s, " s")}</td>
                </tr>
                <tr>
                  <th>Path length</th>
                  <td>{number(baseline?.path_length_m, " m")}</td>
                  <td>{number(candidate?.path_length_m, " m")}</td>
                </tr>
                <tr>
                  <th>Obstacle contact</th>
                  <td>{contact(baseline)}</td>
                  <td>{contact(candidate)}</td>
                </tr>
                <tr>
                  <th>Reported reason</th>
                  <td>{baseline?.reason || "Not supplied"}</td>
                  <td>{candidate?.reason || "Not supplied"}</td>
                </tr>
              </tbody>
            </table>
            <p className="nav-deltas">
              Candidate − baseline: time{" "}
              {delta(baseline?.completion_s, candidate?.completion_s, " s")} ·
              path{" "}
              {delta(baseline?.path_length_m, candidate?.path_length_m, " m")}
            </p>
            <div className="nav-missing">
              <strong>Not in this report</strong>
              <p>
                Contact timestamps, trajectories and termination details are
                unavailable. These results identify the outcome, not the cause
                or location of a collision.
              </p>
            </div>
            <details>
              <summary>Raw pair evidence</summary>
              <pre>{JSON.stringify({ baseline, candidate }, null, 2)}</pre>
            </details>
            <div className="nav-paging">
              <button
                disabled={position <= 0}
                onClick={() => setSelected(visible[position - 1].key)}
              >
                ← Previous
              </button>
              <button
                disabled={position >= visible.length - 1}
                onClick={() => setSelected(visible[position + 1].key)}
              >
                Next →
              </button>
            </div>
          </section>
        )}
      </div>
      <details className="nav-method" ref={evaluation}>
        <summary>
          Evaluation details <span>Policy, uncertainty and source</span>
        </summary>
        <p>
          Source: {source}. Imported files stay in this browser tab and are not
          retained after reload.
        </p>
        <p>
          Success difference:{" "}
          {report.success_delta
            ? `${(report.success_delta.estimate * 100).toFixed(1)} percentage points; 95% interval ${report.success_delta.ci95.map((n) => (n * 100).toFixed(1)).join(" to ")}.`
            : "Unavailable."}{" "}
          Maps are weighted equally. Time ratios use only paired successes.
        </p>
        <p>
          Intervals describe this frozen suite, not unseen failures. Minimum map
          count:{" "}
          {Number.isInteger(report.policy?.min_maps)
            ? report.policy.min_maps
            : "not supplied"}
          . Small suites cannot establish general performance.
        </p>
        <ul>
          {report.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
        <p>
          Live mission capture and trajectory inspection are not connected yet.
        </p>
      </details>
    </div>
  );
}
