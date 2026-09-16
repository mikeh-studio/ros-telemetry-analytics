export const isPipelineTopic = (topic = "") => topic.startsWith("/_telemetry/");
export const isEventDriven = (metric) => metric.topic === "/_telemetry/gateway_events" || metric.payload?.rate_monitoring_enabled === false;
export function signalLabel(topic = "") {
  const known = {
    "/camera/image_raw": "Camera", "/imu/data": "IMU", "/odom": "Odometry",
    "/scan": "Lidar", "/amcl_pose": "Map localization", "/diagnostics": "Diagnostics",
    "/_telemetry/gateway_health": "Gateway health", "/_telemetry/gateway_events": "Gateway events",
  }[topic];
  if (known) return known;
  const camera = topic.match(/^\/cam(\d+)\/image_raw$/);
  if (camera) return `Camera ${camera[1]}`;
  const imu = topic.match(/^\/imu(\d+)$/);
  if (imu) return `IMU ${imu[1]}`;
  // Preserve the namespace for unfamiliar streams so distinct sources stay distinct.
  return topic || "Topic";
}
export const signalPurpose = (topic) => ({
  "/camera/image_raw": "Image delivery supports the robot’s vision.",
  "/imu/data": "Inertial measurements help track physical motion.",
  "/odom": "Odometry tracks local movement; estimates can drift.",
  "/scan": "Range measurements support obstacle detection.",
  "/amcl_pose": "The map pose supports navigation and localization.",
  "/diagnostics": "Component reports help explain robot problems.",
})[topic] || "";

export const signalTime = (ms, startMs) => {
  if (!Number.isFinite(ms)) return "Unavailable";
  if (!Number.isFinite(startMs)) return `${ms} ms (stream time)`;
  const seconds = Math.max(0, Math.floor((ms - startMs) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")} into run`;
};

export function latestObservation(signals, topic, robotId) {
  return signals.filter((item) => item.topic === topic && (!robotId || item.robot_id === robotId))
    .sort((a, b) => b.stream_timestamp_ms - a.stream_timestamp_ms || (b.revision || 0) - (a.revision || 0))[0];
}
