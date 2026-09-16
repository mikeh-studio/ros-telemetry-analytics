import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import LocalizationInvestigation, { decisionText, pathFor, sampleAt } from "./LocalizationInvestigation";

const cases = ["detected", "missed", "false_alarm"].map((outcome, i) => ({ case_id: String(i), outcome, start_ms: 10, end_ms: 20, duration_ms: 10, source_file: "recording", segment_id: 0, onset_lag_ms: i ? null : 5 }));
const samples = [0, 10, 10, 20, 500, 510, 520].map((elapsed_ms, i) => ({ elapsed_ms, sample_index: i, source_file: "recording", segment_id: 0, run_id: "run", break_before: i === 0 || i === 4, ground_truth_x: i, ground_truth_y: 0, estimated_x: i + .1, estimated_y: .1, particle_position_spread_m: .2, estimated_pose_jump_m: .1, detector_score: .5, position_error_m: .14, detector_failure: i === 2, label_failure: i > 0 && i < 4 }));
const evaluation = { status: "available", summary: { thresholds: { particle_spread_warn_m: .4, pose_jump_warn_m: .5 } }, investigation: { status: "available", evaluation_id: "version", configuration_id: "config", dataset: "Test recording", duration_ms: 520, recordings: ["recording"], cases } };
const interval = (case_id) => ({ case_id, evaluation_id: "version", samples, sample_count: samples.length, start_ms: 0, end_ms: 520, gap_threshold_ms: 100 });
const response = (body) => ({ ok: true, json: async () => body });
async function open() {
  const result = render(<LocalizationInvestigation evaluation={evaluation} apiUrl="" />);
  const panel = result.container.querySelector("details");
  panel.open = true;
  fireEvent(panel, new Event("toggle"));
  await screen.findByRole("button", { name: "Play interval" });
  return result;
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const installFetch = () => vi.stubGlobal("fetch", vi.fn(async url => response(interval(new URL(url, "http://localhost").searchParams.get("case_id")))));

it("loads event filters, keeps sample stepping exact at duplicate timestamps, and hides markers in gaps", async () => {
  installFetch();
  const { container } = await open();
  fireEvent.click(screen.getByRole("button", { name: "Next sample" }));
  expect(screen.getByText(/Showing sample 1 at/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next sample" }));
  expect(screen.getByText(/Showing sample 2 at/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider", { name: "Playback time" }), { target: { value: "200" } });
  expect(screen.getByText(/No sample at this time/)).toBeInTheDocument();
  expect(container.querySelector(".estimate-marker")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Missed 1" }));
  await screen.findByText(/No detector alert matched/);
  expect(fetch.mock.calls.at(-1)[0]).toContain("case_id=1");
  fireEvent.click(screen.getByRole("button", { name: "False alarms 1" }));
  await screen.findByText(/This detector alert did not match/);
  expect(fetch.mock.calls.at(-1)[0]).toContain("case_id=2");
});

it("plays, pauses, loops, and stops at the interval end without affecting mission playback", async () => {
  installFetch();
  await open();
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "Play interval" }));
  await act(async () => { vi.advanceTimersByTime(100); });
  expect(Number(screen.getByRole("slider").value)).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "Pause interval" }));
  const paused = screen.getByRole("slider").value;
  await act(async () => { vi.advanceTimersByTime(200); });
  expect(screen.getByRole("slider").value).toBe(paused);
  fireEvent.change(screen.getByRole("slider"), { target: { value: "500" } });
  fireEvent.click(screen.getByRole("button", { name: "Play interval" }));
  await act(async () => { vi.advanceTimersByTime(50); });
  expect(Number(screen.getByRole("slider").value)).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: "Pause interval" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Loop interval" }));
  fireEvent.change(screen.getByRole("slider"), { target: { value: "500" } });
  fireEvent.click(screen.getByRole("button", { name: "Play interval" }));
  await act(async () => { vi.advanceTimersByTime(100); });
  expect(screen.getByRole("button", { name: "Play interval" })).toBeInTheDocument();
  expect(Number(screen.getByRole("slider").value)).toBe(520);
});

it("does not replace selected event evidence when an older request finishes late", async () => {
  installFetch();
  await open();
  let resolveOld;
  fetch.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Next event" }));
  fireEvent.click(screen.getByRole("button", { name: "Next event" }));
  await screen.findByText(/This detector alert did not match/);
  await act(async () => resolveOld(response({ ...interval("1"), sample_count: 999 })));
  expect(screen.queryByText(/999 samples/)).not.toBeInTheDocument();
  expect(screen.getByText(/This detector alert did not match/)).toBeInTheDocument();
});

it("clears stale evidence and exposes an API evaluation conflict", async () => {
  installFetch();
  await open();
  fetch.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "Evaluation changed. Refresh and select the event again." }) });
  fireEvent.click(screen.getByRole("button", { name: "Next event" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Evaluation changed"));
  expect(screen.queryByRole("button", { name: "Play interval" })).not.toBeInTheDocument();
});

it("does not claim thresholds stayed below their limits when evidence is missing", () => {
  const result = decisionText(cases[1], [{ elapsed_ms: 10, particle_position_spread_m: null, estimated_pose_jump_m: .1 }], evaluation.summary.thresholds);
  expect(result.explanation).toContain("missing");
  expect(result.explanation).not.toContain("Neither");
});

it("breaks plot lines at gaps and source boundaries and returns no stale sample inside a gap", () => {
  const rows = [{ ...samples[0], value: 1 }, { ...samples[1], value: 2 }, { ...samples[4], value: 3 }, { ...samples[5], source_file: "other", value: 4 }];
  expect(pathFor(rows, "value", s => s.elapsed_ms, v => v)).toBe("M0.00,1.00 L10.00,2.00 M500.00,3.00 M510.00,4.00");
  expect(sampleAt(samples, 300, 100)).toBeNull();
});


it("matches the saved detector's strict threshold comparison", () => {
  const result = decisionText(cases[1], [{ elapsed_ms: 10, particle_position_spread_m: .4, estimated_pose_jump_m: .5 }], evaluation.summary.thresholds);
  expect(result.evidence.every(item => !item.crossing)).toBe(true);
  expect(result.explanation).toContain("No recorded detector input exceeded");
});

it("preserves the selected event and cursor while pausing playback when its tab is hidden", async () => {
  installFetch();
  const { rerender } = render(<LocalizationInvestigation standalone active evaluation={evaluation} apiUrl="" />);
  await screen.findByRole("button", { name: "Play interval" });
  fireEvent.click(screen.getByRole("button", { name: "Missed 1" }));
  await screen.findByText(/No detector alert matched/);
  fireEvent.change(screen.getByRole("slider"), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Play interval" }));
  rerender(<LocalizationInvestigation standalone active={false} evaluation={evaluation} apiUrl="" />);
  expect(screen.getByRole("button", { name: "Play interval" })).toBeInTheDocument();
  const paused = screen.getByRole("slider").value;
  const requests = fetch.mock.calls.length;
  rerender(<LocalizationInvestigation standalone active evaluation={evaluation} apiUrl="" />);
  expect(screen.getByRole("button", { name: "Missed 1" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("slider").value).toBe(paused);
  expect(fetch.mock.calls).toHaveLength(requests);
});
