export function saved(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
export function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Storage may be disabled. */
  }
}
export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
export const CONNECTION_ERROR =
  "Telemetry API unavailable. Keep the stack running; this view will reconnect automatically.";

export const EMPTY = {
  run_id: null,
  run: null,
  robot_health: null,
  topics: [],
  anomalies: [],
  incident_history: [],
  completion: { verified: false, summary_file_count: 0 },
  mission_progress_ms: 0,
  dataset_id: "warehouse_run_17",
  dataset_name: "Warehouse Run 17",
  source_format: "rosbag2_mcap",
  mission_duration_ms: 90_000,
  topic_count: 4,
  consumer_offsets: [],
};
export const DEFAULT_DATASET = {
  dataset_id: "warehouse_run_17",
  name: "Warehouse Run 17",
  description:
    "Synthetic timing demo with repeated payloads, zero header stamps and a constant 1×1 image.",
  source: "built_in",
  file_format: "rosbag2_mcap",
  status: "ready",
  selectable: true,
  supports_camera_dropout: true,
  mission_duration_ms: 90_000,
  topic_count: 4,
};
export const EMPTY_DATASETS = {
  default_dataset_id: DEFAULT_DATASET.dataset_id,
  datasets: [DEFAULT_DATASET],
};

export const SERVICE_LABELS = {
  kafka: "Kafka",
  flink: "Flink cluster",
  flink_job: "Streaming job",
  projection_api: "Projection API",
  replayer: "MCAP replayer",
};

export const EMPTY_READINESS = {
  status: "starting",
  services: Object.fromEntries(
    Object.keys(SERVICE_LABELS).map((name) => [name, "unknown"]),
  ),
};

export const EMPTY_LOCALIZATION = {
  status: "unavailable",
  summary: null,
  trajectory: [],
  event_matches: [],
};
