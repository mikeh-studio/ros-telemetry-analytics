import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import TopicHistory, { historyPath, topicSamples } from "./TopicHistory";
afterEach(cleanup);
const sample = (end, value, revision = 0, status = "complete") => ({
  topic: "/odom",
  robot_id: "r1",
  window_start_ms: end - 10000,
  window_end_ms: end,
  revision,
  payload: { mean_rate_hz: value, expected_rate_hz: 20, window_status: status },
});
it("keeps corrected windows isolated by robot and leaves missing and partial windows disconnected", () => {
  const rows = topicSamples(
    [
      sample(10000, 20),
      sample(10000, 19, 1),
      sample(11000, 20),
      sample(13000, 20),
      sample(14000, 2, 0, "partial"),
      sample(15000, 20),
      { ...sample(12000, 99), robot_id: "r2" },
    ],
    "/odom",
    0,
    "r1",
  );
  expect(rows).toHaveLength(5);
  expect(rows[0].value).toBe(19);
  expect(
    historyPath(
      rows,
      (v) => v,
      (v) => v,
    ),
  ).toBe("M10000,19 L11000,20 M13000,20  M15000,20");
});
it("inspects recorded timestamps without inventing a value in a missing window", () => {
  const latest = sample(13000, 20);
  latest.payload.max_inter_message_gap_s = 0.9;
  render(
    <TopicHistory
      topics={[latest]}
      history={[sample(10000, 19), latest]}
      startMs={0}
      durationMs={90000}
    />,
  );
  fireEvent.change(screen.getByRole("slider"), { target: { value: "12000" } });
  expect(screen.getByText("No sample")).toBeInTheDocument();
  expect(screen.getByText(/Window max gap:/)).toHaveTextContent(
    "Window max gap: —",
  );
  expect(
    screen.getByText(/No recorded window ends at 00:12/),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider"), { target: { value: "10000" } });
  expect(screen.getByText(/Window ending 00:10: 19 Hz/)).toBeInTheDocument();
});

it("keeps Nav2 localization update-based and explains why signals matter", () => {
  const metric = {
    topic: "/amcl_pose",
    robot_id: "r1",
    payload: {
      rate_monitoring_enabled: false,
      mean_rate_hz: 0,
      expected_rate_hz: 1,
      health_status: "healthy",
    },
  };
  render(
    <TopicHistory
      topics={[metric]}
      startMs={0}
      signals={[
        {
          ...metric,
          stream_timestamp_ms: 4200,
          payload: { attributes: { covariance: 0.25 } },
        },
      ]}
    />,
  );
  expect(
    screen.getByRole("region", { name: "Monitored Topics" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("The map pose supports navigation and localization."),
  ).toBeInTheDocument();
  expect(screen.getByText("00:04 into run")).toBeInTheDocument();
  expect(screen.queryByText("0 Hz")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Map localization" }));
  expect(
    screen.getByText(/This is an estimate, not ground truth/),
  ).toBeInTheDocument();
  expect(screen.getByText("covariance")).toBeInTheDocument();
});

it("shows incident onset beside the affected robot signal", () => {
  render(
    <TopicHistory
      topics={[sample(13000, 0)]}
      startMs={1000}
      incidents={[
        {
          anomaly_id: "gap",
          topic: "/odom",
          robot_id: "r1",
          status: "active",
          effective_start_stream_ms: 5000,
        },
      ]}
    />,
  );
  expect(
    screen.getByText("Unreliable since 00:04 into run"),
  ).toBeInTheDocument();
});

it("does not use a raw rate status as event-driven health", () => {
  render(
    <TopicHistory
      topics={[
        {
          topic: "/diagnostics",
          payload: {
            rate_monitoring_enabled: false,
            status: "gap",
            mean_rate_hz: 0,
          },
        },
      ]}
    />,
  );
  expect(screen.queryByText("gap")).not.toBeInTheDocument();
  expect(screen.getByText("waiting")).toBeInTheDocument();
});

it("keeps camera sources distinct and omits generic purpose text", () => {
  const topics = [
    "/cam0/image_raw",
    "/cam1/image_raw",
    "/custom_a/data",
    "/custom_b/data",
  ].map((topic) => ({
    topic,
    payload: { status: "healthy", mean_rate_hz: 20 },
  }));
  const { container } = render(
    <TopicHistory
      topics={topics}
      history={[]}
      startMs={0}
      durationMs={10000}
    />,
  );
  expect(
    screen.getByRole("button", { name: "Camera 0", exact: true }),
  ).toBeInTheDocument();
  const camera1 = screen.getByRole("button", { name: "Camera 1", exact: true });
  fireEvent.click(camera1);
  expect(camera1).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByRole("button", { name: "Camera 0", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  expect(
    screen.getByRole("button", { name: "/custom_a/data", exact: true }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "/custom_b/data", exact: true }),
  ).toBeInTheDocument();
  expect(container.querySelectorAll(".topic-lane")).toHaveLength(4);
  expect(container.querySelectorAll(".signal-purpose")).toHaveLength(0);
  expect(
    screen.queryByText(/Message delivery indicates/),
  ).not.toBeInTheDocument();
});
