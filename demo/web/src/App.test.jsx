import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class FakeEventSource {
  static instances = [];
  constructor() {
    this.listeners = {};
    FakeEventSource.instances.push(this);
  }
  addEventListener(type, callback) {
    this.listeners[type] = callback;
  }
  emit(type, payload) {
    this.listeners[type]?.({ data: JSON.stringify(payload) });
  }
  close() {}
}

const DEFAULT_DATASET_FOR_TEST = {
  source: "public_dataset",
  file_format: "rosbag1",
  status: "ready",
  selectable: true,
  supports_camera_dropout: true,
};

describe("ROS Workbench", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url) =>
        Promise.resolve({
          ok: true,
          json: async () =>
            url.includes("/api/health")
              ? {
                  status: "ready",
                  services: {
                    kafka: "ready",
                    flink: "ready",
                    flink_job: "ready",
                    projection_api: "ready",
                    replayer: "ready",
                  },
                }
              : {
                  topics: [],
                  anomalies: [],
                  incident_history: [],
                  completion: {},
                  consumer_offsets: [],
                  mission_progress_ms: 0,
                },
        }),
      ),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("switches workspace tabs with keyboard controls and a health-view entry point", () => {
    render(<App />);
    const health = screen.getByRole("tab", { name: "Telemetry Health" });
    const investigation = screen.getByRole("tab", {
      name: "Localization Investigation",
    });
    expect(health).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(health, { key: "ArrowRight" });
    expect(investigation).toHaveFocus();
    expect(investigation).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tabpanel", { name: "Localization Investigation" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Monitored Topics" }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(investigation, { key: "Home" });
    expect(health).toHaveFocus();
    fireEvent.click(
      screen.getByRole("button", { name: "Open Localization Investigation" }),
    );
    expect(investigation).toHaveAttribute("aria-selected", "true");
  });

  it("retains unavailable topic evidence and clears the connection warning on reconnect", async () => {
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    const source = FakeEventSource.instances.at(-1);
    act(() =>
      source.emit("snapshot", {
        run_id: "retained-run",
        dataset_id: "warehouse_run_17",
        robot_id: "r1",
        run: { payload: { status: "running" } },
        topics: [
          {
            topic: "/scan",
            robot_id: "r1",
            payload: { status: "healthy", mean_rate_hz: 10 },
          },
        ],
        anomalies: [],
        incident_history: [],
        completion: {},
        consumer_offsets: [],
        mission_progress_ms: 1000,
      }),
    );
    act(() => source.onerror());
    expect(
      screen.getByRole("button", { name: "Lidar", exact: true }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Telemetry API unavailable",
    );
    expect(
      within(
        screen.getByRole("region", { name: "Monitored Topics" }),
      ).getByText("unavailable"),
    ).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(2));
    act(() => FakeEventSource.instances.at(-1).onopen());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("opens Import recording idempotently when clicked twice", () => {
    const { container } = render(<App />);
    const dialog = container.querySelector("dialog");
    dialog.showModal = vi.fn(() => {
      dialog.open = true;
    });
    const addData = screen.getByRole("button", { name: /import recording/i });
    fireEvent.click(addData);
    fireEvent.click(addData);
    expect(dialog.showModal).toHaveBeenCalledTimes(1);
  });

  it("renders an unavailable catalog entry when status and source are missing", async () => {
    const originalFetch = fetch.getMockImplementation();
    fetch.mockImplementation((url) =>
      url.includes("/api/datasets")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              default_dataset_id: "missing",
              datasets: [
                {
                  dataset_id: "missing",
                  name: "Incomplete recording",
                  selectable: false,
                },
              ],
            }),
          })
        : originalFetch(url),
    );
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("option", {
          name: "Incomplete recording — unavailable",
        }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Start mission" }),
    ).toBeDisabled();
  });

  it("labels the source as recorded replay and exposes mission controls", async () => {
    render(<App />);
    expect(screen.getByText("Recorded replay")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start mission" }),
      ).toBeEnabled(),
    );
    expect(screen.getByText("Camera dropout")).toBeInTheDocument();
    expect(screen.getByText("Streaming job")).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "Stack readiness" }),
      ).getAllByText("ready").length,
    ).toBe(5);
  });

  it("explains why camera fault injection is limited to real time", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("radio", { name: "5× accelerated" }));
    expect(screen.getByRole("radio", { name: "5× accelerated" })).toBeChecked();
    fireEvent.change(screen.getByLabelText("Scenario"), {
      target: { value: "camera-dropout" },
    });
    expect(screen.getByRole("radio", { name: "1× real time" })).toBeChecked();
    expect(
      screen.getByText(/processing-time watchdog stays tied to real time/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "5× accelerated" }),
    ).toBeDisabled();
  });

  it("shows a live robot and prevents replay actions on its session", async () => {
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    act(() =>
      FakeEventSource.instances.at(-1).emit("snapshot", {
        run_id: "live-example",
        robot_id: "robot-live-1",
        dataset_id: "live-ros2",
        dataset_name: "Live ROS session",
        source_format: "live_ros2",
        source: "live_ros2",
        run: { payload: { status: "running" } },
        topic_count: 6,
        topics: [
          { topic: "/scan", payload: { status: "ok", mean_rate_hz: 10 } },
        ],
        anomalies: [],
        incident_history: [],
        completion: {},
        consumer_offsets: [],
        mission_progress_ms: 1000,
      }),
    );
    expect(screen.getByText("Live ROS 2")).toBeInTheDocument();
    expect(screen.getByText("robot-live-1")).toBeInTheDocument();
    expect(screen.getByText("/scan")).toBeInTheDocument();
    for (const name of ["Start mission", "Pause", "Resume", "Restart"]) {
      const action = screen.queryByRole("button", { name });
      if (action) expect(action).toBeDisabled();
    }
    act(() =>
      FakeEventSource.instances.at(-1).emit("completion_failed", {
        run_id: "older-run",
        detail: "Old run failed",
      }),
    );
    expect(screen.queryByText(/Old run failed/)).not.toBeInTheDocument();
  });

  it("switches to an installed public dataset and sends it to replay", async () => {
    fetch.mockImplementation((url, options = {}) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.includes("/api/datasets")
            ? {
                default_dataset_id: "warehouse_run_17",
                datasets: [
                  {
                    dataset_id: "warehouse_run_17",
                    name: "Warehouse Run 17",
                    source: "built_in",
                    file_format: "rosbag2_mcap",
                    status: "ready",
                    selectable: true,
                    supports_camera_dropout: true,
                  },
                  {
                    dataset_id: "lilocbench_dynamics_0",
                    name: "LILocBench · Dynamics 0",
                    description: "Dynamic people mission",
                    source: "public_dataset",
                    file_format: "rosbag1",
                    status: "ready",
                    selectable: true,
                    supports_camera_dropout: false,
                    size_bytes: 38_063_988,
                  },
                  {
                    dataset_id: "openloris_scene_cafe1_1_2",
                    name: "OpenLORIS Scene · Cafe 1-1",
                    status: "not_installed",
                    selectable: false,
                  },
                ],
              }
            : url.includes("/api/health")
              ? {
                  status: "ready",
                  services: {
                    kafka: "ready",
                    flink: "ready",
                    flink_job: "ready",
                    projection_api: "ready",
                    replayer: "ready",
                  },
                }
              : options.method === "POST"
                ? { status: "running" }
                : {
                    topics: [],
                    anomalies: [],
                    incident_history: [],
                    completion: {},
                    consumer_offsets: [],
                    mission_progress_ms: 0,
                  },
      }),
    );

    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /LILocBench/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("option", { name: /OpenLORIS/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Dataset"), {
      target: { value: "lilocbench_dynamics_0" },
    });
    expect(screen.getByText("Dynamic people mission")).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Camera dropout" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Start mission" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/replay/start"),
        expect.objectContaining({
          body: expect.stringContaining('"dataset_id":"lilocbench_dynamics_0"'),
        }),
      ),
    );
  });

  it("restores the dataset for the current run after a page reload", async () => {
    fetch.mockImplementation((url) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.includes("/api/datasets")
            ? {
                default_dataset_id: "warehouse_run_17",
                datasets: [
                  {
                    ...DEFAULT_DATASET_FOR_TEST,
                    dataset_id: "warehouse_run_17",
                    name: "Warehouse Run 17",
                  },
                  {
                    ...DEFAULT_DATASET_FOR_TEST,
                    dataset_id: "lilocbench_dynamics_0",
                    name: "LILocBench · Dynamics 0",
                    supports_camera_dropout: false,
                  },
                ],
              }
            : url.includes("/api/health")
              ? {
                  status: "ready",
                  services: {
                    kafka: "ready",
                    flink: "ready",
                    flink_job: "ready",
                    projection_api: "ready",
                    replayer: "ready",
                  },
                }
              : {
                  run_id: "run-liloc",
                  dataset_id: "lilocbench_dynamics_0",
                  dataset_name: "LILocBench · Dynamics 0",
                  mission_duration_ms: 159_978,
                  topic_count: 7,
                  run: { payload: { status: "summary_ready" } },
                  topics: [],
                  anomalies: [],
                  incident_history: [],
                  completion: { verified: true, summary_file_count: 7 },
                  consumer_offsets: [],
                  mission_progress_ms: 159_978,
                },
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByLabelText("Dataset")).toHaveValue(
        "lilocbench_dynamics_0",
      ),
    );
    expect(screen.getByText("02:39 / 02:39")).toBeInTheDocument();
  });

  it("shows checkpoint freshness and authoritative event counters", async () => {
    fetch.mockImplementation((url) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.includes("/api/health")
            ? {
                status: "ready",
                services: {
                  kafka: "ready",
                  flink: "ready",
                  flink_job: "ready",
                  projection_api: "ready",
                  replayer: "ready",
                },
              }
            : url.includes("/api/flink/summary")
              ? {
                  status: "available",
                  checkpoints: { id: 7, status: "COMPLETED", age_ms: 2_000 },
                  events_processed: 1_000,
                  accepted_late_events: 2,
                  duplicate_events: 1,
                  too_late_events: 0,
                }
              : {
                  topics: [],
                  anomalies: [],
                  incident_history: [],
                  completion: {},
                  consumer_offsets: [],
                  mission_progress_ms: 0,
                },
      }),
    );
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByText(/checkpoint completed #7 \(2.0 s old\)/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        /Processed 1000 · accepted late 2 · duplicate 1 · too late 0/i,
      ),
    ).toBeInTheDocument();
  });

  it.each([false, true])(
    "renders localization metrics with optional heading signal: %s",
    async (useHeading) => {
      fetch.mockImplementation((url) =>
        Promise.resolve({
          ok: true,
          json: async () =>
            url.includes("/api/health")
              ? {
                  status: "ready",
                  services: {
                    kafka: "ready",
                    flink: "ready",
                    flink_job: "ready",
                    projection_api: "ready",
                    replayer: "ready",
                  },
                }
              : url.includes("/api/localization/evaluation")
                ? {
                    status: "available",
                    summary: {
                      detector_inputs: useHeading
                        ? [
                            "particle_position_spread_m",
                            "estimated_pose_jump_m",
                            "particle_heading_spread_rad",
                          ]
                        : undefined,
                      thresholds: useHeading
                        ? { recovery_hold_ms: 250 }
                        : undefined,
                      sample_metrics: {
                        precision: 0.856,
                        recall: 0.468,
                        f1: 0.605,
                      },
                      event_metrics: {
                        precision: 0.842,
                        recall: 0.667,
                        false_alarm_event_count: 3,
                      },
                    },
                    evaluation_start_timestamp_ns: 0,
                    trajectory: [
                      {
                        segment_id: 0,
                        elapsed_ms: 0,
                        ground_truth_x: 0,
                        ground_truth_y: 0,
                        estimated_x: 0,
                        estimated_y: 0,
                        label_failure: false,
                        detector_failure: false,
                      },
                      {
                        segment_id: 0,
                        elapsed_ms: 1000,
                        ground_truth_x: 1,
                        ground_truth_y: 0,
                        estimated_x: 1.2,
                        estimated_y: 0.2,
                        label_failure: true,
                        detector_failure: false,
                      },
                      {
                        segment_id: 1,
                        elapsed_ms: 2000,
                        ground_truth_x: 5,
                        ground_truth_y: 5,
                        estimated_x: 5,
                        estimated_y: 5,
                        label_failure: false,
                        detector_failure: false,
                      },
                      {
                        segment_id: 1,
                        elapsed_ms: 3000,
                        ground_truth_x: 6,
                        ground_truth_y: 5,
                        estimated_x: 6.1,
                        estimated_y: 5.1,
                        label_failure: false,
                        detector_failure: false,
                      },
                    ],
                    event_matches: [
                      {
                        expected_event_id: "expected-1",
                        expected_start_timestamp_ns: 1_000_000_000,
                        observed_start_timestamp_ns: 1_250_000_000,
                        observed_end_timestamp_ns: 1_750_000_000,
                        detected: true,
                        onset_lag_ms: 250,
                      },
                      {
                        expected_event_id: "expected-2",
                        expected_start_timestamp_ns: 2_000_000_000,
                        observed_start_timestamp_ns: null,
                        observed_end_timestamp_ns: null,
                        detected: false,
                        onset_lag_ms: null,
                      },
                    ],
                  }
                : url.includes("/api/flink/summary")
                  ? { status: "available" }
                  : {
                      topics: [],
                      anomalies: [],
                      incident_history: [],
                      completion: {},
                      consumer_offsets: [],
                      mission_progress_ms: 0,
                    },
        }),
      );

      const { container } = render(<App />);

      await waitFor(() =>
        expect(screen.getByText("0.856")).toBeInTheDocument(),
      );
      fireEvent.click(
        screen.getByRole("tab", { name: "Localization Investigation" }),
      );
      await waitFor(() =>
        expect(
          screen.getByRole("img", {
            name: /ground-truth and amcl estimated trajectories/i,
          }),
        ).toBeInTheDocument(),
      );
      expect(
        container.querySelectorAll(".trajectory-ground-truth"),
      ).toHaveLength(2);
      expect(container.querySelectorAll(".trajectory-estimated")).toHaveLength(
        2,
      );
      expect(screen.getByText("0.842")).toBeInTheDocument();
      expect(
        screen.getByText(/Detailed investigation evidence is unavailable/),
      ).toBeInTheDocument();
      if (useHeading)
        expect(
          screen.getByText(/particle_heading_spread_rad/),
        ).toBeInTheDocument();
      expect(
        screen.getByText(/ground truth and published labels are scoring-only/i),
      ).toBeInTheDocument();
    },
  );

  it("replaces stale health with an actionable unavailable state", async () => {
    fetch.mockImplementation((url) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.includes("/api/health")
            ? {
                status: "ready",
                services: {
                  kafka: "ready",
                  flink: "ready",
                  flink_job: "ready",
                  projection_api: "ready",
                  replayer: "ready",
                },
              }
            : url.includes("flink")
              ? { status: "available" }
              : {
                  run_id: "run-1",
                  run: { payload: { status: "running" } },
                  robot_health: { payload: { status: "healthy" } },
                  topics: [],
                  anomalies: [],
                  incident_history: [],
                  completion: {},
                  consumer_offsets: [],
                  mission_progress_ms: 0,
                },
      }),
    );
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    FakeEventSource.instances[0].onopen();
    await waitFor(() =>
      expect(screen.getByText("healthy")).toBeInTheDocument(),
    );
    FakeEventSource.instances[0].onerror();
    await waitFor(() =>
      expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "reconnect automatically",
    );
  });

  it("does not preserve healthy state when a streaming authority is unavailable", async () => {
    fetch.mockImplementation((url) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.includes("/api/health")
            ? {
                status: "starting",
                services: {
                  kafka: "unknown",
                  flink: "ready",
                  flink_job: "ready",
                  projection_api: "ready",
                  replayer: "ready",
                },
              }
            : url.includes("flink")
              ? { status: "available" }
              : {
                  run_id: "run-1",
                  run: { payload: { status: "running" } },
                  robot_health: { payload: { status: "healthy" } },
                  topics: [
                    {
                      topic: "/camera/image_raw",
                      payload: { status: "healthy" },
                    },
                  ],
                  anomalies: [],
                  incident_history: [],
                  completion: {},
                  consumer_offsets: [],
                  mission_progress_ms: 30_000,
                },
      }),
    );
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    FakeEventSource.instances[0].onopen();

    await waitFor(() =>
      expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0),
    );
    expect(screen.queryByText("healthy")).not.toBeInTheDocument();
    expect(screen.getByText(/docker compose ps/)).toBeInTheDocument();
  });

  it("surfaces durable summary verification failures", async () => {
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    FakeEventSource.instances[0].emit("completion_failed", {
      detail:
        "Summary files did not satisfy the durable four-topic contract within 60 seconds",
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "four-topic contract",
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Flink checkpoint");
  });

  it("renders healthy, incident, recovered, and completed mission states", async () => {
    fetch.mockImplementation((url) =>
      url.includes("/api/health")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              status: "ready",
              services: {
                kafka: "ready",
                flink: "ready",
                flink_job: "ready",
                projection_api: "ready",
                replayer: "ready",
              },
            }),
          })
        : new Promise(() => {}),
    );
    render(<App />);
    await waitFor(() =>
      expect(FakeEventSource.instances.length).toBeGreaterThan(0),
    );
    const events = FakeEventSource.instances[0];
    await act(async () => events.onopen());
    const base = {
      run_id: "run-1",
      run: { payload: { status: "running" } },
      robot_health: { payload: { status: "healthy" } },
      topics: [
        {
          topic: "/camera/image_raw",
          payload: {
            status: "healthy",
            mean_rate_hz: 30,
            expected_rate_hz: 30,
            message_count: 300,
          },
        },
      ],
      anomalies: [],
      incident_history: [],
      completion: {},
      consumer_offsets: [],
      mission_progress_ms: 30_000,
    };
    await act(async () => events.emit("snapshot", base));
    await waitFor(() =>
      expect(screen.getAllByText("healthy").length).toBeGreaterThan(0),
    );

    const active = {
      anomaly_id: "incident-1",
      revision: 0,
      condition_type: "GAP",
      status: "active",
      topic: "/camera/image_raw",
    };
    await act(async () =>
      events.emit("snapshot", {
        ...base,
        robot_health: {
          payload: {
            status: "degraded",
            primary_anomaly: {
              condition_type: "GAP",
              topic: "/camera/image_raw",
            },
          },
        },
        anomalies: [active],
        incident_history: [active],
      }),
    );
    await waitFor(() => expect(screen.getAllByText("GAP").length).toBe(2));
    expect(screen.getByText("degraded")).toBeInTheDocument();
    expect(document.querySelector(".primary-anomaly")).toHaveTextContent(
      "/camera/image_raw",
    );

    const recovered = { ...active, revision: 1, status: "recovered" };
    await act(async () =>
      events.emit("snapshot", {
        ...base,
        anomalies: [recovered],
        incident_history: [active, recovered],
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("recovered")).toBeInTheDocument(),
    );

    await act(async () =>
      events.emit("snapshot", {
        ...base,
        run: { payload: { status: "summary_ready" } },
        completion: { verified: true, summary_file_count: 4 },
        mission_progress_ms: 90_000,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("completed")).toBeInTheDocument(),
    );
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });
});
