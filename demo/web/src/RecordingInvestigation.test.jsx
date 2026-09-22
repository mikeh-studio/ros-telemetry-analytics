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
      url.endsWith("/investigations")
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
