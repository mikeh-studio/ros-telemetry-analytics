import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class FakeEventSource {
  static instances = [];
  constructor() { this.listeners = {}; FakeEventSource.instances.push(this); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  emit(type, payload) { this.listeners[type]?.({ data: JSON.stringify(payload) }); }
  close() {}
}

describe("Flight Deck", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url) => Promise.resolve({
        ok: true,
        json: async () => url.includes("/api/health")
          ? { status: "ready", services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }
          : { topics: [], anomalies: [], incident_history: [], completion: {}, consumer_offsets: [], mission_progress_ms: 0 },
      })),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("labels the source as recorded replay and exposes mission controls", async () => {
    render(<App />);
    expect(screen.getByText("RECORDED REPLAY")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Start mission" })).toBeEnabled());
    expect(screen.getByText("Camera dropout")).toBeInTheDocument();
    expect(screen.getByText("Streaming job")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Stack readiness" })).getAllByText("ready").length).toBe(5);
  });

  it("explains why camera fault injection is limited to real time", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "camera-dropout" } });
    expect(screen.getByText(/processing-time watchdog stays tied to real time/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "5× accelerated" })).toBeDisabled();
  });

  it("shows checkpoint freshness and authoritative event counters", async () => {
    fetch.mockImplementation((url) => Promise.resolve({
      ok: true,
      json: async () => url.includes("/api/health")
        ? { status: "ready", services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }
        : url.includes("/api/flink/summary")
        ? {
            status: "available",
            checkpoints: { id: 7, status: "COMPLETED", age_ms: 2_000 },
            events_processed: 1_000,
            accepted_late_events: 2,
            duplicate_events: 1,
            too_late_events: 0,
          }
        : { topics: [], anomalies: [], incident_history: [], completion: {}, consumer_offsets: [], mission_progress_ms: 0 },
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByText(/checkpoint completed #7 \(2.0 s old\)/i)).toBeInTheDocument());
    expect(screen.getByText(/Processed 1000 · accepted late 2 · duplicate 1 · too late 0/i)).toBeInTheDocument();
  });

  it("replaces stale health with an actionable unavailable state", async () => {
    fetch.mockImplementation((url) => Promise.resolve({
      ok: true,
      json: async () => url.includes("/api/health")
        ? { status: "ready", services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }
        : url.includes("flink")
        ? { status: "available" }
        : {
            run_id: "run-1",
            run: { payload: { status: "running" } },
            robot_health: { payload: { status: "healthy" } },
            topics: [], anomalies: [], incident_history: [], completion: {},
            consumer_offsets: [], mission_progress_ms: 0,
          },
    }));
    render(<App />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
    FakeEventSource.instances[0].onopen();
    await waitFor(() => expect(screen.getByText("healthy")).toBeInTheDocument());
    FakeEventSource.instances[0].onerror();
    await waitFor(() => expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0));
    expect(screen.getByRole("alert")).toHaveTextContent("reconnect automatically");
  });

  it("does not preserve healthy state when a streaming authority is unavailable", async () => {
    fetch.mockImplementation((url) => Promise.resolve({
      ok: true,
      json: async () => url.includes("/api/health")
        ? { status: "starting", services: { kafka: "unknown", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }
        : url.includes("flink")
        ? { status: "available" }
        : {
            run_id: "run-1",
            run: { payload: { status: "running" } },
            robot_health: { payload: { status: "healthy" } },
            topics: [{ topic: "/camera/image_raw", payload: { status: "healthy" } }],
            anomalies: [], incident_history: [], completion: {},
            consumer_offsets: [], mission_progress_ms: 30_000,
          },
    }));
    render(<App />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
    FakeEventSource.instances[0].onopen();

    await waitFor(() => expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0));
    expect(screen.queryByText("healthy")).not.toBeInTheDocument();
    expect(screen.getByText(/docker compose ps/)).toBeInTheDocument();
  });

  it("surfaces durable summary verification failures", async () => {
    render(<App />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
    FakeEventSource.instances[0].emit("completion_failed", {
      detail: "Summary files did not satisfy the durable four-topic contract within 60 seconds",
    });

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("four-topic contract"));
    expect(screen.getByRole("alert")).toHaveTextContent("Flink checkpoint");
  });

  it("renders healthy, incident, recovered, and completed mission states", async () => {
    fetch.mockImplementation((url) => url.includes("/api/health")
      ? Promise.resolve({ ok: true, json: async () => ({ status: "ready", services: { kafka: "ready", flink: "ready", flink_job: "ready", projection_api: "ready", replayer: "ready" } }) })
      : new Promise(() => {}));
    render(<App />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
    const events = FakeEventSource.instances[0];
    await act(async () => events.onopen());
    const base = {
      run_id: "run-1",
      run: { payload: { status: "running" } },
      robot_health: { payload: { status: "healthy" } },
      topics: [{ topic: "/camera/image_raw", payload: { status: "healthy", mean_rate_hz: 30, expected_rate_hz: 30, message_count: 300 } }],
      anomalies: [], incident_history: [], completion: {}, consumer_offsets: [], mission_progress_ms: 30_000,
    };
    await act(async () => events.emit("snapshot", base));
    await waitFor(() => expect(screen.getAllByText("healthy").length).toBeGreaterThan(0));

    const active = {
      anomaly_id: "incident-1", revision: 0, condition_type: "GAP", status: "active",
      topic: "/camera/image_raw",
    };
    await act(async () => events.emit("snapshot", {
      ...base,
      robot_health: { payload: { status: "degraded", primary_anomaly: { condition_type: "GAP", topic: "/camera/image_raw" } } },
      anomalies: [active], incident_history: [active],
    }));
    await waitFor(() => expect(screen.getAllByText("GAP").length).toBe(2));
    expect(screen.getByText("degraded")).toBeInTheDocument();
    expect(document.querySelector(".primary-anomaly")).toHaveTextContent("/camera/image_raw");

    const recovered = { ...active, revision: 1, status: "recovered" };
    await act(async () => events.emit("snapshot", { ...base, anomalies: [recovered], incident_history: [active, recovered] }));
    await waitFor(() => expect(screen.getByText("recovered")).toBeInTheDocument());

    await act(async () => events.emit("snapshot", {
      ...base,
      run: { payload: { status: "summary_ready" } },
      completion: { verified: true, summary_file_count: 4 },
      mission_progress_ms: 90_000,
    }));
    await waitFor(() => expect(screen.getByText("completed")).toBeInTheDocument());
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});
