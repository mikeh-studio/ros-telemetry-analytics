import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import IncidentTrajectory, { trajectoryGroups } from "./IncidentTrajectory";

afterEach(cleanup);
const sample = (frame, x, time = 1000) => ({ run_id: "r", robot_id: "bot", topic: "/odom",
  stream_timestamp_ms: time, payload: { attributes: { frame_id: frame, position_x: x, position_y: 2 } } });

it("separates coordinate frames and rejects missing and nonfinite positions", () => {
  const groups = trajectoryGroups([sample("odom", 2, 2000), sample("map", 3), sample("odom", 1), sample("", 4), sample("odom", null), sample("odom", Infinity)]);
  expect(groups).toHaveLength(2);
  expect(groups[0].points.map((point) => point.x)).toEqual([1, 2]);
  expect(groups[1].frame).toBe("map");
});

it("renders a stationary path without invalid coordinates or interpolated lines", () => {
  const { container } = render(<IncidentTrajectory signals={[sample("odom", 1), sample("odom", 1, 2000)]} onset={1500} recovered={2500} />);
  expect(screen.getByRole("img", { name: "/odom reported positions in odom" })).toBeInTheDocument();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(container.querySelectorAll("circle")).toHaveLength(2);
  expect(container.querySelectorAll("polyline")).toHaveLength(0);
});
