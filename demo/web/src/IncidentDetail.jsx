import { useState } from "react";
import IncidentTrajectory from "./IncidentTrajectory";

const OBSERVATIONS = {
  GAP: "Messages stopped arriving after this topic had been observed.",
  NEVER_SEEN: "No messages were observed before the startup deadline.",
  RATE: "The observed message rate remained below the configured threshold.",
  ROBOT_OFFLINE: "The robot exceeded the processing-time silence deadline.",
  OFFLINE: "The robot exceeded the processing-time silence deadline.",
};

function signalValue(value) {
  if (value == null) return "Unavailable";
  if (typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value)) {
    return `${value} (approximate)`;
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function timestamp(value) {
  return value == null ? "Unavailable" : `${value} ms`;
}

function compareIncidents(a, b) {
  const activeFirst = Number(b.latest.status === "active") - Number(a.latest.status === "active");
  if (activeFirst) return activeFirst;
  const aTime = a.latest.effective_start_stream_ms;
  const bTime = b.latest.effective_start_stream_ms;
  const aKnown = Number.isFinite(aTime), bKnown = Number.isFinite(bTime);
  if (aKnown !== bKnown) return aKnown ? -1 : 1;
  if (aKnown && aTime !== bTime) return bTime - aTime;
  return String(a.latest.anomaly_id).localeCompare(String(b.latest.anomaly_id));
}

export default function IncidentDetail({ runId, history = [], anomalies = [], signals = [] }) {
  const [selectedId, setSelectedId] = useState(null);
  const groups = new Map();
  for (const item of [...history, ...anomalies]) {
    if (item.run_id !== runId) continue;
    if (!groups.has(item.anomaly_id)) groups.set(item.anomaly_id, new Map());
    groups.get(item.anomaly_id).set(item.revision, item);
  }
  const incidents = [...groups.values()].map((revisions) => {
    const transitions = [...revisions.values()].sort((a, b) => a.revision - b.revision);
    return { latest: transitions.at(-1), transitions };
  }).sort(compareIncidents);
  const selected = incidents.find(({ latest }) => latest.anomaly_id === selectedId) || incidents[0];
  const latest = selected?.latest;
  const firstActive = selected?.transitions.find((item) => item.status === "active");
  const relatedSignals = !latest ? [] : signals.filter((item) => item.run_id === runId
    && item.robot_id === latest?.robot_id
    && item.stream_timestamp_ms >= latest.effective_start_stream_ms - 5000
    && (latest.recovered_stream_ms == null || item.stream_timestamp_ms <= latest.recovered_stream_ms + 5000));
  const latestSignals = [...new Map(relatedSignals.slice().sort((a, b) => a.stream_timestamp_ms - b.stream_timestamp_ms)
    .map((item) => [item.topic, item])).values()];
  return (
    <section className={`incident-detail${latest ? "" : " is-empty"}`} aria-label="Incident explanation">
      <div className="section-head"><div><span className="eyebrow">Observed failure and recovery</span><h2>Incident explanation</h2></div><span>{incidents.length} incidents</span></div>
      {!latest ? <p>No incidents recorded for this run.</p> : <>
        <label className="incident-picker">Inspect incident
          <select value={latest.anomaly_id} onChange={(event) => setSelectedId(event.target.value)}>
            {incidents.map(({ latest: item }) => <option key={item.anomaly_id} value={item.anomaly_id}>{item.topic || "Robot-wide"} · {item.condition_type.replaceAll("_", " ")} · {item.status} · {item.effective_start_stream_ms}</option>)}
          </select>
        </label>
        <div className="incident-evidence-grid">
          <article><h3>What was observed</h3>
            <p>{OBSERVATIONS[latest.condition_type] || `The ${latest.condition_type} detector raised an incident.`}</p>
            <dl><dt>Affected topic</dt><dd>{latest.topic || "Robot-wide"}</dd><dt>Robot</dt><dd>{latest.robot_id}</dd><dt>Current state</dt><dd>{latest.status}</dd></dl>
            <p>Cause is unconfirmed. Missing telemetry alone cannot distinguish sensor failure, transport interruption, or publisher configuration.</p>
          </article>
          <article><h3>Timeline</h3>
            <dl><dt>Effective start</dt><dd>{timestamp(latest.effective_start_stream_ms)}</dd><dt>First detection</dt><dd>{timestamp(firstActive?.detected_stream_ms)}</dd><dt>Recovery</dt><dd>{latest.status === "recovered" ? timestamp(latest.recovered_stream_ms) : "Not yet observed"}</dd></dl>
            <p>Stream timestamps. {latest.evidence?.decision_clock === "processing_elapsed_projected_to_stream" ? "Watchdog decisions map elapsed processing time onto the stream clock." : "Detection follows the event-time policy."}</p>
            {!firstActive && <p>The opening revision is outside the retained history.</p>}
          </article>
          <article><h3>Detector evidence</h3>
            {selected.transitions.map((item) => <details key={item.revision} open={item.revision === latest.revision}>
              <summary>{item.status} · revision {item.revision}</summary>
              <dl>{Object.entries(item.evidence || {}).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{signalValue(value)}</dd></div>)}</dl>
            </details>)}
            {!latestSignals.length && <p>Localization and trajectory signals: unavailable in the retained incident interval.</p>}
          </article>
        </div>
        <article className="incident-signals"><h3>Signals around this incident</h3>
          <p>Same robot and run, from five seconds before onset through five seconds after recovery. One accepted observation per topic per second; latest sample shown below. Retention is limited to 180 samples per topic. These observations do not establish cause. The public labeled evaluation below is a separate recording.</p>
          <div className="incident-evidence-grid">{latestSignals.map((item) => <details key={item.metric_id}>
            <summary>{item.topic} · {timestamp(item.stream_timestamp_ms)}</summary>
            <dl>{Object.entries(item.payload?.attributes || {}).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{signalValue(value)}</dd></div>)}</dl>
          </details>)}</div>
          {relatedSignals.some((item) => item.payload?.attributes?.event_kind === "qos_incompatible")
            && <p>A QoS incompatibility callback was recorded during this interval. Check its affected topic before associating it with this incident.</p>}
        </article>
        <IncidentTrajectory signals={relatedSignals} onset={latest.effective_start_stream_ms} recovered={latest.recovered_stream_ms} />
      </>}
    </section>
  );
}
