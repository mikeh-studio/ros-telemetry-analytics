import {
  PlayIcon,
  PauseIcon,
  ArrowCounterClockwiseIcon,
} from "@phosphor-icons/react";
import { TransportAction } from "./TelemetryVisuals";

export default function ReplayControls({ state }) {
  const {
    viewingLive,
    selectedDataset,
    scenario,
    setScenario,
    busy,
    datasetLocked,
    rate,
    setRate,
    runStatus,
    uploading,
    readiness,
    selectedDatasetId,
    control,
    snapshot,
    selectedRunMatches,
    error,
  } = state;
  return (
    <section className="replay-controls" aria-label="Replay controls">
      <h2 className="replay-title">{viewingLive ? "Live ROS 2" : "Replay"}</h2>
      <div className="replay-settings">
        <div className="replay-fields">
          {selectedDataset?.supports_camera_dropout && (
            <label>
              Fault injection
              <select
                value={scenario}
                onChange={(event) => setScenario(event.target.value)}
                disabled={viewingLive || busy || datasetLocked}
              >
                <option value="clean">None</option>
                <option
                  value="camera-dropout"
                  disabled={!selectedDataset?.supports_camera_dropout}
                >
                  Camera dropout
                </option>
              </select>
            </label>
          )}
          <fieldset
            className="replay-rate"
            disabled={viewingLive || busy || datasetLocked}
          >
            <legend>Replay speed</legend>
            <div className="replay-rate-options">
              {[1, 5].map((speed) => (
                <label key={speed}>
                  <input
                    type="radio"
                    name="replay-speed"
                    value={speed}
                    checked={rate === speed}
                    disabled={speed === 5 && scenario !== "clean"}
                    onChange={() => setRate(speed)}
                    aria-label={speed === 1 ? "1× real time" : "5× accelerated"}
                  />
                  <span>{speed}×</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </div>
      <div className="replay-actions">
        <div className="replay-buttons">
          <TransportAction
            label={runStatus === "completed" ? "Replay again" : "Start replay"}
            primary
            disabled={
              busy ||
              uploading ||
              viewingLive ||
              readiness.status !== "ready" ||
              datasetLocked ||
              !selectedDataset?.selectable
            }
            onClick={() =>
              control("/api/replay/start", {
                rate,
                dataset_id: selectedDatasetId,
                scenario: scenario === "clean" ? null : scenario,
              })
            }
          >
            <PlayIcon size={26} weight="fill" />
          </TransportAction>
          {runStatus === "running" && (
            <TransportAction
              label="Pause"
              disabled={viewingLive || busy || runStatus !== "running"}
              onClick={() => control("/api/replay/pause")}
            >
              <PauseIcon size={26} weight="fill" />
            </TransportAction>
          )}
          {runStatus === "paused" && (
            <TransportAction
              label="Resume"
              disabled={viewingLive || busy || runStatus !== "paused"}
              onClick={() => control("/api/replay/resume")}
            >
              <PlayIcon size={26} weight="fill" />
            </TransportAction>
          )}
          {["running", "paused", "failed"].includes(runStatus) && (
            <TransportAction
              label="Restart"
              disabled={
                viewingLive || busy || !snapshot.run_id || !selectedRunMatches
              }
              onClick={() => control("/api/replay/restart")}
            >
              <ArrowCounterClockwiseIcon size={26} weight="bold" />
            </TransportAction>
          )}
        </div>
      </div>
      {scenario === "camera-dropout" && (
        <p className="selector-note">
          Camera dropout runs at 1× so the processing-time watchdog stays tied
          to real time. Use 5× without fault injection.
        </p>
      )}
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
