import { describe, it, expect, afterEach, vi } from "vitest";
import {
  act,
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import NavigationRegression from "./NavigationRegression";
import { validateNavigationReport, pairAttempts } from "./navigationReport";
import example from "./examples/navigation-synthetic.json";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("navigation comparisons", () => {
  it("labels synthetic evidence and exposes collision details", () => {
    render(<NavigationRegression />);
    expect(screen.getByText("Synthetic example")).toBeInTheDocument();
    expect(screen.getByText("Regression detected")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Review 1 worse outcome" }),
    );
    expect(
      screen.getByRole("region", { name: "Paired scenario evidence" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Observed")).toBeInTheDocument();
  });
  it("rejects false synthetic passes and malformed metrics", () => {
    expect(() =>
      validateNavigationReport({ ...example, status: "PASS" }),
    ).toThrow();
    expect(() =>
      validateNavigationReport({
        ...example,
        success_delta: { estimate: 0, ci95: [null, 1] },
      }),
    ).toThrow();
    expect(() =>
      validateNavigationReport({ ...example, attempts: [] }),
    ).toThrow();
  });
  it("keeps the current report when an import fails", async () => {
    render(<NavigationRegression />);
    fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
      target: { files: [{ size: 5, text: async () => "bad json" }] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "previous report is still displayed",
    );
    expect(screen.getByText("Regression detected")).toBeInTheDocument();
  });
  it("loads saved evaluation output", async () => {
    render(<NavigationRegression />);
    fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
      target: {
        files: [
          {
            name: "evaluation.json",
            size: 500,
            text: async () =>
              JSON.stringify({ ...example, suite_id: "imported-suite" }),
          },
        ],
      },
    });
    expect(await screen.findByText("imported-suite")).toBeInTheDocument();
  });
});

it("classifies paired evidence without ranking different failures", () => {
  const rows = structuredClone(example.attempts);
  expect(pairAttempts(rows)[0].change).toBe("New collision");
  rows[0].outcome = "timeout";
  rows[1].outcome = "crash";
  rows[1].collision = false;
  expect(pairAttempts(rows)[0].category).toBe("Needs review");
  rows[1].outcome = "success";
  expect(pairAttempts(rows)[0].category).toBe("Improvements");
  rows[0].outcome = "invalid";
  expect(pairAttempts(rows)[0].category).toBe("Needs review");
});
it("opens paired detail in one action and returns to its filter", async () => {
  const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  render(<NavigationRegression />);
  fireEvent.click(
    screen.getByRole("button", { name: "Review 1 worse outcome" }),
  );
  expect(
    screen.getByRole("button", { name: "Worse outcomes 1" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByText(/Contact timestamps, trajectories/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "← Back to comparison" }));
  expect(
    screen.queryByRole("region", { name: "Paired scenario evidence" }),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(scrollTo).toHaveBeenCalled());
});
it("retains invalid results for inspection and shows the evaluator reason", async () => {
  render(<NavigationRegression />);
  const invalid = structuredClone(example);
  invalid.status = "INVALID";
  invalid.reasons = ["Incomplete scoring evidence"];
  invalid.attempts[0].outcome = "invalid";
  invalid.attempts[0].completion_s = null;
  fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
    target: {
      files: [
        {
          name: "invalid.json",
          size: 500,
          text: async () => JSON.stringify(invalid),
        },
      ],
    },
  });
  expect(await screen.findByText("Evidence incomplete")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Needs review 1" }),
  ).toBeInTheDocument();
});
it("opens metrics for an aggregate regression without failed pairs", async () => {
  render(<NavigationRegression />);
  const aggregate = structuredClone(example);
  aggregate.attempts[1] = {
    ...aggregate.attempts[0],
    configuration: "candidate",
    run_id: "candidate-run",
  };
  aggregate.reasons = ["Comparison exceeds frozen margin"];
  fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
    target: {
      files: [
        {
          name: "aggregate.json",
          size: 500,
          text: async () => JSON.stringify(aggregate),
        },
      ],
    },
  });
  const review = await screen.findByRole("button", {
    name: "Review comparison metrics",
  });
  fireEvent.click(review);
  expect(
    screen.getByText("Evaluation details").closest("details"),
  ).toHaveAttribute("open");
});
it("rejects duplicate and incomplete paired schedules", async () => {
  render(<NavigationRegression />);
  const bad = {
    ...example,
    attempts: [example.attempts[0], example.attempts[0]],
  };
  fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
    target: {
      files: [
        {
          name: "duplicate.json",
          size: 500,
          text: async () => JSON.stringify(bad),
        },
      ],
    },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("Duplicate");
});

it("does not let a slower import replace a newer comparison", async () => {
  render(<NavigationRegression />);
  let finishFirst;
  const first = new Promise((resolve) => {
    finishFirst = resolve;
  });
  const input = screen.getByLabelText("Load navigation evaluation");
  fireEvent.change(input, {
    target: { files: [{ name: "old.json", size: 500, text: () => first }] },
  });
  fireEvent.change(input, {
    target: {
      files: [
        {
          name: "new.json",
          size: 500,
          text: async () =>
            JSON.stringify({ ...example, suite_id: "Newest suite" }),
        },
      ],
    },
  });
  expect(await screen.findByText("Newest suite")).toBeInTheDocument();
  await act(async () =>
    finishFirst(JSON.stringify({ ...example, suite_id: "Old suite" })),
  );
  expect(screen.queryByText("Old suite")).not.toBeInTheDocument();
  expect(screen.getByText("Newest suite")).toBeInTheDocument();
});
it("rejects contradictory outcomes and unsafe numeric identifiers", () => {
  const bad = structuredClone(example);
  bad.attempts[0].collision = true;
  expect(() => validateNavigationReport(bad)).toThrow();
  bad.attempts[0] = {
    ...example.attempts[0],
    seed: Number.MAX_SAFE_INTEGER + 1,
  };
  expect(() => validateNavigationReport(bad)).toThrow();
});
it("renders imported identifiers as inert text", async () => {
  render(<NavigationRegression />);
  const hostile = '<img src=x onerror="alert(1)">';
  fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
    target: {
      files: [
        {
          name: "text.json",
          size: 500,
          text: async () => JSON.stringify({ ...example, suite_id: hostile }),
        },
      ],
    },
  });
  expect(await screen.findByText(hostile)).toBeInTheDocument();
  expect(document.querySelector(".navigation-regression img")).toBeNull();
});

it("marks a candidate collision after baseline rejection as a worse outcome", () => {
  const rows = structuredClone(example.attempts);
  rows[0] = {
    ...rows[0],
    outcome: "rejected",
    collision: null,
    completion_s: null,
  };
  const pair = pairAttempts(rows)[0];
  expect(pair.category).toBe("Worse outcomes");
  expect(pair.change).toBe("New collision");
});

it.each(["PASS", "INCONCLUSIVE"])(
  "keeps lost success distinct from the %s suite decision",
  async (status) => {
    render(<NavigationRegression />);
    const report = structuredClone(example);
    report.evidence_kind = "simulator";
    report.status = status;
    report.reasons = ["Saved evaluator decision"];
    report.attempts[1] = {
      ...report.attempts[1],
      outcome: "timeout",
      collision: false,
    };
    fireEvent.change(screen.getByLabelText("Load navigation evaluation"), {
      target: {
        files: [
          {
            name: "evaluation.json",
            size: 500,
            text: async () => JSON.stringify(report),
          },
        ],
      },
    });
    expect(
      await screen.findByText(
        status === "PASS" ? "Suite gates passed" : "More evidence needed",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Regression/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Review 1 worse outcome" }),
    );
    expect(
      screen.getByRole("button", { name: "Worse outcomes 1" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("region", { name: "Paired scenario evidence" }),
    ).toHaveTextContent("Lost success");
  },
);

it.each([5001, 10000])(
  "accepts %i complete pairs within the CLI schedule limit",
  (count) => {
    const attempts = Array.from({ length: count }, (_, seed) =>
      example.attempts.map((row) => ({ ...row, seed })),
    ).flat();
    const report = { ...example, scheduled_pairs: count, attempts };
    expect(validateNavigationReport(report)).toBe(report);
  },
);

it("explains the pair and attempt limits", () => {
  expect(() =>
    validateNavigationReport({ ...example, scheduled_pairs: 10001 }),
  ).toThrow("10,000 pairs / 20,000 attempts");
  expect(() =>
    validateNavigationReport({
      ...example,
      attempts: Array(20001).fill(example.attempts[0]),
    }),
  ).toThrow("10,000 pairs / 20,000 attempts");
});

it("accepts files above the former limit and explains files above 32 MiB", async () => {
  render(<NavigationRegression />);
  const input = screen.getByLabelText("Load navigation evaluation");
  fireEvent.change(input, {
    target: {
      files: [
        {
          name: "larger.json",
          size: 15 * 1024 * 1024,
          text: async () =>
            JSON.stringify({ ...example, suite_id: "Large report" }),
        },
      ],
    },
  });
  expect(await screen.findByText("Large report")).toBeInTheDocument();
  const read = vi.fn();
  fireEvent.change(input, {
    target: {
      files: [
        { name: "oversized.json", size: 32 * 1024 * 1024 + 1, text: read },
      ],
    },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "viewer file-size limit of 32 MiB",
  );
  expect(read).not.toHaveBeenCalled();
  expect(screen.getByText("Large report")).toBeInTheDocument();
});
