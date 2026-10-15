import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import RecordingInvestigation from "./RecordingInvestigation";
const metadata = (id) => ({
  dataset_id: id,
  analysis_id: id.repeat(32),
  name: id,
  duration_s: 10,
  message_count: 10,
  cases: [],
  reference_topics: [],
  coverage: [],
  integrity: "local_digest_only",
  source_sha256: "abc",
  event_count: 0,
  events: [],
});
const interval = (id) => ({
  analysis_id: id.repeat(32),
  previews: [],
  events: [],
  event_count: 0,
  series: [
    {
      topic: `/${id}`,
      domain: "images",
      field: "mean_intensity",
      frame: "camera",
      unit: "0–255",
      points: [{ t: 0, min: 1, max: 99, value: 50, count: 2 }],
    },
  ],
});
const response = (body) => ({ ok: true, json: async () => body });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens offline evidence and moves a shared cursor without replay or another request", async () => {
  const fetch = vi.fn(async (url) =>
    response(
      url.endsWith("/investigations")
        ? {
            datasets: [
              { dataset_id: "a", name: "Recording A", status: "ready" },
            ],
          }
        : url.includes("/interval?")
          ? interval("a")
          : metadata("a"),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  render(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  const cursor = await screen.findByRole("slider", {
    name: "Recorded time cursor",
  });
  const count = fetch.mock.calls.length;
  fireEvent.change(cursor, { target: { value: "5" } });
  expect(cursor).toHaveValue("5");
  expect(fetch).toHaveBeenCalledTimes(count);
  expect(
    screen.getAllByRole("img", { name: "mean_intensity for /a" }),
  ).toHaveLength(3);
  expect(fetch.mock.calls.some(([url]) => url.includes("replay"))).toBe(false);
  fireEvent.change(screen.getByLabelText("Interval end seconds"), {
    target: { value: "99" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "Inspect interval" }).closest("form"),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("inside the recording");
});

it("ignores a slow old dataset response after switching recordings", async () => {
  let finishOld;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      if (url.endsWith("/investigations"))
        return response({
          datasets: ["a", "b"].map((id) => ({
            dataset_id: id,
            name: `Recording ${id}`,
            status: "ready",
          })),
        });
      if (url.includes("/a/interval"))
        return new Promise((resolve) => {
          finishOld = resolve;
        });
      if (url.includes("/b/interval")) return response(interval("b"));
      return response(metadata(url.endsWith("/a") ? "a" : "b"));
    }),
  );
  const { rerender } = render(
    <RecordingInvestigation apiUrl="" active datasetId="a" />,
  );
  await waitFor(() => expect(finishOld).toBeDefined());
  rerender(<RecordingInvestigation apiUrl="" active datasetId="b" />);
  await screen.findByRole("slider");
  await act(async () => finishOld(response(interval("a"))));
  expect(
    screen.queryAllByRole("img", { name: "mean_intensity for /a" }),
  ).toHaveLength(0);
  expect(
    screen.getAllByRole("img", { name: "mean_intensity for /b" }),
  ).toHaveLength(3);
});

it("shows stale evidence and does not render an earlier recording", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      url.endsWith("/preparation")
        ? response({ status: "idle" })
        : url.endsWith("/investigations")
          ? response({
              datasets: [{ dataset_id: "a", name: "A", status: "stale" }],
            })
          : { ok: false, json: async () => ({ detail: "Evidence is stale" }) },
    ),
  );
  render(<RecordingInvestigation apiUrl="" active datasetId="a" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Evidence is stale",
  );
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});

it("opens generated evidence without curated cases, targets a signal, and clears on manual interval changes", async () => {
  const m = {
    ...metadata("a"),
    origin_ns: "1000000000000000000",
    incident_count: 1,
  };
  const entry = {
    incident_id: "generated",
    title: "Image content warning",
    topics: ["/a"],
    start_s: 1,
    end_s: 2,
    member_count: 1,
    explanation_status: "supported",
  };
  const detail = {
    ...entry,
    analysis_id: m.analysis_id,
    display_start_s: 0,
    display_end_s: 4,
    focus_s: 1,
    plot_hints: [{ topic: "/a", field: "mean_intensity" }],
    observations: [
      {
        rule_id: "dark_frames",
        text: "Measured darkness",
        evidence_refs: ["event"],
      },
    ],
    evidence: [
      {
        id: "event",
        topic: "/a",
        field: "mean_intensity",
        start_timestamp_ns: "1000000001000000000",
        parameters: {},
      },
    ],
    possibilities: [],
    limits: ["Cause unknown"],
    next_checks: [],
    member_events: [],
    member_offset: 0,
  };
  const fetch = vi.fn(async (url) =>
    response(
      url.includes("/incidents/generated?")
        ? detail
        : url.includes("/incidents?")
          ? { analysis_id: m.analysis_id, total_count: 1, incidents: [entry] }
          : url.includes("/interval?")
            ? interval("a")
            : m,
    ),
  );
  vi.stubGlobal("fetch", fetch);
  render(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  fireEvent.click(
    await screen.findByRole("button", { name: /Image content warning/ }),
  );
  expect(await screen.findByText("Measured darkness")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Inspect \/a/ }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url]) =>
          url.includes("field=mean_intensity") && url.includes("topic=%2Fa"),
      ),
    ).toBe(true),
  );
  expect(
    screen.getByRole("slider", { name: "Recorded time cursor" }),
  ).toHaveValue("1");
  fireEvent.submit(
    screen.getByRole("button", { name: "Inspect interval" }).closest("form"),
  );
  expect(screen.queryByText("Measured darkness")).not.toBeInTheDocument();
  expect(fetch.mock.calls.some(([url]) => url.includes("replay"))).toBe(false);
});

it("keeps coverage for different message types on one topic distinct", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const m = {
    ...metadata("a"),
    coverage: ["tf/msg/tfMessage", "tf2_msgs/msg/TFMessage"].map(
      (message_type) => ({
        topic: "/tf",
        message_type,
        analyzed_message_count: 2,
        message_count: 2,
        extraction_error_count: 0,
        analysis_status: "full",
      }),
    ),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      response(url.includes("/interval?") ? interval("a") : m),
    ),
  );
  try {
    render(<RecordingInvestigation apiUrl="" active datasetId="a" />);
    expect(await screen.findByText("tf/msg/tfMessage")).toBeInTheDocument();
    expect(screen.getByText("tf2_msgs/msg/TFMessage")).toBeInTheDocument();
    expect(error).not.toHaveBeenCalled();
  } finally {
    error.mockRestore();
  }
});

it("recovers stale evidence through a rebuild and loads the new analysis automatically", async () => {
  let rebuilt = false;
  const fetch = vi.fn(async (url, options = {}) => {
    if (url.endsWith("/preparation")) {
      if (options.method === "POST") {
        rebuilt = true;
        return response({ status: "completed", analysis_id: "a".repeat(32) });
      }
      return response({ status: "idle" });
    }
    if (!rebuilt)
      return { ok: false, json: async () => ({ detail: "Evidence is stale" }) };
    return response(url.includes("/interval?") ? interval("a") : metadata("a"));
  });
  vi.stubGlobal("fetch", fetch);
  render(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Evidence is stale",
  );
  fireEvent.click(screen.getByRole("button", { name: "Rebuild evidence" }));
  expect(
    await screen.findByRole("slider", { name: "Recorded time cursor" }),
  ).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    screen.queryByText(/prepare_investigations.py/),
  ).not.toBeInTheDocument();
});

function pagedIncident(analysisId, offset = 0) {
  return {
    incident_id: "paged",
    analysis_id: analysisId,
    title: "Paged image warning",
    topics: ["/a"],
    start_s: 1,
    end_s: 2,
    member_count: 51,
    explanation_status: "supported",
    display_start_s: 0,
    display_end_s: 4,
    focus_s: 1,
    plot_hints: [{ topic: "/a", field: "mean_intensity" }],
    observations: [],
    evidence: [],
    possibilities: [],
    limits: [],
    next_checks: [],
    member_events: [],
    member_offset: offset,
    next_member_offset: offset === 0 ? 50 : null,
  };
}

function mockPagedRecording() {
  const m = { ...metadata("a"), incident_count: 1 };
  const fetch = vi.fn(async (url) => {
    if (url.includes("/incidents/paged?")) {
      const offset = Number(
        new URL(url, "http://test").searchParams.get("member_offset"),
      );
      return response(pagedIncident(m.analysis_id, offset));
    }
    if (url.includes("/incidents?"))
      return response({
        analysis_id: m.analysis_id,
        total_count: 1,
        incidents: [pagedIncident(m.analysis_id)],
      });
    if (url.includes("/interval?"))
      return response({
        ...interval("a"),
        analysis_id: m.analysis_id,
        series: [
          ...interval("a").series,
          { ...interval("a").series[0], field: "sharpness_score" },
        ],
      });
    if (url.endsWith("/preparation")) return response({ status: "idle" });
    return response({ ...m });
  });
  vi.stubGlobal("fetch", fetch);
  return { m, fetch };
}

it("preserves incident, cursor, draft and signal across warning pages and tab switches", async () => {
  const { fetch } = mockPagedRecording();
  const { rerender } = render(
    <RecordingInvestigation apiUrl="" active datasetId="a" />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Paged image warning/ }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("slider", { name: "Recorded time cursor" }),
    ).toHaveAttribute("max", "4"),
  );
  fireEvent.change(screen.getByRole("slider"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Interval end seconds"), {
    target: { value: "3.5" },
  });
  fireEvent.change(screen.getByLabelText("Signal 1"), {
    target: { value: "1" },
  });
  fireEvent.click(screen.getByText("Original warnings · 51"));
  const intervalRequests = () =>
    fetch.mock.calls.filter(([url]) => url.includes("/interval?")).length;
  const before = intervalRequests();
  const explanation = screen.getByRole("article", {
    name: "Incident explanation",
  });
  const warnings = screen
    .getByText("Original warnings · 51")
    .closest("details");
  const originalFetch = fetch.getMockImplementation();
  let finishPage;
  fetch.mockImplementation((url, ...args) =>
    url.includes("member_offset=50")
      ? new Promise((resolve) => {
          finishPage = () => resolve(originalFetch(url, ...args));
        })
      : originalFetch(url, ...args),
  );
  fireEvent.click(screen.getByRole("button", { name: "Next warnings" }));
  await waitFor(() => expect(finishPage).toBeDefined());
  expect(screen.getByRole("article", { name: "Incident explanation" })).toBe(
    explanation,
  );
  expect(warnings).toHaveAttribute("open");
  await act(async () => finishPage());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Previous warnings" }),
    ).toBeEnabled(),
  );
  expect(screen.getByRole("slider")).toHaveValue("3");
  expect(screen.getByRole("slider")).toHaveAttribute("max", "4");
  expect(screen.getByLabelText("Interval end seconds")).toHaveValue(3.5);
  expect(screen.getByLabelText("Signal 1")).toHaveValue("1");
  expect(intervalRequests()).toBe(before);
  expect(warnings).toHaveAttribute("open");

  const metadataRequests = () =>
    fetch.mock.calls.filter(([url]) => url.endsWith("/investigations/a"))
      .length;
  const beforeReturn = metadataRequests();
  rerender(<RecordingInvestigation apiUrl="" active={false} datasetId="a" />);
  rerender(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  await waitFor(() => expect(metadataRequests()).toBe(beforeReturn + 1));
  expect(screen.getByRole("slider")).toHaveValue("3");
  expect(screen.getByLabelText("Interval end seconds")).toHaveValue(3.5);
  expect(screen.getByLabelText("Signal 1")).toHaveValue("1");
  expect(
    screen.getByRole("button", { name: "Previous warnings" }),
  ).toBeEnabled();
  expect(intervalRequests()).toBe(before);
});

it("resets retained context when the analysis changes while away", async () => {
  const { m } = mockPagedRecording();
  const { rerender } = render(
    <RecordingInvestigation apiUrl="" active datasetId="a" />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Paged image warning/ }),
  );
  await waitFor(() =>
    expect(screen.getByRole("slider")).toHaveAttribute("max", "4"),
  );
  fireEvent.change(screen.getByRole("slider"), { target: { value: "3" } });
  rerender(<RecordingInvestigation apiUrl="" active={false} datasetId="a" />);
  m.analysis_id = "new-analysis";
  rerender(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  await waitFor(() =>
    expect(screen.getByRole("slider")).toHaveAttribute("max", "10"),
  );
  expect(screen.getByRole("slider")).toHaveValue("0");
  expect(
    screen.queryByRole("article", { name: "Incident explanation" }),
  ).not.toBeInTheDocument();
});

it("removes retained evidence if revalidation reports it stale", async () => {
  const { fetch } = mockPagedRecording();
  const { rerender } = render(
    <RecordingInvestigation apiUrl="" active datasetId="a" />,
  );
  await screen.findByRole("slider");
  rerender(<RecordingInvestigation apiUrl="" active={false} datasetId="a" />);
  const original = fetch.getMockImplementation();
  fetch.mockImplementation(async (url) =>
    url.endsWith("/investigations/a")
      ? { ok: false, json: async () => ({ detail: "Evidence is stale" }) }
      : original(url),
  );
  rerender(<RecordingInvestigation apiUrl="" active datasetId="a" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Evidence is stale",
  );
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});
