import { expect, test } from "@playwright/test";

const metric = (topic, rate, enabled = true) => ({ topic, robot_id: "robot-nav2-1", payload: { health_status: "healthy", status: "ok", mean_rate_hz: rate, expected_rate_hz: rate || 1, rate_monitoring_enabled: enabled } });
const base = {
  run_id: "nav2-fixture", robot_id: "robot-nav2-1", dataset_id: "live-ros2", source_format: "live_ros2", source: "live_ros2",
  dataset_name: "Live ROS session", run: { payload: { status: "running" } }, robot_health: { payload: { status: "healthy" } },
  topic_count: 5, topics: [metric("/scan", 5), metric("/odom", 30), metric("/amcl_pose", 0, false), metric("/_telemetry/gateway_health", 1), metric("/_telemetry/gateway_events", 0, false)],
  anomalies: [], incident_history: [], observed_signals: [], topic_history: [], completion: {}, consumer_offsets: [],
  mission_duration_ms: 120000, mission_progress_ms: 12000, run_start_stream_ms: 1000,
};

async function openFixture(page, snapshot = base) {
  await page.addInitScript(() => {
    window.EventSource = class {
      constructor() { this.listeners = {}; window.events = this; setTimeout(() => this.onopen?.(), 0); }
      addEventListener(type, callback) { this.listeners[type] = callback; }
      close() {}
    };
    window.emitSnapshot = (payload) => window.events.listeners.snapshot({ data: JSON.stringify(payload) });
  });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = path.endsWith("/health") ? { status: "ready", services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }
      : path.endsWith("/snapshot") ? snapshot : path.endsWith("/datasets") ? { datasets: [] } : { status: "unavailable" };
    return route.fulfill({ json });
  });
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Monitored Topics" })).toBeVisible();
}

test("Nav2 robot signals and event evidence stay separate on desktop and mobile", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openFixture(page);
  const robot = page.getByRole("region", { name: "Monitored Topics" });
  const pipeline = page.locator(".telemetry-pipeline");
  await expect(robot.locator("tbody tr")).toHaveCount(3);
  await expect(robot).not.toContainText("/_telemetry/");
  await expect(pipeline).not.toHaveAttribute("open");
  const amcl = robot.locator("tr").filter({ hasText: "/amcl_pose" });
  await expect(amcl).toContainText("No fixed rate");
  await expect(amcl).not.toContainText("0 Hz");
  await robot.getByRole("button", { name: "Map localization" }).click();
  await expect(robot.getByText(/This is an estimate, not ground truth/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("signals-desktop.png"), fullPage: true });

  const fault = { ...base,
    topics: base.topics.map((item) => item.topic.endsWith("gateway_health") ? { ...item, payload: { ...item.payload, health_status: "degraded" } } : item),
    observed_signals: [{ topic: "/_telemetry/gateway_events", robot_id: "robot-nav2-1", metric_id: "qos-event", stream_timestamp_ms: 11000, payload: { attributes: { event_kind: "qos_incompatible", affected_topic: "/scan", count: 2 } } }],
  };
  await page.evaluate((snapshot) => window.emitSnapshot(snapshot), fault);
  await expect(pipeline).toHaveAttribute("open");
  await expect(pipeline).toContainText("Needs attention");
  await expect(pipeline).toContainText("00:10 into run");
  await expect(pipeline).toContainText("qos_incompatible");
  const notice = page.getByRole("link", { name: /Telemetry Pipeline: delivery needs attention/ });
  await expect(notice).toBeVisible();
  const eventCard = pipeline.locator("article").filter({ hasText: "Gateway events" });
  await expect(eventCard).not.toContainText("Hz");
  await pipeline.locator(":scope > summary").click();
  await expect(pipeline).not.toHaveAttribute("open");
  await page.evaluate((snapshot) => window.emitSnapshot(snapshot), fault);
  await expect(pipeline).not.toHaveAttribute("open");
  await notice.click();
  await expect(pipeline).toHaveAttribute("open");
  await page.screenshot({ path: testInfo.outputPath("pipeline-fault-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(robot.getByRole("button", { name: "Lidar" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("signals-mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("recorded demo keeps all four robot signals and no fabricated gateway streams", async ({ page }) => {
  await openFixture(page, { ...base, source: "recorded_replay", source_format: "rosbag2_mcap", dataset_id: "warehouse_run_17", dataset_name: "Warehouse Run 17", topic_count: 4,
    topics: [metric("/camera/image_raw", 30), metric("/imu/data", 100), metric("/odom", 20), metric("/diagnostics", 1)],
  });
  const robot = page.getByRole("region", { name: "Monitored Topics" });
  await expect(robot.locator("tbody tr")).toHaveCount(4);
  await expect(robot).toContainText("Image delivery supports the robot’s vision.");
  await expect(page.locator(".telemetry-pipeline")).toContainText("No gateway streams in this recording");
});
