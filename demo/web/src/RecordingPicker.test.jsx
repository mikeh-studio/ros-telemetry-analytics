import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RecordingPicker from "./RecordingPicker";

const datasets = [
  { dataset_id: "a", name: "Camera recording" },
  { dataset_id: "b", name: "TUM VI Room 4" },
];
describe("Recording picker", () => {
  it("supports keyboard selection, escape, and outside dismissal", () => {
    const onSelect = vi.fn();
    render(
      <RecordingPicker
        datasets={datasets}
        selected={datasets[0]}
        onSelect={onSelect}
      />,
    );
    const picker = screen.getByRole("combobox");
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    expect(picker).toHaveAttribute(
      "aria-activedescendant",
      "recording-option-1",
    );
    fireEvent.keyDown(picker, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("b");
    expect(picker).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(picker);
    fireEvent.keyDown(picker, { key: "Escape" });
    expect(picker).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(picker);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
