import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import RecordingIncidentList from "./RecordingIncidentList";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("paginates complete counts and selects an incident", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => ({
      ok: true,
      json: async () => {
        const offset = Number(
          new URL(url, "http://test").searchParams.get("offset"),
        );
        return {
          analysis_id: "a",
          total_count: 21,
          returned_count: offset ? 1 : 20,
          next_offset: offset ? null : 20,
          incidents: [
            {
              incident_id: `i${offset}`,
              title: `Warning ${offset}`,
              topics: ["/camera"],
              start_s: 1,
              end_s: 2,
              member_count: 1,
              explanation_status: "unsupported",
            },
          ],
        };
      },
    })),
  );
  const select = vi.fn();
  render(
    <RecordingIncidentList
      datasetId="test"
      analysisId="a"
      apiUrl=""
      onSelect={select}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: /Warning 0/ }));
  expect(select).toHaveBeenCalledWith("i0");
  fireEvent.click(screen.getByRole("button", { name: "Next incidents" }));
  expect(
    await screen.findByRole("button", { name: /Warning 20/ }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next incidents" })).toBeDisabled();
});
it("does not call an empty result healthy", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ analysis_id: "a", total_count: 0, incidents: [] }),
    })),
  );
  render(
    <RecordingIncidentList
      datasetId="test"
      analysisId="a"
      apiUrl=""
      onSelect={() => {}}
    />,
  );
  expect(
    await screen.findByText(/Issues outside these checks may still be present/),
  ).toBeInTheDocument();
});
