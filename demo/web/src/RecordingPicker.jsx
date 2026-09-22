import { useEffect, useRef, useState } from "react";
import { CaretDownIcon, CheckIcon } from "@phosphor-icons/react";

export default function RecordingPicker({ datasets, selected, onSelect }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef(null);
  const trigger = useRef(null);
  const search = useRef({ text: "", time: 0 });
  const options = datasets.filter(
    (d) => d.catalog_visible !== false || d.dataset_id === selected?.dataset_id,
  );
  if (selected && !options.some((d) => d.dataset_id === selected.dataset_id))
    options.unshift(selected);
  const chosen = Math.max(
    0,
    options.findIndex((d) => d.dataset_id === selected?.dataset_id),
  );
  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      if (!root.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  useEffect(() => {
    if (open)
      document
        .getElementById(`recording-option-${active}`)
        ?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);
  function choose(index) {
    if (options[index]) onSelect(options[index].dataset_id);
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div className="recording-menu" ref={root}>
      <span className="recording-label">Recording</span>
      <button
        ref={trigger}
        type="button"
        className="recording-trigger"
        role="combobox"
        aria-label="Dataset"
        value={selected?.dataset_id || ""}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls="recording-options"
        aria-activedescendant={
          open && options.length ? `recording-option-${active}` : undefined
        }
        onBlur={(e) => {
          if (!root.current?.contains(e.relatedTarget)) setOpen(false);
        }}
        onClick={() => {
          setActive(chosen);
          setOpen(!open);
        }}
        onKeyDown={(e) => {
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            setOpen(true);
            setActive((i) =>
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? options.length - 1
                  : !open
                    ? chosen
                    : Math.max(
                        0,
                        Math.min(
                          options.length - 1,
                          i + (e.key === "ArrowDown" ? 1 : -1),
                        ),
                      ),
            );
          } else if (e.key === "Escape") {
            e.preventDefault();
            setOpen(false);
          } else if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (open) choose(active);
            else {
              setActive(chosen);
              setOpen(true);
            }
          } else if (
            e.key.length === 1 &&
            !e.ctrlKey &&
            !e.metaKey &&
            !e.altKey
          ) {
            const now = Date.now();
            search.current = {
              text:
                (now - search.current.time < 700 ? search.current.text : "") +
                e.key.toLowerCase(),
              time: now,
            };
            const found = options.findIndex((d) =>
              d.name?.toLowerCase().startsWith(search.current.text),
            );
            if (found >= 0) {
              setActive(found);
              setOpen(true);
            }
          }
        }}
      >
        <span>{selected?.name || "Choose recording"}</span>
        <CaretDownIcon size={22} aria-hidden="true" />
      </button>
      {open && (
        <div
          className="recording-options"
          id="recording-options"
          role="listbox"
          aria-label="Recordings"
        >
          {options.map((d, i) => (
            <div
              key={d.dataset_id}
              id={`recording-option-${i}`}
              role="option"
              aria-selected={d.dataset_id === selected?.dataset_id}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => e.preventDefault()}
              onPointerMove={() => setActive(i)}
              onClick={() => choose(i)}
            >
              <span>
                {d.name}
                {!d.selectable && !d.capabilities
                  ? ` — ${d.status || "unavailable"}`
                  : ""}
              </span>
              {d.dataset_id === selected?.dataset_id && (
                <CheckIcon size={18} aria-hidden="true" />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
