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
    localStorage.clear();
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

  it("switches workspace tabs with keyboard controls and pointer input", () => {
    render(<App />);
    const health = screen.getByRole("tab", { name: "Telemetry" });
    const investigation = screen.getByRole("tab", {
      name: "Localization",
    });
    expect(health).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(health, { key: "ArrowRight" });
    const recordings = screen.getByRole("tab", {
      name: "Recording",
    });
    expect(recordings).toHaveFocus();
    fireEvent.keyDown(recordings, { key: "ArrowRight" });
    expect(investigation).toHaveFocus();
    expect(investigation).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tabpanel", { name: "Localization" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Monitored Topics" }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(investigation, { key: "Home" });
    expect(health).toHaveFocus();
    fireEvent.click(investigation);
    expect(investigation).toHaveAttribute("aria-selected", "true");
  });

  it("offers prepared evidence without empty monitors or redundant scenario controls", async () => {
    const original = fetch.getMockImplementation();
    fetch.mockImplementation((url) =>
      url.includes("/api/datasets")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              default_dataset_id: "walking",
              datasets: [
                {
                  dataset_id: "walking",
                  name: "Walking XYZ",
                  selectable: true,
                  source: "public_dataset",
                  capabilities: {
                    health: "ready",
                    recordings: "ready",
                    localization: "unsupported",
                  },
                },
              ],
            }),
          })
        : url.includes("/api/health")
          ? Promise.resolve({
              ok: false,
              json: async () => ({
                status: "starting",
                services: { projection_api: "ready" },
              }),
            })
          : original(url),
    );
    render(<App />);
    const inspect = await screen.findByRole("button", {
      name: "Inspect sensor evidence",
    });
    expect(screen.queryByLabelText("Fault injection")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Monitor" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Telemetry" }),
    ).toHaveAccessibleDescription("Services not ready");
    expect(
      screen.getByRole("tab", { name: "Recording" }),
    ).toHaveAccessibleDescription("Ready");
    expect(
      screen.getByRole("tab", { name: "Localization" }),
    ).toHaveAccessibleDescription("Analysis not prepared");
    expect(screen.getAllByText("Replay services are not ready.")).toHaveLength(
      1,
    );
    expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
    const about = screen.getByRole("button", { name: "About this recording" });
    expect(about).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(about);
    expect(
      screen.getByRole("button", { name: "Refresh dataset catalog" }),
    ).toBeVisible();
    fireEvent.click(about);
    fireEvent.click(inspect);
    expect(screen.getByRole("tab", { name: "Recording" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByLabelText("Dataset")).toHaveValue("walking");
    expect(
      screen.getByRole("button", { name: "Upload recording" }),
    ).toBeVisible();
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
    act(() => source.emit("snapshot", { run_id: "obsolete-connection" }));
    expect(
      within(
        screen.getByRole("region", { name: "Monitored Topics" }),
      ).getByText("unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Telemetry API unavailable",
    );
    act(() =>
      FakeEventSource.instances.at(-1).emit("snapshot", {
        run_id: "retained-run",
        dataset_id: "warehouse_run_17",
        robot_id: "r1",
        run: { payload: { status: "running" } },
        topics: [
          {
            topic: "/scan",
            robot_id: "r1",
            payload: { status: "degraded", mean_rate_hz: 0 },
          },
        ],
        anomalies: [],
        incident_history: [],
        completion: {},
        consumer_offsets: [],
        mission_progress_ms: 2000,
      }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "Monitored Topics" }),
      ).getByText("degraded"),
    ).toBeInTheDocument();
  });

  it("opens Import recording idempotently when clicked twice", () => {
    const { container } = render(<App />);
    const dialog = container.querySelector("dialog");
    dialog.showModal = vi.fn(() => {
      dialog.open = true;
    });
    const addData = screen.getByRole("button", { name: /upload recording/i });
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
    fireEvent.click(screen.getByLabelText("Dataset"));
    await waitFor(() =>
      expect(
        screen.getByRole("option", {
          name: "Incomplete recording — unavailable",
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
  });

  it("labels the source as recorded replay and exposes mission controls", async () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Replay", exact: true }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start replay" }),
      ).toBeEnabled(),
    );
    expect(
      screen.getByRole("tab", { name: "Telemetry" }),
    ).toHaveAccessibleDescription("Ready");
    expect(screen.getByText("Camera dropout")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Connection details"));
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
    fireEvent.change(screen.getByLabelText("Fault injection"), {
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
    for (const name of ["Start replay", "Pause", "Resume", "Restart"]) {
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
    fireEvent.click(screen.getByLabelText("Dataset"));
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /LILocBench/ }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("option", { name: /OpenLORIS/ }),
    ).not.toBeDisabled();
    fireEvent.click(screen.getByRole("option", { name: /LILocBench/ }));
    expect(screen.getByText("Dynamic people mission")).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Camera dropout" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start replay" }));

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
                  run_id: "checkpoint-run",
                  dataset_id: "warehouse_run_17",
                  run: { payload: { status: "running" } },
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
            url.includes("/api/datasets")
              ? {
                  default_dataset_id: "localization:test",
                  datasets: [
                    {
                      dataset_id: "localization:test",
                      name: "Test evaluation",
                      capabilities: { localization: "ready" },
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
                : url.includes("/api/localization/evaluation")
                  ? {
                      status: "available",
                      dataset_id: "localization:test",
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
      fireEvent.click(screen.getByRole("tab", { name: "Localization" }));
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

  it.each(["readiness", "connection"])(
    "keeps a healthy pipeline collapsed while initial %s is pending",
    async (delayed) => {
      let resolveHealth;
      fetch.mockImplementation((url) =>
        url.includes("/api/health")
          ? new Promise((resolve) => {
              resolveHealth = resolve;
            })
          : new Promise(() => {}),
      );
      const { container } = render(<App />);
      const events = FakeEventSource.instances[0];
      const healthy = {
        run_id: "startup-run",
        run: { payload: { status: "running" } },
        robot_health: { payload: { status: "healthy" } },
        topics: [
          {
            topic: "/_telemetry/gateway_health",
            payload: { health_status: "healthy" },
          },
        ],
        anomalies: [],
        incident_history: [],
        completion: {},
        consumer_offsets: [],
        mission_progress_ms: 0,
      };
      const readiness = () =>
        resolveHealth({
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
        });
      await act(async () => {
        events.emit("snapshot", healthy);
        if (delayed === "readiness") events.onopen();
        else readiness();
      });
      const panel = container.querySelector(".telemetry-pipeline");
      expect(panel).not.toHaveAttribute("open");
      expect(
        within(panel).getByText("Checking connection"),
      ).toBeInTheDocument();
      expect(
        within(
          screen.getByRole("region", { name: "Operations status" }),
        ).queryByText("healthy"),
      ).not.toBeInTheDocument();
      await act(async () => {
        if (delayed === "readiness") readiness();
        else events.onopen();
      });
      expect(within(panel).getByText("Monitoring")).toBeInTheDocument();
      expect(panel).not.toHaveAttribute("open");
      await act(async () => events.onerror());
      expect(panel).toHaveAttribute("open");
      expect(
        within(panel.querySelector("summary")).getByText("Unavailable"),
      ).toBeInTheDocument();
    },
  );

  it.each(["response", "network"])(
    "opens the pipeline for an initial readiness %s failure",
    async (failure) => {
      let settleHealth;
      fetch.mockImplementation((url) =>
        url.includes("/api/health")
          ? new Promise((resolve, reject) => {
              settleHealth = () =>
                failure === "network"
                  ? reject(new Error("offline"))
                  : resolve({
                      ok: true,
                      json: async () => ({ status: "starting", services: {} }),
                    });
            })
          : new Promise(() => {}),
      );
      const { container } = render(<App />);
      const events = FakeEventSource.instances[0];
      await act(async () => {
        events.onopen();
        events.emit("snapshot", {
          run_id: "startup-failed",
          run: { payload: { status: "running" } },
          robot_health: { payload: { status: "healthy" } },
          topics: [],
          anomalies: [],
          incident_history: [],
          completion: {},
          consumer_offsets: [],
          mission_progress_ms: 0,
        });
      });
      const panel = container.querySelector(".telemetry-pipeline");
      expect(panel).not.toHaveAttribute("open");
      await act(async () => settleHealth());
      expect(panel).toHaveAttribute("open");
      expect(
        within(panel.querySelector("summary")).getByText("Unavailable"),
      ).toBeInTheDocument();
    },
  );

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
    fireEvent.click(screen.getByText("Connection details"));
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
  it("keeps one dataset and upload action across all tabs without loading unrelated localization", async () => {
    const original = fetch.getMockImplementation();
    fetch.mockImplementation((url) =>
      url.includes("/api/datasets")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              default_dataset_id: "recording-a",
              datasets: [
                {
                  dataset_id: "recording-a",
                  name: "Recording A",
                  selectable: true,
                  description: "Camera recording",
                  capabilities: {
                    health: "ready",
                    recordings: "not_prepared",
                    localization: "unsupported",
                  },
                },
              ],
            }),
          })
        : original(url),
    );
    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Dataset")).toHaveValue("recording-a"),
    );
    for (const name of ["Recording", "Localization", "Telemetry"]) {
      fireEvent.click(screen.getByRole("tab", { name }));
      expect(screen.getByLabelText("Dataset")).toHaveValue("recording-a");
      expect(
        screen.getByRole("button", { name: "Upload recording" }),
      ).toBeVisible();
    }
    expect(
      fetch.mock.calls.some(([url]) =>
        url.includes("/api/localization/evaluation"),
      ),
    ).toBe(false);
    expect(localStorage.getItem("workbench.view")).toBe("health");
  });

  it("keeps replay A isolated while browsing B, including disconnected runtime authority", async () => {
    const original = fetch.getMockImplementation();
    fetch.mockImplementation((url) =>
      url.includes("/api/datasets")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              default_dataset_id: "a",
              datasets: ["a", "b"].map((id) => ({
                dataset_id: id,
                name: `Recording ${id}`,
                selectable: true,
              })),
            }),
          })
        : original(url),
    );
    render(<App />);
    fireEvent.click(screen.getByLabelText("Dataset"));
    await screen.findByRole("option", { name: "Recording b" });
    act(() =>
      FakeEventSource.instances.at(-1).emit("snapshot", {
        run_id: "run-a",
        dataset_id: "a",
        dataset_name: "Recording a",
        run: { payload: { status: "running" } },
        topics: [],
        anomalies: [],
        incident_history: [],
        completion: {},
        consumer_offsets: [],
        mission_progress_ms: 1,
      }),
    );
    fireEvent.click(screen.getByRole("option", { name: "Recording b" }));
    expect(screen.getByLabelText("Dataset")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Pause", exact: true }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/No replay results yet/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Return to active replay" }),
    );
    expect(screen.getByLabelText("Dataset")).toHaveValue("a");
  });

  it("restores a saved selection and explains removal without retaining old context", async () => {
    localStorage.setItem("workbench.dataset", "removed");
    localStorage.setItem("workbench.view", "recordings");
    const original = fetch.getMockImplementation();
    fetch.mockImplementation((url) =>
      url.includes("/api/datasets")
        ? Promise.resolve({
            ok: true,
            json: async () => ({
              default_dataset_id: "a",
              datasets: [
                { dataset_id: "a", name: "Recording A", selectable: true },
              ],
            }),
          })
        : original(url),
    );
    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Dataset")).toHaveValue("a"),
    );
    expect(screen.getByRole("tab", { name: "Recording" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByText(/previous dataset is no longer available/),
    ).toBeVisible();
    expect(localStorage.getItem("workbench.dataset")).toBe("a");
  });

  it("selects a successful upload globally without starting replay or promising sensor evidence", async () => {
    const original = fetch.getMockImplementation();
    let uploaded = false;
    fetch.mockImplementation((url, options) => {
      if (url.includes("/api/datasets/upload")) {
        uploaded = true;
        return Promise.resolve({
          ok: true,
          json: async () => ({ dataset_id: "upload:mine.bag" }),
        });
      }
      if (url.endsWith("/api/datasets"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            default_dataset_id: "a",
            datasets: [
              { dataset_id: "a", name: "A", selectable: true },
              ...(uploaded
                ? [
                    {
                      dataset_id: "upload:mine.bag",
                      name: "Mine",
                      source: "user_upload",
                      selectable: true,
                    },
                  ]
                : []),
            ],
          }),
        });
      return original(url, options);
    });
    const { container } = render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Dataset")).toHaveValue("a"),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Recording" }));
    const dialog = container.querySelector("dialog");
    dialog.showModal = () => {
      dialog.open = true;
    };
    dialog.close = () => {
      dialog.open = false;
    };
    fireEvent.click(screen.getByRole("button", { name: "Upload recording" }));
    fireEvent.change(container.querySelector('input[type="file"]'), {
      target: { files: [new File(["bag"], "mine.bag")] },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Dataset")).toHaveValue("upload:mine.bag"),
    );
    expect(
      screen.getByText(/Your upload is available for replay/),
    ).toBeVisible();
    expect(
      fetch.mock.calls.some(([url]) => url.includes("/api/replay/start")),
    ).toBe(false);
  });

  it("preserves the selected recording after an upload fails", async () => {
    const original = fetch.getMockImplementation();
    fetch.mockImplementation((url, options) =>
      url.includes("/api/datasets/upload")
        ? Promise.resolve({
            ok: false,
            json: async () => ({ detail: "Recording is invalid" }),
          })
        : original(url, options),
    );
    const { container } = render(<App />);
    const before = screen.getByLabelText("Dataset").value;
    const dialog = container.querySelector("dialog");
    dialog.showModal = () => {
      dialog.open = true;
    };
    fireEvent.click(screen.getByRole("button", { name: "Upload recording" }));
    fireEvent.change(container.querySelector('input[type="file"]'), {
      target: { files: [new File(["bad"], "bad.bag")] },
    });
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(
        "Recording is invalid",
      ),
    );
    expect(screen.getByLabelText("Dataset")).toHaveValue(before);
    expect(dialog.open).toBe(true);
  });
});
