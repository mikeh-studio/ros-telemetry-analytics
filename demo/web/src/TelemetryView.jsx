import IncidentDetail from "./IncidentDetail";
import TopicHistory from "./TopicHistory";
import TelemetryPipeline from "./TelemetryPipeline";
import ReplayControls from "./ReplayControls";
import { capability } from "./DatasetContext";
import { signalLabel as topicLabel } from "./signals";
import { SERVICE_LABELS } from "./workbenchConfig";
import {
  formatTime,
  formatDurationMs,
  formatEvidence,
  healthTone,
  StatusPill,
  RateBars,
  MissionTimeline,
} from "./TelemetryVisuals";

export default function TelemetryView({ state, activeView, setActiveView }) {
  const {
    snapshot,
    scenario,
    error,
    connected,
    flink,
    readiness,
    localization,
    selectedDatasetId,
    selectedDataset,
    viewingLive,
    authorityUnavailable,
    authorityPending,
    runStatus,
    robotStatus,
    visibleTopics,
    robotTopics,
    pipelineTopics,
    visibleSignals,
    pipelineSignals,
    activeIncidents,
    pipelineIncidents,
    pipeline,
    primaryAnomaly,
    selectedRunMatches,
    selectedRunActive,
    missionDurationMs,
    expectedTopicCount,
    datasetLocked,
  } = state;
  return (
    <section
      id="panel-health"
      role="tabpanel"
      aria-labelledby="view-health"
      hidden={activeView !== "health"}
    >
      <div className="analysis-workspace">
        <ReplayControls state={state} />
        {(!selectedRunActive || readiness.status !== "ready") && (
          <section className="replay-empty" aria-label="Replay status">
            <div className="replay-message" role="status">
              <p>
                {capability(selectedDataset, "health") === "loading"
                  ? "Loading recording availability…"
                  : !selectedDataset?.selectable
                    ? "Replay is unavailable for this recording."
                    : datasetLocked && !selectedRunMatches
                      ? "Another recording is being replayed."
                      : readiness.status !== "ready"
                        ? "Replay services are not ready."
                        : "Ready to replay this recording."}
              </p>
              <p>
                {capability(selectedDataset, "recordings") === "ready"
                  ? "Prepared sensor evidence is available."
                  : selectedRunActive
                    ? "Live results will resume when services reconnect."
                    : "No replay results yet for this dataset."}
              </p>
            </div>
          </section>
        )}
        <div className="replay-followup">
          {(!selectedRunActive || readiness.status !== "ready") &&
            capability(selectedDataset, "recordings") === "ready" && (
              <button
                className="inspect-evidence"
                onClick={() => {
                  setActiveView("recordings");
                  document.getElementById("view-recordings").focus();
                }}
              >
                Inspect sensor evidence
              </button>
            )}
          <details className="stack-disclosure">
            <summary>
              <span>Connection details</span>
              <strong>
                {
                  Object.values(readiness.services || {}).filter(
                    (status) => status === "ready",
                  ).length
                }
                /5 services ready
              </strong>
            </summary>
            <section className="readiness" aria-label="Stack readiness">
              <p className="connection-summary">
                {connected ? "API connected" : "Reconnecting to API"}.{" "}
                {readiness.status === "ready"
                  ? "Replay services are ready."
                  : "Start the local replay stack to enable streaming analytics."}
              </p>
              {readiness.status !== "ready" && (
                <p className="connection-summary">
                  Check <code>docker compose ps</code> and{" "}
                  <code>docker compose logs</code> for service diagnostics.
                </p>
              )}
              <div className="readiness-services">
                {Object.entries(SERVICE_LABELS).map(([name, label]) => {
                  const status = readiness.services?.[name] || "unknown";
                  return (
                    <span
                      className={`readiness-item ${healthTone(status)}`}
                      key={name}
                    >
                      <i />
                      <span>{label}</span>
                      <strong>{status}</strong>
                    </span>
                  );
                })}
              </div>
            </section>
          </details>
        </div>
        {selectedRunActive && (
          <div className="analysis-main">
            <div className="monitor-heading">
              <h2>Monitor</h2>
              <StatusPill
                status={runStatus === "ready" ? "not started" : runStatus}
              />
            </div>
            {Number.isFinite(missionDurationMs) && (
              <section className="timeline-section">
                <div className="section-title compact">
                  <div>
                    <span className="eyebrow">
                      Mission timeline <b>({formatTime(missionDurationMs)})</b>
                    </span>
                  </div>
                  <strong className="elapsed">
                    {formatTime(
                      selectedRunMatches ? snapshot.mission_progress_ms : 0,
                    )}{" "}
                    / {formatTime(missionDurationMs)}
                  </strong>
                </div>
                <MissionTimeline
                  incidents={selectedRunMatches ? snapshot.anomalies : []}
                  startMs={snapshot.run_start_stream_ms}
                  progressMs={
                    selectedRunMatches ? snapshot.mission_progress_ms : 0
                  }
                  durationMs={missionDurationMs}
                />
              </section>
            )}

            <section className="mission-summary" aria-label="Operations status">
              <div className="summary-cell robot-summary">
                <span className="eyebrow">
                  Telemetry status
                  {runStatus === "completed" ? " · end of run" : " · latest"}
                </span>
                <div className="summary-heading">
                  <h2>
                    {selectedRunMatches
                      ? snapshot.robot_id ||
                        snapshot.run?.robot_id ||
                        "Unknown source"
                      : "—"}
                  </h2>
                  <StatusPill status={robotStatus} />
                </div>
                <dl>
                  <div>
                    <dt>Monitored topics</dt>
                    <dd>{robotTopics.length}</dd>
                  </div>
                  <div>
                    <dt>Total monitored topics</dt>
                    <dd>
                      {visibleTopics.length} / {expectedTopicCount ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Source</dt>
                    <dd>
                      {selectedDataset?.file_format?.replaceAll("_", " ") ||
                        "ROS bag"}
                    </dd>
                  </div>
                  <div>
                    <dt>Output</dt>
                    <dd>
                      {selectedRunMatches && snapshot.completion?.verified
                        ? "Verified"
                        : "Pending"}
                    </dd>
                  </div>
                </dl>
              </div>
              <div className="summary-cell incident-summary">
                <span className="eyebrow">Active incidents</span>
                <strong className="incident-count">
                  {activeIncidents.length}{" "}
                  <small>
                    active ·{" "}
                    {selectedRunMatches
                      ? snapshot.anomalies.filter(
                          (item) => item.status === "recovered",
                        ).length
                      : 0}{" "}
                    resolved
                  </small>
                </strong>
                <div className="primary-anomaly">
                  {primaryAnomaly ? (
                    <>
                      <strong>
                        {primaryAnomaly.condition_type.replaceAll("_", " ")}
                      </strong>
                      <code>{primaryAnomaly.topic || "Robot-wide"}</code>
                    </>
                  ) : (
                    <>
                      <strong>None active</strong>
                      <span>
                        {robotStatus === "healthy"
                          ? "No open incidents"
                          : "See robot and topic status"}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </section>

            {(pipeline.unhealthy || pipeline.attention) && (
              <p className="pipeline-notice">
                <a
                  href="#telemetry-pipeline"
                  onClick={() => {
                    document.getElementById("telemetry-pipeline").open = true;
                  }}
                >
                  Telemetry Pipeline:{" "}
                  {pipeline.unhealthy
                    ? "delivery needs attention"
                    : "event to inspect"}{" "}
                  · View evidence
                </a>
              </p>
            )}

            <TopicHistory
              completed={runStatus === "completed"}
              live={viewingLive}
              key={`${snapshot.run_id}-${selectedDatasetId}`}
              topics={robotTopics}
              signals={visibleSignals}
              history={selectedRunMatches ? snapshot.topic_history || [] : []}
              startMs={snapshot.run_start_stream_ms}
              durationMs={
                viewingLive
                  ? Math.max(
                      missionDurationMs,
                      snapshot.mission_progress_ms || 0,
                    )
                  : missionDurationMs
              }
              incidents={selectedRunMatches ? snapshot.anomalies : []}
              unavailable={authorityUnavailable}
            />

            <TelemetryPipeline
              key={`pipeline-${snapshot.run_id}-${selectedDatasetId}`}
              topics={pipelineTopics}
              signals={pipelineSignals}
              incidents={pipelineIncidents}
              startMs={snapshot.run_start_stream_ms}
              unavailable={authorityUnavailable && !authorityPending}
              pending={authorityPending}
              live={viewingLive}
            />

            <IncidentDetail
              key={snapshot.run_id}
              runId={selectedRunMatches ? snapshot.run_id : null}
              history={snapshot.incident_history}
              anomalies={snapshot.anomalies}
              signals={snapshot.observed_signals}
            />

            <div className="investigation-entry">
              <span>
                Review localization evidence attached to the selected dataset.
              </span>
              <button
                onClick={() => {
                  setActiveView("localization");
                  document.getElementById("view-localization").focus();
                }}
              >
                Open Localization
              </button>
            </div>

            <details className="operations-detail">
              <summary>
                <span>
                  <span className="eyebrow">Operational detail</span>
                  <strong>Throughput and incident log</strong>
                </span>
                <span>Expand</span>
              </summary>
              <div className="operations-grid">
                <article>
                  <div className="section-head">
                    <div>
                      <span className="eyebrow">Rate monitor</span>
                      <h2>Observed throughput</h2>
                    </div>
                    <span className="legend">Target band</span>
                  </div>
                  <RateBars topics={visibleTopics} />
                </article>
                <article className="incidents">
                  <div className="section-head">
                    <div>
                      <span className="eyebrow">Incident timeline</span>
                      <h2>Detection log</h2>
                    </div>
                    <strong>{snapshot.incident_history.length}</strong>
                  </div>
                  <ol>
                    {snapshot.incident_history
                      .slice(-8)
                      .reverse()
                      .map((incident) => (
                        <li key={`${incident.anomaly_id}-${incident.revision}`}>
                          <span className={`incident-dot ${incident.status}`} />
                          <div>
                            <strong>
                              {incident.condition_type.replaceAll("_", " ")}
                            </strong>
                            <span>
                              {incident.topic
                                ? topicLabel(incident.topic)
                                : "Robot-wide"}{" "}
                              · revision {incident.revision}
                            </span>
                            {formatEvidence(incident.evidence) && (
                              <span>{formatEvidence(incident.evidence)}</span>
                            )}
                          </div>
                          <StatusPill
                            status={
                              incident.status === "active"
                                ? "error"
                                : "recovered"
                            }
                          />
                        </li>
                      ))}
                    {!snapshot.incident_history.length && (
                      <li className="empty-state">
                        No incidents yet. Run the camera dropout scenario to
                        exercise event-time recovery.
                      </li>
                    )}
                  </ol>
                </article>
              </div>
            </details>

            <details className="technical">
              <summary>
                <span>
                  <span className="eyebrow">Technical details</span>
                  <strong>Pipeline state & durability</strong>
                </span>
                <span>Expand</span>
              </summary>
              <div className="technical-grid">
                <div>
                  <h3>Event-time policy</h3>
                  <p>
                    2 s out-of-orderness · 5 s allowed lateness · 3 s idle
                    partitions
                  </p>
                </div>
                <div>
                  <h3>Durability</h3>
                  <p>
                    5 s checkpoints · exactly-once Kafka sinks · SQLite offset
                    projection
                  </p>
                </div>
                <div>
                  <h3>Mission output</h3>
                  <p>
                    {selectedRunMatches
                      ? snapshot.completion?.summary_file_count || 0
                      : 0}{" "}
                    / {expectedTopicCount ?? "—"} topic summaries independently
                    verified
                  </p>
                </div>
                <div>
                  <h3>Runtime</h3>
                  <p>
                    {flink.status === "available"
                      ? "Flink job available"
                      : "Flink unavailable · metrics unknown"}{" "}
                    ·{" "}
                    <a
                      href="http://localhost:8081"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open dashboard ↗
                    </a>
                  </p>
                </div>
                <div>
                  <h3>Streaming authority</h3>
                  <p>
                    Source lag {flink.consumer_lag ?? "unknown"} · projection
                    lag {flink.projection_lag ?? "unknown"} · watermark{" "}
                    {flink.watermark_ms ?? "unknown"} · checkpoint{" "}
                    {flink.checkpoints?.status?.toLowerCase() ?? "unknown"} #
                    {flink.checkpoints?.id ?? "unknown"} (
                    {formatDurationMs(flink.checkpoints?.age_ms)} old) ·
                    restarts {flink.restarts ?? "unknown"}
                  </p>
                </div>
                <div>
                  <h3>Event counters</h3>
                  <p>
                    Processed {flink.events_processed ?? "unknown"} · accepted
                    late {flink.accepted_late_events ?? "unknown"} · duplicate{" "}
                    {flink.duplicate_events ?? "unknown"} · too late{" "}
                    {flink.too_late_events ?? "unknown"} · operator in/out{" "}
                    {flink.records_in ?? "unknown"}/
                    {flink.records_out ?? "unknown"}
                  </p>
                </div>
              </div>
              <div className="offsets">
                <code>
                  {snapshot.consumer_offsets
                    .map(
                      (item) =>
                        `${item.topic}[${item.partition}]=${item.next_offset}`,
                    )
                    .join("  ·  ") || "Waiting for Kafka offsets"}
                </code>
              </div>
            </details>
          </div>
        )}
      </div>
    </section>
  );
}
