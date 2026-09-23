import RecordingPicker from "./RecordingPicker";
import { useState } from "react";
import { ArrowRightIcon } from "@phosphor-icons/react";

export function capability(dataset, view) {
  return (
    dataset?.capabilities?.[view] ||
    (view === "health"
      ? dataset?.selectable
        ? "ready"
        : "unavailable"
      : "not_prepared")
  );
}
export function AnalysisUnavailable({ dataset, view }) {
  const status = capability(dataset, view);
  if (status === "loading")
    return (
      <p className="analysis-unavailable" role="status">
        Loading selected dataset…
      </p>
    );
  const explanations = {
    localization:
      "No localization evaluation is attached to this dataset. Compatible estimates, reference data and evaluation inputs are required.",
    recordings:
      dataset?.source === "user_upload"
        ? "Your upload is available for replay. Sensor evidence has not been prepared; uploading does not automatically create an investigation."
        : "Prepared sensor evidence is not available for this dataset.",
    health: "This dataset does not contain an available replayable recording.",
  };
  return (
    <section className="analysis-unavailable" role="status">
      <h2>
        {status === "stale"
          ? "Evidence needs refreshing"
          : "Analysis unavailable"}
      </h2>
      <p>{explanations[view]}</p>
      <p>
        Status: {status.replaceAll("_", " ")}. Choose a compatible dataset
        above.
      </p>
    </section>
  );
}
export default function DatasetContext({
  datasets,
  selected,
  onSelect,
  onRefresh,
  notice,
}) {
  const [aboutOpen, setAboutOpen] = useState(false);
  const coverage = selected?.coverage || [];
  const signalTypes = [
    ...new Set(
      coverage
        .map(
          (c) =>
            ({
              image: "Camera images",
              images: "Camera images",
              tf: "Transforms",
              imu: "IMU",
              lidar: "Lidar",
              scan: "Laser scans",
              laser_scan: "Laser scans",
              command: "Commands",
              odometry: "Odometry",
            })[c.domain] || c.domain?.replaceAll("_", " "),
        )
        .filter((d) => d && d !== "unclassified"),
    ),
  ];
  return (
    <section className="dataset-context" aria-label="Shared dataset context">
      <div className="dataset-toolbar">
        <RecordingPicker
          datasets={datasets}
          selected={selected}
          onSelect={onSelect}
        />
        <button
          className="text-action recording-about"
          aria-expanded={aboutOpen}
          aria-controls="recording-details"
          onClick={() => setAboutOpen(!aboutOpen)}
        >
          About this recording <ArrowRightIcon size={18} aria-hidden="true" />
        </button>
      </div>
      {notice && <p role="status">{notice}</p>}
      <p className="dataset-purpose">
        {selected?.purpose ||
          selected?.description ||
          "Choose a dataset to inspect its available evidence."}
      </p>
      <div className="dataset-facts">
        {(selected?.source === "user_upload" ||
          selected?.source === "built_in") && (
          <span>
            {selected.source === "user_upload"
              ? "User upload"
              : "Controlled synthetic demo"}
          </span>
        )}
        <span>
          {Number.isFinite(selected?.mission_duration_ms)
            ? `${(selected.mission_duration_ms / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} s`
            : "Duration not measured"}
        </span>
        {(coverage.length > 0 || selected?.topic_count != null) && (
          <span>{coverage.length || selected.topic_count} topics</span>
        )}
        {selected?.runs && (
          <span>
            {selected.runs.length} prepared run(s) · independent run clocks
          </span>
        )}
      </div>
      {signalTypes.length > 0 && (
        <p className="dataset-signals">
          <span>Signals</span> {signalTypes.join(" · ")}
        </p>
      )}
      <div
        id="recording-details"
        className="recording-details"
        hidden={!aboutOpen}
      >
        <h2>About this recording</h2>
        <p>
          {(selected?.source === "user_upload"
            ? "User upload"
            : selected?.role || selected?.source || "Unknown origin"
          ).replaceAll("_", " ")}
          {selected?.size_bytes != null &&
            ` · ${(selected.size_bytes / 1048576).toFixed(1)} MB`}
        </p>
        {selected?.purpose && selected?.description !== selected.purpose && (
          <p>{selected?.description}</p>
        )}
        <p>
          {selected?.interpretation ||
            (selected?.source === "user_upload"
              ? "User-provided recording. Scene, origin and license have not been supplied."
              : "Availability and source checks do not establish that the robot is healthy.")}
        </p>
        <p>
          Format: {selected?.file_format || "unknown"} · License:{" "}
          {selected?.license || "not recorded"}
        </p>
        {selected?.source_url && /^https?:\/\//.test(selected.source_url) && (
          <p>
            <a href={selected.source_url} target="_blank" rel="noreferrer">
              Original dataset source
            </a>
          </p>
        )}
        <p>
          Evidence:{" "}
          {selected?.integrity?.replaceAll("_", " ") || "not verified"} ·
          Prepared: {selected?.created_at || "not recorded"}
        </p>
        {coverage.length > 0 && (
          <ul>
            {coverage.map((c, i) => (
              <li key={i}>
                {c.topic} ·{" "}
                {c.message_type || c.msgtype || c.domain || "sensor stream"} ·{" "}
                {c.analysis_status || c.status || "coverage unknown"}
              </li>
            ))}
          </ul>
        )}
        {selected?.recordings && (
          <p>Prepared files: {selected.recordings.join(" · ")}</p>
        )}
        {!!selected?.reference_topics?.length && (
          <p>Reference topics: {selected.reference_topics.join(", ")}</p>
        )}
        <button
          className="text-action"
          onClick={onRefresh}
          aria-label="Refresh dataset catalog"
        >
          Refresh catalog
        </button>
      </div>
    </section>
  );
}
