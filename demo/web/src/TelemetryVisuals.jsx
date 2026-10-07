import { isPipelineTopic, isEventDriven, signalLabel } from "./signals";

function formatRate(value) {
  return value == null ? "—" : `${value.toFixed(value >= 10 ? 1 : 2)} Hz`;
}

export function formatDurationMs(value) {
  if (value == null) return "unknown";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function formatTime(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const topicLabel = signalLabel;

export function healthTone(status = "waiting") {
  if (["healthy", "ok", "ready", "completed", "recovered"].includes(status))
    return "ok";
  if (
    ["rate", "warn", "paused", "finalizing", "recovering", "degraded"].includes(
      status,
    )
  )
    return "warn";
  if (
    ["gap", "never_seen", "offline", "error", "failed", "unavailable"].includes(
      status,
    )
  )
    return "bad";
  return "idle";
}

export function StatusPill({ status }) {
  return (
    <span className={`status-pill ${healthTone(status)}`}>
      {String(status || "waiting").replaceAll("_", " ")}
    </span>
  );
}

export function formatEvidence(evidence = {}) {
  const parts = [];
  if (evidence.observed_rate_hz != null && evidence.expected_rate_hz != null) {
    parts.push(
      `${formatRate(evidence.observed_rate_hz)} observed / ${formatRate(evidence.expected_rate_hz)} expected`,
    );
  }
  if (evidence.incident_duration_ms != null)
    parts.push(
      `${(evidence.incident_duration_ms / 1000).toFixed(1)} s duration`,
    );
  if (evidence.watermark_ms != null)
    parts.push(`watermark ${evidence.watermark_ms}`);
  if (evidence.accepted_late_count != null)
    parts.push(`${evidence.accepted_late_count} accepted late`);
  return parts.join(" · ");
}

export function RateBars({ topics }) {
  const rows = topics.filter(
    (metric) => !isPipelineTopic(metric.topic) && !isEventDriven(metric),
  );
  return (
    <div
      className="rate-bars"
      aria-label="Observed versus expected message rates"
    >
      {!rows.length && (
        <p className="empty-state">No fixed-rate topics observed.</p>
      )}
      {rows.map((metric) => {
        const { topic } = metric;
        const payload = metric.payload || {};
        const ratio = Math.max(0, Math.min(1.25, payload.rate_ratio || 0));
        return (
          <div className="rate-row" key={topic}>
            <div className="rate-label">
              <span>{topicLabel(topic)}</span>
              <strong>{formatRate(payload.mean_rate_hz)}</strong>
            </div>
            <div className="rate-track">
              <span className="target-band" />
              <span
                className={`rate-fill ${healthTone(payload.status)}`}
                style={{ width: `${Math.min(100, ratio * 80)}%` }}
              />
            </div>
            <span className="rate-target">
              target {formatRate(payload.expected_rate_hz)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function MissionTimeline({
  progressMs,
  durationMs,
  incidents = [],
  startMs,
}) {
  const safeDuration = Math.max(1, durationMs || 90_000);
  const progress = Math.min(
    100,
    Math.max(0, (progressMs / safeDuration) * 100),
  );
  const ticks = 6;
  return (
    <div
      className={`mission-timeline ${progress >= 100 ? "complete" : ""}`}
      aria-label={`Mission elapsed ${formatTime(progressMs)} of ${formatTime(safeDuration)}`}
    >
      <div className="timeline-rail">
        <span className="timeline-progress" style={{ width: `${progress}%` }} />
        {incidents.map((incident) => {
          if (
            !Number.isFinite(startMs) ||
            !Number.isFinite(incident.effective_start_stream_ms)
          )
            return null;
          const left = Math.max(
            0,
            Math.min(
              100,
              ((incident.effective_start_stream_ms - startMs) / safeDuration) *
                100,
            ),
          );
          const right = Math.max(
            left,
            Math.min(
              100,
              (((incident.recovered_stream_ms ?? startMs + progressMs) -
                startMs) /
                safeDuration) *
                100,
            ),
          );
          return (
            <span
              key={incident.anomaly_id}
              className="timeline-incident"
              style={{
                left: `${left}%`,
                width: `${Math.max(0.3, right - left)}%`,
              }}
              title={`${incident.topic || "Robot"}: ${incident.condition_type}`}
            />
          );
        })}
        <span className="timeline-cursor" style={{ left: `${progress}%` }} />
        {Array.from({ length: ticks }, (_, index) => (
          <span
            className="timeline-tick"
            style={{ left: `${(index / (ticks - 1)) * 100}%` }}
            key={index}
          />
        ))}
      </div>
      <div className="timeline-labels" aria-hidden="true">
        {Array.from({ length: ticks }, (_, index) => (
          <span key={index}>
            {formatTime((index * safeDuration) / (ticks - 1))}
          </span>
        ))}
      </div>
    </div>
  );
}

export function TransportAction({
  label,
  disabled,
  onClick,
  children,
  primary = false,
}) {
  return (
    <div className="replay-action">
      <button
        className={primary ? "primary" : ""}
        type="button"
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onClick}
      >
        {children}
        <span>{label}</span>
      </button>
    </div>
  );
}
