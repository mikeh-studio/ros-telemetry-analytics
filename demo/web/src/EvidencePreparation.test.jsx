import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EvidencePreparation from "./EvidencePreparation";

const response = (body, ok = true) => ({ ok, json: async () => body });
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("starts one rebuild, shows progress, and automatically reloads completed evidence", async () => {
  vi.useFakeTimers();
  const onComplete = vi.fn();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ status: "idle" }))
    .mockResolvedValueOnce(
      response({ status: "running", stage: "Analyzing recording" }),
    )
    .mockResolvedValueOnce(
      response({ status: "completed", analysis_id: "new" }),
    );
  vi.stubGlobal("fetch", fetch);
  await act(async () => {
    render(
      <EvidencePreparation apiUrl="" datasetId="a" onComplete={onComplete} />,
    );
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Rebuild evidence" }));
  });
  expect(screen.getByRole("button")).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Analyzing recording");
  expect(fetch.mock.calls[1][1].method).toBe("POST");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(onComplete).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button")).not.toBeDisabled();
});

it("resumes polling an existing job and stops updates when leaving the recording", async () => {
  vi.useFakeTimers();
  const onComplete = vi.fn();
  let finish;
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      response({ status: "running", stage: "Analyzing recording" }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
  vi.stubGlobal("fetch", fetch);
  let view;
  await act(async () => {
    view = render(
      <EvidencePreparation apiUrl="" datasetId="a" onComplete={onComplete} />,
    );
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  view.unmount();
  await act(async () => {
    finish(response({ status: "completed" }));
  });
  expect(onComplete).not.toHaveBeenCalled();
  expect(fetch.mock.calls[1][1].signal.aborted).toBe(true);
});

it("shows failures and allows retry without a terminal command", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      response({ status: "failed", error: "Rebuild failed" }),
    )
    .mockResolvedValueOnce(
      response({ detail: "Another recording is rebuilding" }, false),
    );
  vi.stubGlobal("fetch", fetch);
  render(<EvidencePreparation apiUrl="" datasetId="a" onComplete={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Rebuild failed");
  fireEvent.click(screen.getByRole("button", { name: "Rebuild evidence" }));
  expect(
    await screen.findByText("Another recording is rebuilding"),
  ).toBeVisible();
  expect(screen.getByRole("button")).not.toBeDisabled();
});

it("does not restart a rebuild when the completion callback changes", async () => {
  vi.useFakeTimers();
  const first = vi.fn();
  const latest = vi.fn();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ status: "idle" }))
    .mockResolvedValueOnce(
      response({ status: "running", stage: "Analyzing recording" }),
    )
    .mockResolvedValueOnce(response({ status: "completed" }));
  vi.stubGlobal("fetch", fetch);
  let view;
  await act(async () => {
    view = render(
      <EvidencePreparation apiUrl="" datasetId="a" onComplete={first} />,
    );
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Rebuild evidence" }));
  });
  view.rerender(
    <EvidencePreparation apiUrl="" datasetId="a" onComplete={latest} />,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(
    fetch.mock.calls.filter(([, options]) => options.method === "POST"),
  ).toHaveLength(1);
  expect(first).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledTimes(1);
});
