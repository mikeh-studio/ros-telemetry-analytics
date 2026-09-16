import { useEffect, useRef } from "react";
import { isEventDriven, latestObservation, signalLabel, signalTime } from "./signals";
import { topicDescription } from "./TopicInfo";

const value = (item) => item == null ? "Unavailable" : typeof item === "object" ? JSON.stringify(item) : String(item);
const concerning = (status) => ["degraded", "recovering", "gap", "never_seen", "offline", "error", "failed", "unavailable", "warn", "warning", "critical", "rate"].includes(status?.toLowerCase());

export function pipelineState({ topics = [], signals = [], incidents = [], unavailable }) {
  // Observations can arrive before the first rate window. Keep them visible too.
  const rows = [...new Map([...signals.map((item) => ({ topic: item.topic, robot_id: item.robot_id, payload: {} })), ...topics]
    .map((item) => [`${item.robot_id}:${item.topic}`, item])).values()];
  const active = incidents.filter((item) => item.status === "active");
  const transportFault = rows.some((item) => {
    const attributes = latestObservation(signals, item.topic, item.robot_id)?.payload?.attributes || {};
    return attributes.transport_state === "disconnected";
  });
  const unhealthy = unavailable || transportFault || active.length > 0 || rows.some((item) =>
    !isEventDriven(item) && concerning(item.payload?.health_status || item.payload?.status));
  const events = signals.filter((item) => item.payload?.attributes?.event_kind)
    .slice().sort((a, b) => b.stream_timestamp_ms - a.stream_timestamp_ms);
  const latestEvent = events[0];
  const attention = latestEvent && (concerning(latestEvent.payload.attributes.severity)
    || latestEvent.payload.attributes.event_kind === "qos_incompatible");
  return { rows, active, transportFault, unhealthy, events, latestEvent, attention };
}

export default function TelemetryPipeline({ topics = [], signals = [], incidents = [], startMs, unavailable, live }) {
  const panel = useRef(null);
  const { rows, active, transportFault, unhealthy, events, latestEvent, attention } = pipelineState({ topics, signals, incidents, unavailable });
  const issueKey = `${unavailable}:${transportFault}:${rows.map((item) => !isEventDriven(item) && (item.payload?.health_status || item.payload?.status)).join(",")}:${attention ? latestEvent.metric_id || latestEvent.stream_timestamp_ms : ""}:${active.map((item) => item.anomaly_id).join(",")}`;
  useEffect(() => {
    if ((unhealthy || attention) && panel.current) panel.current.open = true;
  }, [issueKey, unhealthy, attention]);
  const status = unavailable ? "Unavailable" : unhealthy ? "Needs attention" : attention ? "Event to inspect" : rows.length ? "Monitoring" : live ? "Awaiting gateway evidence" : "No gateway streams in this recording";

  return <details id="telemetry-pipeline" ref={panel} className={`telemetry-pipeline${unhealthy || attention ? " needs-attention" : ""}`}>
    <summary><span><strong>Telemetry Pipeline</strong><span>Can we trust the delivery of topic data?</span></span><span className={`status-pill ${unhealthy ? "bad" : attention ? "warn" : "idle"}`}>{status}</span></summary>
    <div className="pipeline-content">
      {unavailable && <p role="status">Live monitoring is unavailable. Values below are last received evidence, not current confirmation of telemetry health.</p>}
      <p>Gateway delivery problems can make topics appear silent. Correlate timestamps and affected topics before attributing a cause.</p>
      {!rows.length && <p>{live ? "Waiting for gateway health or event observations." : "This recording contains no gateway streams. Stack readiness remains available above."}</p>}
      <div className="pipeline-streams">{rows.map((metric) => {
        const observation = latestObservation(signals, metric.topic, metric.robot_id);
        const attributes = observation?.payload?.attributes || {};
        const eventDriven = isEventDriven(metric);
        return <article key={`${metric.robot_id}:${metric.topic}`}>
          <h3>{signalLabel(metric.topic)}</h3><code>{metric.topic}</code>
          <p>{eventDriven ? "Event-driven · silence does not imply a fault." : `Delivery health: ${unavailable ? "unavailable" : metric.payload?.health_status || metric.payload?.status || "waiting"}`}</p>
          <dl><dt>{eventDriven ? "Last observed event" : "Last observed update"}</dt><dd>{signalTime(observation?.stream_timestamp_ms, startMs)}</dd>
            {eventDriven && observation && attributes.severity == null && <><dt>Severity</dt><dd>Not reported</dd></>}
            {Object.entries(attributes).map(([key, item]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value(item)}</dd></div>)}
          </dl>
          {eventDriven && !observation && <p>No events observed in retained evidence.</p>}
          <details><summary>About {signalLabel(metric.topic)}</summary><p>{topicDescription(metric.topic)}</p>
            {!eventDriven && <p>Observed rate: {Number.isFinite(metric.payload?.mean_rate_hz) ? `${Number(metric.payload.mean_rate_hz.toFixed(2))} Hz` : "Unavailable"} · expected: {Number.isFinite(metric.payload?.expected_rate_hz) ? `${metric.payload.expected_rate_hz} Hz` : "Unavailable"}</p>}
          </details>
        </article>;
      })}</div>
      {active.map((item) => <p key={item.anomaly_id}><strong>{item.condition_type?.replaceAll("_", " ")}</strong> · {item.topic} · since {signalTime(item.effective_start_stream_ms, startMs)}. See incident explanation for detector evidence.</p>)}
      {events.length > 0 && <details className="pipeline-events"><summary>Retained gateway events · {events.length}</summary><ol>{events.map((item) => {
        const attributes = item.payload.attributes;
        return <li key={item.metric_id || `${item.robot_id}:${item.topic}:${item.stream_timestamp_ms}`}><strong>{attributes.event_kind.replaceAll("_", " ")}</strong> · {signalTime(item.stream_timestamp_ms, startMs)} · severity: {attributes.severity || "not reported"}{attributes.affected_topic && <> · <code>{attributes.affected_topic}</code></>}{attributes.count != null && <> · count: {attributes.count}</>}</li>;
      })}</ol></details>}
      {signals.length > 0 && <p className="pipeline-retention">Evidence is sampled: first accepted observation per topic per second, up to 180 samples per topic. This is not a complete event log; an earlier event does not prove a fault is still active.</p>}
    </div>
  </details>;
}
