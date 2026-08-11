import { useCallback, useEffect, useMemo, useState } from "react";

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

function TopicCard({ topic, metric, unavailable = false }) {
  const payload = metric?.payload || {};
  const status = unavailable
    ? "unavailable"
    : payload.health_status || payload.status || "waiting";
  return (
    <article className={`topic-card ${healthTone(status)}`}>
      <div className="topic-card-head">
        <div><span className="eyebrow">TOPIC</span><h3>{TOPIC_LABELS[topic]}</h3></div>
        <StatusPill status={status} />
      </div>
      <code>{topic}</code>
      <dl>
        <div><dt>Observed</dt><dd>{formatRate(payload.mean_rate_hz)}</dd></div>
        <div><dt>Expected</dt><dd>{formatRate(payload.expected_rate_hz)}</dd></div>
        <div><dt>Max gap</dt><dd>{payload.max_inter_message_gap_s == null ? "—" : `${payload.max_inter_message_gap_s.toFixed(2)} s`}</dd></div>
        <div><dt>Messages</dt><dd>{payload.message_count?.toLocaleString() || "—"}</dd></div>
      </dl>
    </article>
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
      <header className="masthead">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div>
          <span className="eyebrow">STREAMING OPERATIONS CONSOLE</span>
          <h1>Robot Telemetry <em>Flight Deck</em></h1>
        </div>
        <div className="header-state">
          <span className={`connection-dot ${connected ? "live" : ""}`} />
          {connected ? "LIVE DATA" : "RECONNECTING"}
          <span className="source-badge">RECORDED REPLAY</span>
        </div>
      </header>

      <section className="readiness" aria-label="Stack readiness">
        <span className="eyebrow">STACK READINESS</span>
        <div className="readiness-services">
          {Object.entries(SERVICE_LABELS).map(([name, label]) => {
            const status = readiness.services?.[name] || "unknown";
            return <span className={`readiness-item ${healthTone(status)}`} key={name}><i /><span>{label}</span><strong>{status}</strong></span>;
          })}
        </div>
      </section>
      {readiness.status !== "ready" && (
        <p className="recovery-message" role="status">
          Stack services are still starting or unavailable. If this persists, run <code>docker compose ps</code> and <code>docker compose logs</code>.
        </p>
      )}

      <section className="hero-grid">
        <article className="panel mission-control">
          <div className="section-head">
            <div><span className="eyebrow">MISSION CONTROL</span><h2>Warehouse run 17</h2></div>
            <StatusPill status={runStatus} />
          </div>
          <p className="muted">A deterministic 90-second ROS 2 mission replayed through Kafka and Apache Flink.</p>
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
          {scenario === "camera-dropout" && (
            <p className="selector-note">
              Camera dropout runs at 1× so the robot's processing-time watchdog stays tied to real time. Use 5× for the clean mission.
            </p>
          )}
          <div className="controls">
            <button className="primary" disabled={busy || readiness.status !== "ready" || ["running", "paused"].includes(runStatus)} onClick={() => control("/api/replay/start", { rate, scenario: scenario === "clean" ? null : scenario })}>Start mission</button>
            <button disabled={busy || runStatus !== "running"} onClick={() => control("/api/replay/pause")}>Pause</button>
            <button disabled={busy || runStatus !== "paused"} onClick={() => control("/api/replay/resume")}>Resume</button>
            <button disabled={busy || !snapshot.run_id} onClick={() => control("/api/replay/restart")}>Restart</button>
          </div>
          {error && <p className="error-message" role="alert">{error}</p>}
          <div className="progress-wrap">
            <div className="progress-meta"><span>Mission elapsed</span><strong>{formatTime(snapshot.mission_progress_ms)} / 01:30</strong></div>
            <div className="progress"><span style={{ width: `${Math.min(100, snapshot.mission_progress_ms / 900)}%` }} /></div>
          </div>
        </article>

        <article className={`panel robot-overview ${healthTone(robotStatus)}`}>
          <div className="section-head">
            <div><span className="eyebrow">ROBOT HEALTH</span><h2>robot-17</h2></div>
            <div className="radar" aria-hidden="true"><span /></div>
          </div>
          <div className="health-callout"><StatusPill status={robotStatus} /><strong>{activeIncidents.length}</strong><span>active incidents</span></div>
          <div className="primary-anomaly">
            <span className="eyebrow">PRIMARY ANOMALY</span>
            {primaryAnomaly
              ? <><strong>{primaryAnomaly.condition_type.replaceAll("_", " ")}</strong><code>{primaryAnomaly.topic || "Robot-wide"}</code></>
              : <strong>None active</strong>}
          </div>
          <dl className="compact-stats">
            <div><dt>Topics online</dt><dd>{snapshot.topics.length} / 4</dd></div>
            <div><dt>Source</dt><dd>MCAP replay</dd></div>
            <div><dt>Output verified</dt><dd>{snapshot.completion?.verified ? "Yes" : "Pending"}</dd></div>
          </dl>
        </article>
      </section>

      <section>
        <div className="section-title"><div><span className="eyebrow">LIVE TELEMETRY</span><h2>Topic health</h2></div><span className="muted">10 s windows · 1 s slide</span></div>
        <div className="topic-grid">
          {Object.keys(TOPIC_LABELS).map((topic) => (
            <TopicCard
              key={topic}
              topic={topic}
              metric={topicMap[topic]}
              unavailable={authorityUnavailable}
            />
          ))}
        </div>
      </section>

      <section className="lower-grid">
        <article className="panel">
          <div className="section-head"><div><span className="eyebrow">RATE MONITOR</span><h2>Observed throughput</h2></div><span className="legend">target band</span></div>
          <RateBars topics={snapshot.topics} />
        </article>
        <article className="panel incidents">
          <div className="section-head"><div><span className="eyebrow">INCIDENT TIMELINE</span><h2>Detection log</h2></div><strong>{snapshot.incident_history.length}</strong></div>
          <ol>
            {snapshot.incident_history.slice(-8).reverse().map((incident) => (
              <li key={`${incident.anomaly_id}-${incident.revision}`}>
                <span className={`incident-dot ${incident.status}`} />
                <div>
                  <strong>{incident.condition_type.replaceAll("_", " ")}</strong>
                  <span>{TOPIC_LABELS[incident.topic] || "Robot-wide"} · revision {incident.revision}</span>
                  {formatEvidence(incident.evidence) && <span className="incident-evidence">{formatEvidence(incident.evidence)}</span>}
                </div>
                <StatusPill status={incident.status === "active" ? "error" : "recovered"} />
              </li>
            ))}
            {!snapshot.incident_history.length && <li className="empty-state">No incidents yet. Run the camera dropout scenario to exercise event-time recovery.</li>}
          </ol>
        </article>
      </section>

      <details className="technical panel">
        <summary><span><span className="eyebrow">TECHNICAL DETAILS</span><strong>Pipeline state & durability</strong></span><span>Expand</span></summary>
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
      <footer><span>ROBOT TELEMETRY FLIGHT DECK</span><span>Kafka → Flink DataStream → FastAPI → React</span></footer>
    </main>
  );
}
