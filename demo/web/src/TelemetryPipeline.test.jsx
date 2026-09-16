import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import TelemetryPipeline from "./TelemetryPipeline";

afterEach(cleanup);
const health = { topic: "/_telemetry/gateway_health", robot_id: "r1", payload: { health_status: "healthy", mean_rate_hz: 1, expected_rate_hz: 1 } };
const events = { topic: "/_telemetry/gateway_events", robot_id: "r1", payload: { status: "gap", mean_rate_hz: 0, expected_rate_hz: 1, rate_monitoring_enabled: false } };

it("does not report silent event streams as a pipeline fault or fixed-rate stream", () => {
  const { container } = render(<TelemetryPipeline topics={[health, events]} />);
  expect(container.querySelector(".telemetry-pipeline")).not.toHaveAttribute("open");
  expect(screen.getByText("Monitoring")).toBeInTheDocument();
  expect(screen.getByText("No events observed in retained evidence.")).toBeInTheDocument();
  expect(screen.queryByText(/0 Hz/)).not.toBeInTheDocument();
});

it("opens for a fault arriving after mount and can still be collapsed", () => {
  const { container, rerender } = render(<TelemetryPipeline topics={[health]} />);
  rerender(<TelemetryPipeline topics={[{ ...health, payload: { health_status: "degraded" } }]} />);
  expect(container.querySelector(".telemetry-pipeline")).toHaveAttribute("open");
  fireEvent.click(container.querySelector(".telemetry-pipeline > summary"));
  // jsdom does not implement native summary toggling; simulate the browser toggle.
  container.querySelector(".telemetry-pipeline").open = false;
  rerender(<TelemetryPipeline topics={[{ ...health, payload: { health_status: "degraded" } }]} />);
  expect(container.querySelector(".telemetry-pipeline")).not.toHaveAttribute("open");
  rerender(<TelemetryPipeline topics={[health]} unavailable />);
  expect(container.querySelector(".telemetry-pipeline")).toHaveAttribute("open");
  expect(screen.getByRole("status")).toHaveTextContent("last received evidence");
});

it("shows the latest event by timestamp, its evidence, and severity without inventing current failure", () => {
  const observation = (timestamp, kind) => ({ topic: events.topic, robot_id: "r1", metric_id: String(timestamp), stream_timestamp_ms: timestamp, payload: { attributes: { event_kind: kind, affected_topic: "/scan", count: 2 } } });
  const { container } = render(<TelemetryPipeline topics={[events]} startMs={1000}
    signals={[observation(5000, "qos_incompatible"), observation(2000, "older_event")]} />);
  expect(container.querySelector(".telemetry-pipeline")).toHaveAttribute("open");
  expect(screen.getByText("Event to inspect")).toBeInTheDocument();
  expect(screen.getByText("qos_incompatible")).toBeInTheDocument();
  expect(screen.getAllByText(/00:04 into run/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/severity: not reported/)).toHaveLength(2);
  expect(screen.getByText(/not a complete event log/)).toBeInTheDocument();
});

it("surfaces disconnected transport even when the latest health window was healthy", () => {
  const { container } = render(<TelemetryPipeline topics={[health]} signals={[{ ...health, stream_timestamp_ms: 5000, payload: { attributes: { transport_state: "disconnected", last_transport_error: "KafkaTimeoutError" } } }]} />);
  expect(container.querySelector(".telemetry-pipeline")).toHaveAttribute("open");
  expect(screen.getByText("Needs attention")).toBeInTheDocument();
  expect(screen.getByText("KafkaTimeoutError")).toBeInTheDocument();
});
