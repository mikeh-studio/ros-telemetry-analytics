import { useEffect, useState } from "react";
import { explanationStatusLabel } from "./recordingCopy";

export default function RecordingIncidentList({
  apiUrl,
  datasetId,
  analysisId,
  selectedId,
  onSelect,
}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError("");
    const query = new URLSearchParams({
      analysis_id: analysisId,
      offset,
      limit: 20,
    });
    fetch(
      `${apiUrl}/api/investigations/${encodeURIComponent(datasetId)}/incidents?${query}`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.detail || "Incident list unavailable");
        if (!controller.signal.aborted && body.analysis_id === analysisId)
          setPage(body);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [apiUrl, datasetId, analysisId, offset]);
  return (
    <section
      className="recording-incident-list"
      aria-label="Detected incidents"
    >
      <div className="recording-incident-heading">
        <h3>Detected incidents</h3>
        {page && (
          <span>
            {page.total_count}{" "}
            {page.total_count === 1 ? "incident" : "incidents"} · in time order
          </span>
        )}
      </div>
      <p>
        Select an incident to review its measurements, possible explanations,
        and next checks. Incidents group related warnings; they do not confirm a
        failure.
      </p>
      {error && (
        <p role="alert">
          {error}. Use Rebuild evidence to update this recording’s analysis.
        </p>
      )}
      {!page && !error && <p role="status">Loading incidents…</p>}
      {page?.total_count === 0 && (
        <p>
          No incidents found by the current checks. Issues outside these checks
          may still be present.
        </p>
      )}
      <div className="recording-incident-options">
        {page?.incidents.map((incident) => (
          <button
            key={incident.incident_id}
            className={selectedId === incident.incident_id ? "is-selected" : ""}
            aria-pressed={selectedId === incident.incident_id}
            onClick={() => onSelect(incident.incident_id)}
          >
            <strong>{incident.title}</strong>
            <span>
              {incident.start_s.toFixed(3)}–{incident.end_s.toFixed(3)} s ·{" "}
              {incident.member_count}{" "}
              {incident.member_count === 1 ? "warning" : "warnings"}
            </span>
            <span>{incident.topics.join(" · ")}</span>
            <small>{explanationStatusLabel(incident.explanation_status)}</small>
          </button>
        ))}
      </div>
      {page && (offset > 0 || page.next_offset != null) && (
        <div className="recording-incident-pagination">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            Previous incidents
          </button>
          <span>
            {offset + 1}–{offset + page.returned_count} of {page.total_count}
          </span>
          <button
            disabled={page.next_offset == null}
            onClick={() => setOffset(page.next_offset)}
          >
            Next incidents
          </button>
        </div>
      )}
    </section>
  );
}
