import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import RecordingIncidentExplanation from "./RecordingIncidentExplanation";

afterEach(cleanup);
const incident = {
  title: "Image content warning",
  start_s: 1,
  end_s: 2,
  explanation_status: "supported",
  observations: [
    {
      rule_id: "dark_frames",
      text: "2 frames crossed the threshold.",
      evidence_refs: ["e"],
    },
  ],
  evidence: [
    {
      id: "e",
      topic: "/cam0/image_raw",
      field: "mean_intensity",
      availability: "available",
      start_timestamp_ns: "1000000000",
      end_timestamp_ns: "2000000000",
      clock: "recorded_receive",
      parameters: { count: 2 },
    },
  ],
  possibilities: [{ text: "Lighting changes", status: "untested" }],
  limits: ["Camera malfunction is not established."],
  next_checks: [
    {
      text: "Collect exposure data.",
      reason: "Not recorded",
      evidence_refs: [],
    },
  ],
  member_events: [
    {
      event_id: "e",
      topic: "/cam0/image_raw",
      event_type: "dark_frames",
      start_s: 1,
      end_s: 2,
    },
  ],
  member_count: 60,
  member_offset: 0,
  next_member_offset: 50,
};
it("keeps hypotheses untested and makes real evidence navigable", () => {
  const inspect = vi.fn(),
    members = vi.fn();
  render(
    <RecordingIncidentExplanation
      incident={incident}
      onInspect={inspect}
      onMembers={members}
    />,
  );
  expect(screen.getByText(/untested/)).toBeInTheDocument();
  expect(
    screen.getByText("Camera malfunction is not established."),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Inspect \/cam0/ }));
  expect(inspect).toHaveBeenCalledWith(incident.evidence[0]);
  fireEvent.click(screen.getByRole("button", { name: "Next warnings" }));
  expect(members).toHaveBeenCalledWith(50);
  expect(
    screen.queryByRole("button", { name: /exposure/ }),
  ).not.toBeInTheDocument();
});
