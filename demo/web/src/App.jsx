import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowCounterClockwiseIcon, PauseIcon, PlayIcon } from "@phosphor-icons/react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOPIC_LABELS = {
  "/camera/image_raw": "Camera",
  "/imu/data": "IMU",
  "/odom": "Odometry",
  "/diagnostics": "Diagnostics",
};

const EMPTY = {
  run_id: null,
  run: null,
  robot_health: null,
  topics: [],
  anomalies: [],
  incident_history: [],
  completion: { verified: false, summary_file_count: 0 },
  mission_progress_ms: 0,
  consumer_offsets: [],
};

const SERVICE_LABELS = {
  kafka: "Kafka",
  flink: "Flink cluster",
  flink_job: "Streaming job",
  projection_api: "Projection API",
  replayer: "MCAP replayer",
};

const EMPTY_READINESS = {
  status: "starting",
  services: Object.fromEntries(Object.keys(SERVICE_LABELS).map((name) => [name, "unknown"])),
};

const EMPTY_LOCALIZATION = { status: "unavailable", summary: null, trajectory: [], event_matches: [] };

function formatRate(value) {
  return value == null ? "—" : `${value.toFixed(value >= 10 ? 1 : 2)} Hz`;
}

function formatDurationMs(value) {
  if (value == null) return "unknown";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function formatTime(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatScore(value) {
  return value == null ? "—" : value.toFixed(3);
}

function healthTone(status = "waiting") {
  if (["healthy", "ok", "ready", "completed", "recovered"].includes(status)) return "ok";
  if (["rate", "warn", "paused", "finalizing", "recovering", "degraded"].includes(status)) return "warn";
  if (["gap", "never_seen", "offline", "error", "failed", "unavailable"].includes(status)) return "bad";
  return "idle";
}

function StatusPill({ status }) {
  return <span className={`status-pill ${healthTone(status)}`}>{String(status || "waiting").replaceAll("_", " ")}</span>;
}

function formatEvidence(evidence = {}) {
  const parts = [];
  if (evidence.observed_rate_hz != null && evidence.expected_rate_hz != null) {
    parts.push(`${formatRate(evidence.observed_rate_hz)} observed / ${formatRate(evidence.expected_rate_hz)} expected`);
  }
  if (evidence.incident_duration_ms != null) parts.push(`${(evidence.incident_duration_ms / 1000).toFixed(1)} s duration`);
  if (evidence.watermark_ms != null) parts.push(`watermark ${evidence.watermark_ms}`);
  if (evidence.accepted_late_count != null) parts.push(`${evidence.accepted_late_count} accepted late`);
  return parts.join(" · ");
}

function RateBars({ topics }) {
  return (
    <div className="rate-bars" aria-label="Observed versus expected message rates">
      {Object.entries(TOPIC_LABELS).map(([topic, label]) => {
        const metric = topics.find((item) => item.topic === topic);
        const payload = metric?.payload || {};
        const ratio = Math.max(0, Math.min(1.25, payload.rate_ratio || 0));
        return (
          <div className="rate-row" key={topic}>
            <div className="rate-label"><span>{label}</span><strong>{formatRate(payload.mean_rate_hz)}</strong></div>
            <div className="rate-track">
              <span className="target-band" />
              <span className={`rate-fill ${healthTone(payload.status)}`} style={{ width: `${Math.min(100, ratio * 80)}%` }} />
            </div>
            <span className="rate-target">target {formatRate(payload.expected_rate_hz)}</span>
          </div>
        );
      })}
    </div>
  );
}

function MissionTimeline({ progressMs }) {
  const progress = Math.min(100, Math.max(0, progressMs / 900));
  return (
    <div className={`mission-timeline ${progress >= 100 ? "complete" : ""}`} aria-label={`Mission elapsed ${formatTime(progressMs)} of 01:30`}>
      <div className="timeline-rail">
        <span className="timeline-progress" style={{ width: `${progress}%` }} />
        <span className="timeline-cursor" style={{ left: `${progress}%` }} />
        {Array.from({ length: 10 }, (_, index) => (
          <span className="timeline-tick" style={{ left: `${(index / 9) * 100}%` }} key={index} />
        ))}
      </div>
      <div className="timeline-labels" aria-hidden="true">
        {Array.from({ length: 10 }, (_, index) => <span key={index}>{formatTime(index * 10_000)}</span>)}
      </div>
    </div>
  );
}

function TransportAction({ label, disabled, onClick, children, primary = false }) {
  return (
    <div className="transport-action">
      <button
        className={primary ? "primary" : ""}
        type="button"
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onClick}
      >
        {children}
      </button>
      <span>{label}</span>
    </div>
  );
}

function TelemetryTable({ topicMap, unavailable }) {
  return (
    <div className="telemetry-table-wrap">
      <table className="telemetry-table">
        <thead>
          <tr><th>Topic</th><th>Health</th><th>Observed</th><th>Expected</th><th>Max gap</th><th>Messages</th></tr>
        </thead>
        <tbody>
          {Object.entries(TOPIC_LABELS).map(([topic, label]) => {
            const payload = topicMap[topic]?.payload || {};
            const status = unavailable ? "unavailable" : payload.health_status || payload.status || "waiting";
            return (
              <tr key={topic}>
                <td data-label="Topic"><strong>{label}</strong><code>{topic}</code></td>
                <td data-label="Health"><StatusPill status={status} /></td>
                <td data-label="Observed">{formatRate(payload.mean_rate_hz)}</td>
                <td data-label="Expected">{formatRate(payload.expected_rate_hz)}</td>
                <td data-label="Max gap">{payload.max_inter_message_gap_s == null ? "—" : `${payload.max_inter_message_gap_s.toFixed(2)} s`}</td>
                <td data-label="Messages">{payload.message_count?.toLocaleString() || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LocalizationTrajectory({ points }) {
  const geometry = useMemo(() => {
    const valid = points.filter((point) => [
      point.ground_truth_x,
      point.ground_truth_y,
      point.estimated_x,
      point.estimated_y,
    ].every(Number.isFinite));
    if (!valid.length) return null;
    const xs = valid.flatMap((point) => [point.ground_truth_x, point.estimated_x]);
    const ys = valid.flatMap((point) => [point.ground_truth_y, point.estimated_y]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = Math.max(maxX - minX, 0.1);
    const spanY = Math.max(maxY - minY, 0.1);
    const scale = Math.min(560 / spanX, 280 / spanY);
    const offsetX = (600 - spanX * scale) / 2;
    const offsetY = (320 - spanY * scale) / 2;
    const project = (x, y) => [
      offsetX + (x - minX) * scale,
      320 - offsetY - (y - minY) * scale,
    ];
    const path = (xKey, yKey) => {
      const segments = new Map();
      valid.forEach((point) => {
        const segment = point.segment_id ?? 0;
        if (!segments.has(segment)) segments.set(segment, []);
        segments.get(segment).push(point);
      });
      return [...segments.entries()].map(([segment, segmentPoints]) => ({
        segment,
        d: segmentPoints.map((point, index) => {
          const [x, y] = project(point[xKey], point[yKey]);
          return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(" "),
      }));
    };
    return {
      estimated: path("estimated_x", "estimated_y"),
      groundTruth: path("ground_truth_x", "ground_truth_y"),
      failures: valid.filter((point) => point.label_failure).map((point) => {
        const [x, y] = project(point.estimated_x, point.estimated_y);
        return { x, y, detected: point.detector_failure, timestamp: point.elapsed_ms };
      }),
    };
  }, [points]);

  if (!geometry) return <div className="trajectory-empty">No trajectory samples available.</div>;
  return (
    <svg className="trajectory-map" viewBox="0 0 600 320" role="img" aria-label="Ground-truth and AMCL estimated trajectories">
      {geometry.groundTruth.map((path) => (
        <path className="trajectory-ground-truth" d={path.d} key={`ground-truth-${path.segment}`} />
      ))}
      {geometry.estimated.map((path) => (
        <path className="trajectory-estimated" d={path.d} key={`estimated-${path.segment}`} />
      ))}
      {geometry.failures.map((point, index) => (
        <circle
          className={point.detected ? "failure-detected" : "failure-missed"}
          cx={point.x}
          cy={point.y}
          r="2.4"
          key={`${point.timestamp}-${index}`}
        />
      ))}
    </svg>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState(EMPTY);
  const [scenario, setScenario] = useState("clean");
  const [rate, setRate] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [flink, setFlink] = useState({ status: "unknown" });
  const [readiness, setReadiness] = useState(EMPTY_READINESS);
  const [localization, setLocalization] = useState(EMPTY_LOCALIZATION);

  const refresh = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/runs/current/snapshot`);
    if (!response.ok) throw new Error("Snapshot API is unavailable");
    setSnapshot(await response.json());
  }, []);

  useEffect(() => {
    refresh().catch((reason) => setError(reason.message));
    let events;
    let reconnectTimer;
    let stopped = false;
    let retryMs = 500;
    const connect = () => {
      events = new EventSource(`${API_URL}/api/runs/current/events`);
      events.onopen = () => { setConnected(true); retryMs = 500; };
      events.onerror = () => {
        setConnected(false);
        setError("Telemetry API unavailable. Keep the stack running; this view will reconnect automatically.");
        setSnapshot((current) => ({ ...current, robot_health: null, topics: [] }));
        events.close();
        if (!stopped) {
          reconnectTimer = window.setTimeout(connect, retryMs);
          retryMs = Math.min(retryMs * 2, 10_000);
        }
      };
      events.addEventListener("snapshot", (event) => setSnapshot(JSON.parse(event.data)));
      ["metric", "anomaly", "completed"].forEach((type) => events.addEventListener(type, () => refresh().catch(() => {})));
      events.addEventListener("completion_failed", (event) => {
        const payload = JSON.parse(event.data);
        setError(`${payload.detail}. Inspect the Flink checkpoint and summary-file diagnostics.`);
        refresh().catch(() => {});
      });
    };
    connect();
    return () => { stopped = true; window.clearTimeout(reconnectTimer); events?.close(); };
  }, [refresh]);

  useEffect(() => {
    const load = () => fetch(`${API_URL}/api/flink/summary`)
      .then((response) => response.ok ? response.json() : { status: "unknown" })
      .then(setFlink)
      .catch(() => setFlink({ status: "unknown" }));
    load();
    const interval = window.setInterval(load, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const load = () => fetch(`${API_URL}/api/localization/evaluation`)
      .then((response) => response.ok ? response.json() : EMPTY_LOCALIZATION)
      .then(setLocalization)
      .catch(() => setLocalization(EMPTY_LOCALIZATION));
    load();
    const interval = window.setInterval(load, 10_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const load = () => fetch(`${API_URL}/api/health`)
      .then((response) => response.json())
      .then(setReadiness)
      .catch(() => setReadiness(EMPTY_READINESS));
    load();
    const interval = window.setInterval(load, 2000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (scenario === "camera-dropout" && rate !== 1) setRate(1);
  }, [scenario, rate]);

  const streamingAuthoritiesReady = connected
    && ["kafka", "flink", "flink_job", "projection_api"]
      .every((name) => readiness.services?.[name] === "ready");
  const authorityUnavailable = Boolean(snapshot.run_id) && !streamingAuthoritiesReady;
  const runStatus = authorityUnavailable
    ? "unavailable"
    : snapshot.completion?.verified
    ? "completed"
    : snapshot.run?.payload?.status || "ready";
  const robotStatus = authorityUnavailable
    ? "unavailable"
    : snapshot.robot_health?.payload?.status || "waiting";
  const topicMap = useMemo(
    () => Object.fromEntries(snapshot.topics.map((item) => [item.topic, item])),
    [snapshot.topics],
  );
  const activeIncidents = snapshot.anomalies.filter((item) => item.status === "active");
  const primaryAnomaly = snapshot.robot_health?.payload?.primary_anomaly;
  const localizationSummary = localization.summary || {};
  const localizationSampleMetrics = localizationSummary.sample_metrics || {};
  const localizationEventMetrics = localizationSummary.event_metrics || {};

  async function control(path, body) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Control request failed");
      }
      await refresh();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="command-header">
        <div className="title-lockup">
          <span className="eyebrow">Streaming operations console</span>
          <h1><span>Robot Telemetry</span><br />Flight Deck</h1>
        </div>
        <div className="header-operations">
          <section className="readiness" aria-label="Stack readiness">
            <span className="eyebrow">Stack readiness</span>
            <div className="readiness-services">
              {Object.entries(SERVICE_LABELS).map(([name, label]) => {
                const status = readiness.services?.[name] || "unknown";
                return <span className={`readiness-item ${healthTone(status)}`} key={name}><i /><span>{label}</span><strong>{status}</strong></span>;
              })}
            </div>
          </section>
          <div className="header-state">
            <span className={`connection-dot ${connected ? "live" : ""}`} />
            {connected ? "Live data" : "Reconnecting"}
            <span>Recorded replay</span>
          </div>
        </div>
      </header>

      {readiness.status !== "ready" && (
        <p className="recovery-message" role="status">
          Stack services are still starting or unavailable. If this persists, run <code>docker compose ps</code> and <code>docker compose logs</code>.
        </p>
      )}

      <section className="mission-summary" aria-label="Mission summary">
        <div className="summary-cell mission-identity">
          <span className="eyebrow">Mission</span>
          <div className="summary-heading"><h2>Warehouse run 17</h2><StatusPill status={runStatus} /></div>
          <p>A deterministic 90-second ROS 2 mission replayed through Kafka and Apache Flink.</p>
        </div>
        <div className="summary-cell robot-summary">
          <span className="eyebrow">Robot health</span>
          <div className="summary-heading"><h2>robot-17</h2><StatusPill status={robotStatus} /></div>
          <dl>
            <div><dt>Topics online</dt><dd>{snapshot.topics.length} / 4</dd></div>
            <div><dt>Source</dt><dd>MCAP replay</dd></div>
            <div><dt>Output</dt><dd>{snapshot.completion?.verified ? "Verified" : "Pending"}</dd></div>
          </dl>
        </div>
        <div className="summary-cell incident-summary">
          <span className="eyebrow">Active incidents</span>
          <strong className="incident-count">{activeIncidents.length}</strong>
          <div className="primary-anomaly">
            {primaryAnomaly
              ? <><strong>{primaryAnomaly.condition_type.replaceAll("_", " ")}</strong><code>{primaryAnomaly.topic || "Robot-wide"}</code></>
              : <><strong>None active</strong><span>All monitored systems nominal</span></>}
          </div>
        </div>
      </section>

      <section className="timeline-section">
        <div className="section-title compact">
          <div><span className="eyebrow">Mission timeline <b>(90 seconds)</b></span></div>
          <strong className="elapsed">{formatTime(snapshot.mission_progress_ms)} / 01:30</strong>
        </div>
        <MissionTimeline progressMs={snapshot.mission_progress_ms} />
        <div className="timeline-controls">
          <div className="transport-controls">
            <TransportAction
              label="Start mission"
              primary
              disabled={busy || readiness.status !== "ready" || ["running", "paused"].includes(runStatus)}
              onClick={() => control("/api/replay/start", { rate, scenario: scenario === "clean" ? null : scenario })}
            ><PlayIcon size={26} weight="fill" /></TransportAction>
            <TransportAction label="Pause" disabled={busy || runStatus !== "running"} onClick={() => control("/api/replay/pause")}>
              <PauseIcon size={26} weight="fill" />
            </TransportAction>
            <TransportAction label="Resume" disabled={busy || runStatus !== "paused"} onClick={() => control("/api/replay/resume")}>
              <PlayIcon size={26} weight="fill" />
            </TransportAction>
            <TransportAction label="Restart" disabled={busy || !snapshot.run_id} onClick={() => control("/api/replay/restart")}>
              <ArrowCounterClockwiseIcon size={26} weight="bold" />
            </TransportAction>
          </div>
          <div className="selector-grid">
            <label>Scenario
              <select value={scenario} onChange={(event) => setScenario(event.target.value)} disabled={busy}>
                <option value="clean">Clean mission</option>
                <option value="camera-dropout">Camera dropout</option>
              </select>
            </label>
            <label>Replay speed
              <select value={rate} onChange={(event) => setRate(Number(event.target.value))} disabled={busy}>
                <option value={1}>1× real time</option>
                <option value={5} disabled={scenario !== "clean"}>5× accelerated</option>
              </select>
            </label>
          </div>
        </div>
        {scenario === "camera-dropout" && (
          <p className="selector-note">Camera dropout runs at 1× so the robot's processing-time watchdog stays tied to real time. Use 5× for the clean mission.</p>
        )}
        {error && <p className="error-message" role="alert">{error}</p>}
      </section>

      <section className="telemetry-section">
        <div className="section-title compact"><div><span className="eyebrow">Live telemetry</span></div><span>10 s windows · 1 s slide</span></div>
        <TelemetryTable topicMap={topicMap} unavailable={authorityUnavailable} />
      </section>

      <section className="localization-section">
        <div className="section-title">
          <div><span className="eyebrow">Localization integrity · public labeled evaluation</span></div>
          <StatusPill status={localization.status === "available" ? "ready" : "unavailable"} />
        </div>
        {localization.status === "available" ? (
          <div className="localization-grid">
            <article className="trajectory-panel">
              <div className="trajectory-legend"><span className="ground-truth-key">Ground truth</span><span className="estimated-key">AMCL estimate</span><span className="detected-key">Detected failure</span><span className="missed-key">Missed failure</span></div>
              <LocalizationTrajectory points={localization.trajectory || []} />
            </article>
            <article className="evaluation-panel">
              <span className="eyebrow">Evaluation metrics</span>
              <div className="evaluation-metrics">
                <div><span>Sample precision</span><strong>{formatScore(localizationSampleMetrics.precision)}</strong></div>
                <div><span>Sample recall</span><strong>{formatScore(localizationSampleMetrics.recall)}</strong></div>
                <div><span>Sample F1</span><strong>{formatScore(localizationSampleMetrics.f1)}</strong></div>
                <div><span>Event precision</span><strong>{formatScore(localizationEventMetrics.precision)}</strong></div>
                <div><span>Event recall</span><strong>{formatScore(localizationEventMetrics.recall)}</strong></div>
              </div>
              <p className="evaluation-contract">Detector: particle spread + AMCL jumps. Ground truth and published labels are scoring-only.</p>
            </article>
            <article className="event-summary">
              <span className="eyebrow">Event summary</span>
              <div className="event-counts">
                <div><strong>{localizationEventMetrics.matched_event_count ?? "—"}</strong><span>Detected</span></div>
                <div className="bad"><strong>{Math.max(0, (localizationEventMetrics.expected_event_count || 0) - (localizationEventMetrics.matched_event_count || 0))}</strong><span>Missed</span></div>
                <div><strong>{localizationEventMetrics.false_alarm_event_count ?? "—"}</strong><span>False alarms</span></div>
              </div>
              <div className="event-match-list">
                {(localization.event_matches || []).slice(0, 4).map((match) => (
                  <div key={match.expected_event_id}><span>expected {formatTime((match.expected_start_timestamp_ns - localization.evaluation_start_timestamp_ns) / 1_000_000)}</span><strong>{match.detected ? `detected ${formatTime((match.observed_start_timestamp_ns - localization.evaluation_start_timestamp_ns) / 1_000_000)} (${match.onset_lag_ms >= 0 ? "+" : ""}${Math.round(match.onset_lag_ms)} ms) · recovered ${formatTime((match.observed_end_timestamp_ns - localization.evaluation_start_timestamp_ns) / 1_000_000)}` : "missed"}</strong></div>
                ))}
              </div>
            </article>
          </div>
        ) : (
          <article className="localization-empty"><strong>No localization evaluation loaded</strong><p>Run <code>ros-telemetry evaluate-localization</code> and publish the results to <code>data/evaluations/latest</code>.</p></article>
        )}
      </section>

      <details className="operations-detail">
        <summary><span><span className="eyebrow">Operational detail</span><strong>Throughput and incident log</strong></span><span>Expand</span></summary>
        <div className="operations-grid">
          <article>
            <div className="section-head"><div><span className="eyebrow">Rate monitor</span><h2>Observed throughput</h2></div><span className="legend">Target band</span></div>
            <RateBars topics={snapshot.topics} />
          </article>
          <article className="incidents">
            <div className="section-head"><div><span className="eyebrow">Incident timeline</span><h2>Detection log</h2></div><strong>{snapshot.incident_history.length}</strong></div>
            <ol>
              {snapshot.incident_history.slice(-8).reverse().map((incident) => (
                <li key={`${incident.anomaly_id}-${incident.revision}`}>
                  <span className={`incident-dot ${incident.status}`} />
                  <div><strong>{incident.condition_type.replaceAll("_", " ")}</strong><span>{TOPIC_LABELS[incident.topic] || "Robot-wide"} · revision {incident.revision}</span>{formatEvidence(incident.evidence) && <span>{formatEvidence(incident.evidence)}</span>}</div>
                  <StatusPill status={incident.status === "active" ? "error" : "recovered"} />
                </li>
              ))}
              {!snapshot.incident_history.length && <li className="empty-state">No incidents yet. Run the camera dropout scenario to exercise event-time recovery.</li>}
            </ol>
          </article>
        </div>
      </details>

      <details className="technical">
        <summary><span><span className="eyebrow">Technical details</span><strong>Pipeline state & durability</strong></span><span>Expand</span></summary>
        <div className="technical-grid">
          <div><h3>Event-time policy</h3><p>2 s out-of-orderness · 5 s allowed lateness · 3 s idle partitions</p></div>
          <div><h3>Durability</h3><p>5 s checkpoints · exactly-once Kafka sinks · SQLite offset projection</p></div>
          <div><h3>Mission output</h3><p>{snapshot.completion?.summary_file_count || 0} / 4 topic summaries independently verified</p></div>
          <div><h3>Runtime</h3><p>{flink.status === "available" ? "Flink job available" : "Flink unavailable · metrics unknown"} · <a href="http://localhost:8081" target="_blank" rel="noreferrer">Open dashboard ↗</a></p></div>
          <div><h3>Streaming authority</h3><p>Source lag {flink.consumer_lag ?? "unknown"} · projection lag {flink.projection_lag ?? "unknown"} · watermark {flink.watermark_ms ?? "unknown"} · checkpoint {flink.checkpoints?.status?.toLowerCase() ?? "unknown"} #{flink.checkpoints?.id ?? "unknown"} ({formatDurationMs(flink.checkpoints?.age_ms)} old) · restarts {flink.restarts ?? "unknown"}</p></div>
          <div><h3>Event counters</h3><p>Processed {flink.events_processed ?? "unknown"} · accepted late {flink.accepted_late_events ?? "unknown"} · duplicate {flink.duplicate_events ?? "unknown"} · too late {flink.too_late_events ?? "unknown"} · operator in/out {flink.records_in ?? "unknown"}/{flink.records_out ?? "unknown"}</p></div>
        </div>
        <div className="offsets"><code>{snapshot.consumer_offsets.map((item) => `${item.topic}[${item.partition}]=${item.next_offset}`).join("  ·  ") || "Waiting for Kafka offsets"}</code></div>
      </details>
      <footer><span>Robot Telemetry Flight Deck</span><span>Kafka → Flink DataStream → FastAPI → React</span></footer>
    </main>
  );
}
