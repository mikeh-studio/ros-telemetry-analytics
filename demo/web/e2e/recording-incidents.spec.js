import { expect, test } from "@playwright/test";

const analysisId = "a".repeat(32);
const incidentId = "b".repeat(64);
const summary = {
  incident_id: incidentId,
  title: "Image content warning",
  topics: ["/camera"],
  start_s: 1,
  end_s: 2,
  member_count: 1,
  explanation_status: "supported",
};
const detail = {
  ...summary,
  analysis_id: analysisId,
  source_sha256: "c".repeat(64),
  catalog_version: "recording-explanations-v1",
  grouping_version: "recording-overlap-v1",
  display_start_s: 0,
  display_end_s: 4,
  focus_s: 1,
  plot_hints: [{ topic: "/camera", field: "mean_intensity" }],
  observations: [
    {
      rule_id: "dark_frames",
      text: "Two analyzed frames had mean intensity below 20.",
      evidence_refs: ["event"],
    },
  ],
  evidence: [
    {
      id: "event",
      topic: "/camera",
      field: "mean_intensity",
      start_timestamp_ns: "1000000000",
      end_timestamp_ns: "2000000000",
      clock: "recorded_receive",
      availability: "available",
      reason: "Structured detector provenance",
      parameters: { sample_count: 2, threshold: 20 },
    },
  ],
  possibilities: [{ text: "Lighting changes", status: "untested" }],
  limits: ["Camera malfunction is not established."],
  next_checks: [
    {
      text: "Collect exposure data if unavailable.",
      reason: "Additional evidence needed",
      evidence_refs: [],
    },
  ],
  member_events: [],
  member_offset: 0,
  next_member_offset: null,
};

test("offline incident inspection links evidence and remains usable on a narrow screen", async ({
  page,
}, testInfo) => {
  const errors = [];
  const requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      /same key|unique.*key/.test(message.text())
    )
      errors.push(message.text());
  });
  await page.addInitScript(() => {
    localStorage.setItem("workbench.dataset", "test");
    localStorage.setItem("workbench.view", "recordings");
    window.EventSource = class {
      addEventListener() {}
      close() {}
    };
  });
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    let json = {};
    if (url.pathname.endsWith("/datasets"))
      json = {
        default_dataset_id: "test",
        datasets: [
          {
            dataset_id: "test",
            name: "Synthetic recording",
            selectable: false,
            capabilities: {
              recordings: "ready",
              health: "unavailable",
              localization: "not_prepared",
            },
          },
        ],
      };
    else if (url.pathname.endsWith("/snapshot"))
      json = {
        run_id: null,
        topics: [],
        anomalies: [],
        incident_history: [],
        observed_signals: [],
        topic_history: [],
        completion: {},
      };
    else if (url.pathname.endsWith("/health"))
      json = { status: "unavailable", services: {} };
    else if (url.pathname.endsWith(`/incidents/${incidentId}`)) json = detail;
    else if (url.pathname.endsWith("/incidents"))
      json = {
        analysis_id: analysisId,
        incidents: [summary],
        total_count: 1,
        returned_count: 1,
        next_offset: null,
      };
    else if (url.pathname.endsWith("/interval"))
      json = {
        analysis_id: analysisId,
        events: [],
        event_count: 0,
        previews: [],
        series: [
          {
            topic: "/camera",
            field: "mean_intensity",
            unit: "0–255",
            frame: "camera",
            domain: "images",
            points: [{ t: 1, count: 2, min: 5, max: 10, value: 7.5 }],
          },
        ],
      };
    else if (url.pathname.endsWith("/investigations/test"))
      json = {
        dataset_id: "test",
        analysis_id: analysisId,
        origin_ns: "0",
        duration_s: 10,
        message_count: 100,
        incident_count: 1,
        cases: [],
        reference_topics: [],
        coverage: [],
        topic_health: [],
        integrity: "local_digest_only",
        source_sha256: "c".repeat(64),
      };
    return route.fulfill({ json });
  });
  await page.goto("/");
  const select = page.getByRole("button", { name: /Image content warning/ });
  await expect(select).toBeVisible();
  await select.focus();
  await page.keyboard.press("Enter");
  const explanation = page.getByRole("article", {
    name: "Incident explanation",
  });
  await expect(explanation).toContainText(
    "Camera malfunction is not established.",
  );
  await explanation
    .getByRole("button", { name: "Inspect /camera · mean_intensity" })
    .click();
  await expect(
    page.getByRole("img", { name: "mean_intensity for /camera" }),
  ).toHaveCount(1);
  expect(
    requests.some((u) => u.searchParams.get("field") === "mean_intensity"),
  ).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(explanation).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("incident-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Inspect interval", exact: true })
    .click();
  await expect(explanation).toHaveCount(0);
  expect(requests.some((u) => u.pathname.includes("replay"))).toBeFalsy();
  expect(errors).toEqual([]);
});

test("prepared TUM VI and LILocBench incidents reconcile through the real API and UI", async ({
  page,
}, testInfo) => {
  test.skip(
    !process.env.RECORDING_INCIDENTS_LIVE,
    "requires prepared local comparison recordings",
  );
  test.setTimeout(60_000);
  const api = process.env.RECORDING_INCIDENTS_API || "http://127.0.0.1:8011";
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      /same key|unique.*key/.test(message.text())
    )
      errors.push(message.text());
  });
  await page.addInitScript(() => {
    localStorage.setItem("workbench.dataset", "tum_vi_room4_512");
    localStorage.setItem("workbench.view", "recordings");
  });
  const metaResponse = await page.request.get(
    `${api}/api/investigations/tum_vi_room4_512`,
  );
  expect(metaResponse.ok()).toBeTruthy();
  const metadata = await metaResponse.json();
  const listResponse = await page.request.get(
    `${api}/api/investigations/tum_vi_room4_512/incidents?analysis_id=${metadata.analysis_id}&limit=100`,
  );
  const list = await listResponse.json();
  const target = list.incidents.find(
    (i) =>
      i.start_s > 102.6 &&
      i.start_s < 103 &&
      i.topics.includes("/cam0/image_raw"),
  );
  expect(target).toBeTruthy();
  await page.goto("/");
  const generated = page.getByRole("region", { name: "Detected incidents" });
  await expect(generated).toBeVisible({ timeout: 20_000 });
  for (let n = 0; n < Math.floor(list.incidents.indexOf(target) / 20); n++) {
    await generated.getByRole("button", { name: "Next incidents" }).click();
    await expect(generated.getByRole("status")).toHaveCount(0);
  }
  await generated
    .getByRole("button")
    .filter({
      hasText: `${target.start_s.toFixed(3)}–${target.end_s.toFixed(3)}`,
    })
    .click();
  const explanation = page.getByRole("article", {
    name: "Incident explanation",
  });
  await expect(explanation).toContainText(
    "8 analyzed frames on /cam0/image_raw",
  );
  await expect(explanation).toContainText(
    "No recorded receive interval exceeded",
  );
  await explanation
    .getByRole("button", {
      name: "Inspect /cam0/image_raw · mean_intensity",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("img", { name: "mean_intensity for /cam0/image_raw" }),
  ).toHaveCount(1);
  await explanation.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("camera-incident-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("combobox", { name: "Dataset", exact: true }).click();
  await page
    .getByRole("option")
    .filter({ hasText: "LILocBench · Dynamics 0" })
    .click();
  await expect(
    page.getByText("8 analyzed frames on /cam0/image_raw", { exact: false }),
  ).toHaveCount(0);
  await generated.getByRole("button").filter({ hasText: "65.781" }).click();
  await expect(explanation).toContainText(
    "13 commands on /dingo_velocity_controller/cmd_vel",
  );
  await expect(explanation).toContainText(
    "nearest recorded timestamp within 500 ms",
  );
  await explanation
    .getByRole("button", {
      name: "Inspect /dingo_velocity_controller/odom · angular_z",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("img", {
      name: "angular_z for /dingo_velocity_controller/odom",
    }),
  ).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("motion-incident-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
