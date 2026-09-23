import { explanationStatusLabel } from "./recordingCopy";

export default function RecordingIncidentExplanation({
  incident,
  onInspect,
  onMembers,
}) {
  if (!incident) return null;
  const refs = new Map(incident.evidence.map((item) => [item.id, item]));
  const links = (ids) =>
    ids.map((id) => {
      const ref = refs.get(id);
      return (
        ref && (
          <button
            className="recording-evidence-link"
            key={id}
            onClick={() => onInspect(ref)}
          >
            Inspect {ref.topic}
            {ref.field ? ` · ${ref.field}` : " · original event"}
          </button>
        )
      );
    });
  return (
    <article
      className="recording-incident-explanation"
      aria-label="Incident explanation"
    >
      <p className="eyebrow">SELECTED INCIDENT</p>
      <h3>{incident.title}</h3>
      <p>
        {incident.start_s.toFixed(3)}–{incident.end_s.toFixed(3)} s ·{" "}
        {explanationStatusLabel(incident.explanation_status)}
      </p>
      {incident.member_count > incident.member_events.length && (
        <p className="recording-muted">
          Showing evidence for warnings {incident.member_offset + 1}–
          {incident.member_offset + incident.member_events.length} of{" "}
          {incident.member_count}. Use Original warnings below to change pages.
        </p>
      )}
      <h4>What was observed</h4>
      {incident.observations.map((observation, i) => (
        <div key={`${observation.rule_id}-${i}`}>
          <p>{observation.text}</p>
          {links(observation.evidence_refs)}
        </div>
      ))}
      <div className="recording-explanation-columns">
        <section>
          <h4>Possible explanations</h4>
          {incident.possibilities.length ? (
            <ul>
              {incident.possibilities.map((item) => (
                <li key={item.text}>
                  {item.text}{" "}
                  <span className="recording-muted">— {item.status}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              The available evidence does not support an explanation for this
              warning.
            </p>
          )}
        </section>
        <section>
          <h4>What remains uncertain</h4>
          <ul>
            {incident.limits.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </section>
      </div>
      <h4>Next checks</h4>
      {incident.next_checks.map((check, i) => (
        <div key={i}>
          <p>{check.text}</p>
          <p className="recording-muted">{check.reason}</p>
          {links(check.evidence_refs)}
        </div>
      ))}
      <details>
        <summary>Measurements and source details</summary>
        {incident.evidence.map((ref) => (
          <section className="recording-evidence-record" key={ref.id}>
            <h4>
              {ref.topic} · {ref.field || "detector event"}
            </h4>
            <p>
              {ref.availability} · {ref.reason}
            </p>
            <p>
              {ref.start_timestamp_ns}–{ref.end_timestamp_ns} ns · {ref.clock}
            </p>
            <pre>{JSON.stringify(ref.parameters, null, 2)}</pre>
            {ref.selection && (
              <>
                <p>
                  {ref.selection.count ?? "Recorded"} samples · bounded
                  examples; full selection retained in the prepared evidence.
                </p>
                <pre>{JSON.stringify(ref.selection, null, 2)}</pre>
              </>
            )}
          </section>
        ))}
        <p>
          Source SHA-256: <code>{incident.source_sha256}</code>
        </p>
        <p>
          Analysis: <code>{incident.analysis_id}</code>
        </p>
        <p>
          {incident.catalog_version} · {incident.grouping_version}
        </p>
      </details>
      <details>
        <summary>Original warnings · {incident.member_count}</summary>
        <p>{incident.grouping_reason}</p>
        {incident.member_events.map((event) => (
          <div className="recording-evidence-record" key={event.event_id}>
            <strong>
              {event.topic} · {event.event_type}
            </strong>
            <p>
              {event.start_s.toFixed(3)}–{event.end_s.toFixed(3)} s ·{" "}
              {event.observed_value} / {event.threshold} {event.unit}
            </p>
            <p>{event.detail}</p>
          </div>
        ))}
        {(incident.member_offset > 0 ||
          incident.next_member_offset != null) && (
          <div className="recording-incident-pagination">
            <button
              disabled={incident.member_offset === 0}
              onClick={() =>
                onMembers(Math.max(0, incident.member_offset - 50))
              }
            >
              Previous warnings
            </button>
            <button
              disabled={incident.next_member_offset == null}
              onClick={() => onMembers(incident.next_member_offset)}
            >
              Next warnings
            </button>
          </div>
        )}
      </details>
    </article>
  );
}
