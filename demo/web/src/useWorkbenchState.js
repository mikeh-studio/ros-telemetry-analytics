import { useCallback, useEffect, useRef, useState } from "react";
import { capability } from "./DatasetContext";
import { pipelineState } from "./TelemetryPipeline";
import { isPipelineTopic } from "./signals";
import {
  saved,
  remember,
  API_URL,
  CONNECTION_ERROR,
  EMPTY,
  EMPTY_DATASETS,
  EMPTY_READINESS,
  EMPTY_LOCALIZATION,
} from "./workbenchConfig";

// Owns replay connection, catalog selection, upload and authority state.
export default function useWorkbenchState() {
  const [snapshot, setSnapshot] = useState(EMPTY);
  const [scenario, setScenario] = useState("clean");
  const [rate, setRate] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [awaitingSnapshot, setAwaitingSnapshot] = useState(false);
  const [flink, setFlink] = useState({ status: "unknown" });
  const [readiness, setReadiness] = useState(EMPTY_READINESS);
  const [readinessLoaded, setReadinessLoaded] = useState(false);
  const [localization, setLocalization] = useState(EMPTY_LOCALIZATION);
  const [datasetCatalog, setDatasetCatalog] = useState(EMPTY_DATASETS);
  const [selectedDatasetId, setSelectedDatasetId] = useState(() =>
    saved("workbench.dataset", EMPTY_DATASETS.default_dataset_id),
  );
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const uploadDialog = useRef(null);
  const datasetSelectionTouched = useRef(
    Boolean(saved("workbench.dataset", "")),
  );
  const [catalogNotice, setCatalogNotice] = useState("");
  const currentRunId = useRef(null);
  const currentLiveId = useRef(null);

  const applySnapshot = useCallback((payload) => {
    if (currentRunId.current !== payload.run_id) setError("");
    currentRunId.current = payload.run_id;
    currentLiveId.current =
      payload.source_format === "live_ros2" ? payload.dataset_id : null;
    setSnapshot(payload);
    if (
      !datasetSelectionTouched.current &&
      payload.run_id &&
      payload.dataset_id
    ) {
      setSelectedDatasetId(payload.dataset_id);
    }
  }, []);

  const refresh = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/runs/current/snapshot`);
    if (!response.ok) throw new Error("Snapshot API is unavailable");
    applySnapshot(await response.json());
  }, [applySnapshot]);

  const loadDatasets = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/datasets`);
    if (!response.ok) throw new Error("Dataset catalog is unavailable");
    const payload = await response.json();
    const entries = payload.datasets || EMPTY_DATASETS.datasets;
    setSelectedDatasetId((current) => {
      if (
        entries.some((d) => d.dataset_id === current) ||
        current === currentLiveId.current
      )
        return current;
      const next =
        payload.default_dataset_id ||
        entries[0]?.dataset_id ||
        EMPTY_DATASETS.default_dataset_id;
      if (datasetSelectionTouched.current)
        setCatalogNotice(
          "The previous dataset is no longer available. Selected the catalog default.",
        );
      remember("workbench.dataset", next);
      return next;
    });
    setDatasetCatalog({
      default_dataset_id:
        payload.default_dataset_id || EMPTY_DATASETS.default_dataset_id,
      datasets: payload.datasets || EMPTY_DATASETS.datasets,
    });
    if (
      !datasetSelectionTouched.current &&
      !currentRunId.current &&
      payload.default_dataset_id
    )
      setSelectedDatasetId(payload.default_dataset_id);
  }, []);

  useEffect(() => {
    loadDatasets().catch((reason) => setCatalogNotice(reason.message));
  }, [loadDatasets]);

  const refreshEvidenceCatalog = useCallback(() => {
    loadDatasets().catch((reason) => setCatalogNotice(reason.message));
  }, [loadDatasets]);

  useEffect(() => {
    refresh().catch((reason) => setError(reason.message));
    let events;
    let reconnectTimer;
    let stopped = false;
    let retryMs = 500;
    const connect = () => {
      const source = new EventSource(`${API_URL}/api/runs/current/events`);
      events = source;
      source.onopen = () => {
        if (stopped || events !== source) return;
        setConnected(true);
        retryMs = 500;
      };
      source.onerror = () => {
        if (stopped || events !== source) return;
        setConnected(false);
        setAwaitingSnapshot(true);
        setError(CONNECTION_ERROR);
        source.close();
        if (!stopped) {
          reconnectTimer = window.setTimeout(connect, retryMs);
          retryMs = Math.min(retryMs * 2, 10_000);
        }
      };
      source.addEventListener("snapshot", (event) => {
        if (stopped || events !== source) return;
        applySnapshot(JSON.parse(event.data));
        setAwaitingSnapshot(false);
        setError((current) => (current === CONNECTION_ERROR ? "" : current));
      });
      ["metric", "anomaly", "completed"].forEach((type) =>
        events.addEventListener(type, () => refresh().catch(() => {})),
      );
      events.addEventListener("completion_failed", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.run_id !== currentRunId.current) return;
        setError(
          `${payload.detail}. Inspect the Flink checkpoint and summary-file diagnostics.`,
        );
        refresh().catch(() => {});
      });
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(reconnectTimer);
      events?.close();
    };
  }, [applySnapshot, refresh]);

  useEffect(() => {
    const load = () =>
      fetch(`${API_URL}/api/flink/summary`)
        .then((response) =>
          response.ok ? response.json() : { status: "unknown" },
        )
        .then(setFlink)
        .catch(() => setFlink({ status: "unknown" }));
    load();
    const interval = window.setInterval(load, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    setLocalization(EMPTY_LOCALIZATION);
    if (!selectedDatasetId.startsWith("localization:")) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/localization/evaluation?dataset_id=${encodeURIComponent(selectedDatasetId)}`,
          { signal: controller.signal },
        );
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.detail || "Evaluation unavailable");
        if (!controller.signal.aborted && body.dataset_id === selectedDatasetId)
          setLocalization(body);
      } catch (reason) {
        if (!controller.signal.aborted)
          setLocalization({ status: "unavailable", detail: reason.message });
      }
    };
    load();
    const interval = window.setInterval(load, 10_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [selectedDatasetId]);

  useEffect(() => {
    const load = () =>
      fetch(`${API_URL}/api/health`)
        .then((response) => response.json())
        .then((result) => {
          setReadiness(result);
          setReadinessLoaded(true);
        })
        .catch(() => {
          setReadiness(EMPTY_READINESS);
          setReadinessLoaded(true);
        });
    load();
    const interval = window.setInterval(load, 2000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (scenario === "camera-dropout" && rate !== 1) setRate(1);
  }, [scenario, rate]);

  const liveDataset =
    snapshot.source_format === "live_ros2" && snapshot.run_id
      ? {
          dataset_id: snapshot.dataset_id,
          name: snapshot.dataset_name,
          description:
            "Live ROS 2 observations received by the gateway. Session timing uses gateway reception time.",
          file_format: "live_ros2",
          source: "live_ros2",
          status: "live session",
          capabilities: {
            health: "ready",
            recordings: "unsupported",
            localization: "unsupported",
          },
          selectable: false,
        }
      : null;
  const availableDatasets = liveDataset
    ? [...datasetCatalog.datasets, liveDataset]
    : datasetCatalog.datasets;
  const selectedDataset = availableDatasets.find(
    (dataset) => dataset.dataset_id === selectedDatasetId,
  ) || {
    dataset_id: selectedDatasetId,
    name: "Loading selected dataset…",
    capabilities: {
      health: "loading",
      recordings: "loading",
      localization: "loading",
    },
  };

  useEffect(() => {
    if (
      selectedDataset &&
      !selectedDataset.supports_camera_dropout &&
      scenario !== "clean"
    ) {
      setScenario("clean");
    }
  }, [scenario, selectedDataset]);

  const selectedRunMatches =
    !snapshot.dataset_id || snapshot.dataset_id === selectedDatasetId;
  const viewingLive = selectedRunMatches && Boolean(liveDataset);
  const servicesReady = ["kafka", "flink", "flink_job", "projection_api"].every(
    (name) => readiness.services?.[name] === "ready",
  );
  const streamingAuthoritiesReady =
    connected && !awaitingSnapshot && servicesReady;
  const authorityUnavailable =
    selectedRunMatches &&
    Boolean(snapshot.run_id) &&
    !streamingAuthoritiesReady;
  // Initial requests can finish in either order. Unknown readiness is not a fault.
  // Explicit service failures and SSE errors still surface immediately.
  const authorityPending =
    authorityUnavailable &&
    !awaitingSnapshot &&
    !(readinessLoaded && !servicesReady) &&
    (!readinessLoaded || !connected);
  const runStatus = authorityPending
    ? "loading"
    : authorityUnavailable
      ? "unavailable"
      : !selectedRunMatches
        ? "ready"
        : snapshot.completion?.verified
          ? "completed"
          : snapshot.run?.payload?.status || "ready";
  const robotStatus = authorityPending
    ? "unknown"
    : authorityUnavailable
      ? "unavailable"
      : selectedRunMatches
        ? snapshot.robot_health?.payload?.status || "waiting"
        : "waiting";
  const visibleTopics = selectedRunMatches ? snapshot.topics : [];
  const robotTopics = visibleTopics.filter(
    (metric) => !isPipelineTopic(metric.topic),
  );
  const pipelineTopics = visibleTopics.filter((metric) =>
    isPipelineTopic(metric.topic),
  );
  const visibleSignals = selectedRunMatches
    ? snapshot.observed_signals || []
    : [];
  const pipelineSignals = visibleSignals.filter((metric) =>
    isPipelineTopic(metric.topic),
  );
  const activeIncidents = selectedRunMatches
    ? snapshot.anomalies.filter((item) => item.status === "active")
    : [];
  const pipelineIncidents = activeIncidents.filter((item) =>
    isPipelineTopic(item.topic),
  );
  const pipeline = pipelineState({
    topics: pipelineTopics,
    signals: pipelineSignals,
    incidents: pipelineIncidents,
    unavailable: authorityUnavailable && !authorityPending,
  });
  const primaryAnomaly = selectedRunMatches
    ? snapshot.robot_health?.payload?.primary_anomaly
    : null;
  const selectedRunActive = selectedRunMatches && Boolean(snapshot.run_id);
  const missionDurationMs = selectedRunActive
    ? snapshot.mission_duration_ms
    : (selectedDataset?.mission_duration_ms ?? null);
  const expectedTopicCount = selectedRunActive
    ? snapshot.topic_count
    : selectedDataset?.topic_count;
  const datasetLocked =
    ["starting", "running", "paused", "finalizing"].includes(
      snapshot.run?.payload?.status,
    ) && !snapshot.completion?.verified;

  function tabAvailability(view) {
    if (view === "navigation") return "Saved comparisons";
    const state = capability(selectedDataset, view);
    if (state === "loading") return "Loading";
    if (view === "health") {
      if (viewingLive)
        return streamingAuthoritiesReady ? "Live" : "Connection unavailable";
      if (!selectedDataset?.selectable || state !== "ready")
        return state === "not_installed"
          ? "Not installed"
          : "Recording unavailable";
      if (readiness.status !== "ready") return "Services not ready";
      if (datasetLocked && !selectedRunMatches) return "Another replay active";
      if (datasetLocked)
        return {
          starting: "Starting replay",
          running: "Replaying",
          paused: "Paused",
          finalizing: "Finishing replay",
        }[snapshot.run?.payload?.status];
      return "Ready";
    }
    return (
      {
        ready: "Ready",
        limited: "Limited coverage",
        stale: "Needs refresh",
        not_installed: "Not installed",
      }[state] || "Analysis not prepared"
    );
  }

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

  function chooseDataset(id) {
    datasetSelectionTouched.current = true;
    setSelectedDatasetId(id);
    remember("workbench.dataset", id);
    setCatalogNotice("");
    setScenario("clean");
  }

  async function uploadDataset(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setUploadError("");
    setError("");
    try {
      const response = await fetch(
        `${API_URL}/api/datasets/upload?filename=${encodeURIComponent(file.name)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(payload.detail || "Dataset upload failed");
      await loadDatasets();
      chooseDataset(payload.dataset_id);
      setScenario("clean");
      uploadDialog.current.close();
    } catch (reason) {
      setUploadError(reason.message);
      setError(reason.message);
    } finally {
      setUploading(false);
    }
  }

  return {
    snapshot,
    scenario,
    setScenario,
    rate,
    setRate,
    busy,
    error,
    connected,
    flink,
    readiness,
    localization,
    selectedDatasetId,
    uploading,
    uploadError,
    uploadDialog,
    setUploadError,
    catalogNotice,
    loadDatasets,
    refreshEvidenceCatalog,
    availableDatasets,
    selectedDataset,
    viewingLive,
    streamingAuthoritiesReady,
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
    tabAvailability,
    control,
    chooseDataset,
    uploadDataset,
  };
}
