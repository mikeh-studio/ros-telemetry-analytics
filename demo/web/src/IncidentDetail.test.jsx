import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import IncidentDetail from "./IncidentDetail";

afterEach(cleanup);
const opened = {
  run_id: "run-a", robot_id: "robot-a", anomaly_id: "scan-gap", revision: 0,
  condition_type: "GAP", topic: "/scan", status: "active",
  effective_start_stream_ms: 1000, detected_stream_ms: 4000,
  evidence: { observed_rate_hz: 0, expected_rate_hz: 10 },
};
const recovered = {
  ...opened, revision: 1, status: "recovered", detected_stream_ms: 3000,
  recovered_stream_ms: 5000, evidence: { recovery_gate_ms: 1000 },
};

describe("Incident explanation", () => {
  it("handles signal data without any incident or robot identity", () => {
    render(<IncidentDetail runId="run-a" signals={[{ run_id: "run-a", stream_timestamp_ms: 500 }]} />);
    expect(screen.getByText("No incidents recorded for this run.")).toBeInTheDocument();
  });
  it("sorts missing timestamps after known timestamps with stable identity ties", () => {
    const incidents = [
      { ...opened, anomaly_id: "z", effective_start_stream_ms: undefined },
      { ...opened, anomaly_id: "a", effective_start_stream_ms: null },
      { ...opened, anomaly_id: "known", effective_start_stream_ms: 2000 },
    ];
    const { rerender } = render(<IncidentDetail runId="run-a" anomalies={incidents} />);
    const values = () => screen.getAllByRole("option").map(option => option.value);
    expect(values()).toEqual(["known", "a", "z"]);
    rerender(<IncidentDetail runId="run-a" anomalies={[...incidents].reverse()} />);
    expect(values()).toEqual(["known", "a", "z"]);
  });
  it("labels rounded nanosecond timestamps instead of implying exact browser precision", () => {
    const attributes = JSON.parse('{"gateway_received_timestamp_ns":1789070944781336293,"count":1}');
    render(<IncidentDetail runId="run-a" anomalies={[recovered]} signals={[{
      metric_id: "qos", run_id: "run-a", robot_id: "robot-a", topic: "/gateway_events",
      stream_timestamp_ms: 4500, payload: { attributes },
    }]} />);
    expect(screen.getByText("1789070944781336300 (approximate)")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
  it("shows only signals from the incident robot, run, and time interval", () => {
    const signal = { metric_id: "signal", run_id: "run-a", robot_id: "robot-a",
      topic: "/amcl_pose", stream_timestamp_ms: 4500,
      payload: { attributes: { position_x: 1.25 } } };
    render(<IncidentDetail runId="run-a" anomalies={[recovered]} signals={[
      signal, { ...signal, metric_id: "wrong-run", run_id: "run-b", topic: "/wrong-run" },
      { ...signal, metric_id: "wrong-robot", robot_id: "robot-b", topic: "/wrong-robot" },
      { ...signal, metric_id: "too-new", stream_timestamp_ms: 12000, topic: "/too-new" },
    ]} />);
    expect(screen.getByText(/\/amcl_pose/)).toBeInTheDocument();
    expect(screen.queryByText(/\/wrong-run|\/wrong-robot|\/too-new/)).not.toBeInTheDocument();
    expect(screen.getByText("1.25")).toBeInTheDocument();
  });
  it("groups revisions by identity, uses revision order, and excludes other runs", () => {
    render(<IncidentDetail runId="run-a" history={[recovered, opened]} anomalies={[recovered, { ...opened, run_id: "run-b", anomaly_id: "foreign", topic: "/foreign" }]} />);
    expect(screen.getByText("1 incidents")).toBeInTheDocument();
    expect(screen.getByText("4000 ms")).toBeInTheDocument();
    expect(screen.getByText("5000 ms")).toBeInTheDocument();
    expect(screen.queryByText(/\/foreign/)).not.toBeInTheDocument();
    expect(screen.getByText(/Cause is unconfirmed/)).toBeInTheDocument();
    expect(screen.getByText(/separate recording/)).toBeInTheDocument();
  });

  it("switches incidents and handles pruned opening history without inventing detection", () => {
    const active = { ...opened, anomaly_id: "odom-gap", topic: "/odom" };
    const { rerender } = render(<IncidentDetail runId="run-a" history={[recovered]} anomalies={[active]} />);
    expect(screen.getByText("Not yet observed")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Inspect incident" }), { target: { value: "scan-gap" } });
    expect(screen.getByText("The opening revision is outside the retained history.")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    rerender(<IncidentDetail runId="run-b" history={[recovered]} anomalies={[active]} />);
    expect(screen.getByText("No incidents recorded for this run.")).toBeInTheDocument();
  });
});
