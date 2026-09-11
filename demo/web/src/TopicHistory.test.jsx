import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import TopicHistory, { historyPath, topicSamples } from "./TopicHistory";
afterEach(cleanup);
const sample = (end, value, revision = 0, status = "complete") => ({ topic: "/odom", robot_id: "r1", window_start_ms: end - 10000, window_end_ms: end, revision, payload: { mean_rate_hz: value, expected_rate_hz: 20, window_status: status } });
it("keeps corrected windows isolated by robot and leaves missing and partial windows disconnected", () => {
  const rows = topicSamples([sample(10000, 20), sample(10000, 19, 1), sample(11000, 20), sample(13000, 20), sample(14000, 2, 0, "partial"), sample(15000, 20), { ...sample(12000, 99), robot_id: "r2" }], "/odom", 0, "r1");
  expect(rows).toHaveLength(5);
  expect(rows[0].value).toBe(19);
  expect(historyPath(rows, v => v, v => v)).toBe("M10000,19 L11000,20 M13000,20  M15000,20");
});
it("inspects recorded timestamps without inventing a value in a missing window", () => {
  const latest = sample(13000, 20);
  render(<TopicHistory topics={[latest]} history={[sample(10000, 19), latest]} startMs={0} durationMs={90000} />);
  fireEvent.change(screen.getByRole("slider"), { target: { value: "12000" } });
  expect(screen.getByText("No sample")).toBeInTheDocument();
  expect(screen.getByText(/No recorded window ends at 00:12/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider"), { target: { value: "10000" } });
  expect(screen.getByText(/Window ending 00:10: 19 Hz/)).toBeInTheDocument();
});
