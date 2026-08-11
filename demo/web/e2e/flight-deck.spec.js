import { expect, test } from "@playwright/test";

test("completed recorded mission is operationally trustworthy", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Robot Telemetry/ })).toBeVisible();
  await expect(page.getByText("RECORDED REPLAY")).toBeVisible();

  const readiness = page.getByRole("region", { name: "Stack readiness" });
  for (const service of ["Kafka", "Flink cluster", "Streaming job", "Projection API", "MCAP replayer"]) {
    await expect(readiness.getByText(service, { exact: true })).toBeVisible();
  }
  await expect(readiness.getByText("ready", { exact: true })).toHaveCount(5, { timeout: 30_000 });

  const mission = page.locator(".mission-control");
  await expect(mission.locator(".status-pill")).toHaveText("completed", { timeout: 30_000 });
  await expect(mission.getByText("01:30 / 01:30")).toBeVisible();

  await expect(page.locator(".topic-card")).toHaveCount(4);
  await expect(page.locator(".topic-card .status-pill")).toHaveCount(4);
  await page.locator(".technical summary").click();
  await expect(page.getByText("4 / 4 topic summaries independently verified")).toBeVisible();
  await expect(page.getByText("Flink job available")).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("camera dropout remains legible after recovery", async ({ page }) => {
  test.skip(!process.env.EXPECT_DROPOUT, "requires the completed dropout Compose mission");
  await page.goto("/");

  await expect(page.locator(".mission-control .status-pill")).toHaveText("completed", { timeout: 30_000 });
  const timeline = page.locator(".incidents");
  await expect(timeline.getByText("GAP", { exact: true })).toHaveCount(2);
  await expect(timeline.getByText("recovered", { exact: true })).toBeVisible();
  await expect(page.locator(".robot-overview .status-pill")).toHaveText("healthy");
});

test("state flow never leaves stale health behind", async ({ page }) => {
  let health = {
    status: "starting",
    services: { kafka: "unknown", flink: "unknown", flink_job: "unknown", projection_api: "ready", replayer: "unknown" },
  };
  await page.addInitScript(() => {
    class FakeEventSource {
      constructor() {
        this.listeners = {};
        window.__flightDeckEvents = this;
        window.setTimeout(() => this.onopen?.(), 0);
      }
      addEventListener(type, callback) { this.listeners[type] = callback; }
      close() {}
    }
    window.EventSource = FakeEventSource;
    window.__emitFlightDeckSnapshot = (payload) => {
      window.__flightDeckEvents.listeners.snapshot?.({ data: JSON.stringify(payload) });
    };
    window.__failFlightDeckEvents = () => window.__flightDeckEvents.onerror?.();
  });
  await page.route("**/api/health", (route) => route.fulfill({ status: health.status === "ready" ? 200 : 503, json: health }));
  await page.route("**/api/flink/summary", (route) => route.fulfill({ json: { status: "available" } }));
  await page.route("**/api/runs/current/snapshot", (route) => route.fulfill({ json: {
    run_id: null, run: null, robot_health: null, topics: [], anomalies: [], incident_history: [],
    completion: { verified: false, summary_file_count: 0 }, consumer_offsets: [], mission_progress_ms: 0,
  } }));

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start mission" })).toBeDisabled();
  health = {
    status: "ready",
    services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" },
  };
  await expect(page.getByRole("button", { name: "Start mission" })).toBeEnabled({ timeout: 5000 });

  const base = {
    run_id: "run-state-flow",
    run: { payload: { status: "running" } },
    robot_health: { payload: { status: "healthy" } },
    topics: [{ topic: "/camera/image_raw", payload: { status: "healthy", mean_rate_hz: 30, expected_rate_hz: 30, message_count: 300 } }],
    anomalies: [], incident_history: [], completion: { verified: false, summary_file_count: 0 },
    consumer_offsets: [], mission_progress_ms: 30_000,
  };
  await page.evaluate((snapshot) => window.__emitFlightDeckSnapshot(snapshot), base);
  await expect(page.locator(".robot-overview .status-pill")).toHaveText("healthy");

  await page.evaluate((snapshot) => window.__emitFlightDeckSnapshot(snapshot), {
    ...base, run: { payload: { status: "paused" } },
  });
  await expect(page.locator(".mission-control .status-pill")).toHaveText("paused");

  const active = { anomaly_id: "incident-1", revision: 0, condition_type: "GAP", status: "active", topic: "/camera/image_raw" };
  await page.evaluate((snapshot) => window.__emitFlightDeckSnapshot(snapshot), {
    ...base, robot_health: { payload: { status: "degraded" } }, anomalies: [active], incident_history: [active],
  });
  await expect(page.locator(".robot-overview .status-pill")).toHaveText("degraded");
  await expect(page.getByText("GAP", { exact: true })).toBeVisible();

  const recovered = { ...active, revision: 1, status: "recovered" };
  await page.evaluate((snapshot) => window.__emitFlightDeckSnapshot(snapshot), {
    ...base, anomalies: [recovered], incident_history: [active, recovered],
  });
  await expect(page.getByText("recovered", { exact: true })).toBeVisible();

  await page.evaluate((snapshot) => window.__emitFlightDeckSnapshot(snapshot), {
    ...base, run: { payload: { status: "summary_ready" } }, completion: { verified: true, summary_file_count: 4 }, mission_progress_ms: 90_000,
  });
  await expect(page.locator(".mission-control .status-pill")).toHaveText("completed");

  await page.evaluate(() => window.__failFlightDeckEvents());
  await expect(page.locator(".robot-overview .status-pill")).toHaveText("unavailable");
  await expect(page.getByRole("alert")).toContainText("reconnect automatically");
});

test("mobile controls and readiness remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("region", { name: "Stack readiness" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start mission" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Scenario" })).toBeVisible();
  await expect(page.locator(".topic-card")).toHaveCount(4);
  await expect(page.locator("main")).toHaveCSS("width", "390px");
});
