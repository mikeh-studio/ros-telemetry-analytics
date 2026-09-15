import { useEffect, useMemo, useRef, useState } from "react";

const names = {
  all: "All events",
  detected: "Detected",
  missed: "Missed",
  false_alarm: "False alarms",
};
export const clock = (ms) =>
  Number.isFinite(ms)
    ? `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${((ms / 1000) % 60).toFixed(2).padStart(5, "0")}`
    : "Unavailable";
const number = (value, unit = "") =>
  Number.isFinite(value) ? `${Number(value.toFixed(3))}${unit}` : "Unavailable";

export function pathFor(samples, field, x, y, stepped = false) {
  let previous = null;
  return samples
    .map((sample) => {
      if (!Number.isFinite(sample[field])) {
        previous = null;
        return "";
      }
      const command =
        !previous ||
        sample.break_before ||
        sample.continuity !== previous.continuity ||
        sample.segment_id !== previous.segment_id ||
        sample.source_file !== previous.source_file ||
        sample.run_id !== previous.run_id
          ? "M"
          : "L";
      previous = sample;
      return stepped && command === "L"
        ? `H${x(sample).toFixed(2)}V${y(sample[field], sample).toFixed(2)}`
        : `${command}${x(sample).toFixed(2)},${y(sample[field], sample).toFixed(2)}`;
    })
    .join(" ");
}

export function sampleAt(samples, cursor, gapMs) {
  let found = null;
  for (const sample of samples) {
    if (sample.elapsed_ms > cursor) break;
    found = sample;
  }
  return found && cursor - found.elapsed_ms <= gapMs ? found : null;
}

function Trajectory({ samples, route = samples, current, selected, cursor }) {
  const geometry = useMemo(() => {
    const coords = [...route, ...samples]
      .flatMap((s) => [
        [s.ground_truth_x, s.ground_truth_y],
        [s.estimated_x, s.estimated_y],
      ])
      .filter((p) => p.every(Number.isFinite));
    if (!coords.length) return null;
    const xs = coords.map(([x]) => x),
      ys = coords.map(([, y]) => y);
    const minX = Math.min(...xs),
      minY = Math.min(...ys);
    const spanX = Math.max(0.1, Math.max(...xs) - minX),
      spanY = Math.max(0.1, Math.max(...ys) - minY);
    const scale = Math.min(540 / spanX, 270 / spanY);
    return {
      x: (v) => 30 + (540 - spanX * scale) / 2 + (v - minX) * scale,
      y: (v) => 295 - (270 - spanY * scale) / 2 - (v - minY) * scale,
      scale,
    };
  }, [samples, route]);
  if (!geometry)
    return <p>No finite trajectory coordinates in this interval.</p>;
  const { x, y, scale } = geometry;
  const plotted = (fieldX, fieldY, subset) =>
    pathFor(
      subset.map((s) =>
        Number.isFinite(s[fieldX]) ? s : { ...s, [fieldY]: null },
      ),
      fieldY,
      (s) => x(s[fieldX]),
      y,
    );
  const during = samples.map((s) =>
    s.elapsed_ms >= selected.start_ms && s.elapsed_ms <= selected.end_ms
      ? s
      : { ...s, estimated_y: null },
  );
  const past = samples.filter((s) => s.elapsed_ms <= cursor);
  return (
    <svg
      viewBox="0 0 600 330"
      className="investigation-map"
      role="img"
      aria-label="Selected event trajectory with ground-truth and estimated position markers"
    >
      <path
        d={plotted("ground_truth_x", "ground_truth_y", route)}
        className="investigation-route truth context"
      />
      <path
        d={plotted("estimated_x", "estimated_y", route)}
        className="investigation-route estimate context"
      />
      <path
        d={plotted("estimated_x", "estimated_y", during)}
        className={`investigation-route case-${selected.outcome}`}
      />
      <path
        d={plotted("ground_truth_x", "ground_truth_y", past)}
        className="investigation-route truth"
      />
      <path
        d={plotted("estimated_x", "estimated_y", past)}
        className="investigation-route estimate"
      />
      {current &&
        Number.isFinite(current.ground_truth_x) &&
        Number.isFinite(current.ground_truth_y) && (
          <circle
            cx={x(current.ground_truth_x)}
            cy={y(current.ground_truth_y)}
            r="6"
            className="truth-marker"
          >
            <title>Ground truth at {clock(current.elapsed_ms)}</title>
          </circle>
        )}
      {current &&
        Number.isFinite(current.estimated_x) &&
        Number.isFinite(current.estimated_y) && (
          <rect
            x={x(current.estimated_x) - 5}
            y={y(current.estimated_y) - 5}
            width="10"
            height="10"
            className="estimate-marker"
          >
            <title>Estimate at {clock(current.elapsed_ms)}</title>
          </rect>
        )}
      <path d="M30 309h60" className="plot-axis" />
      <text x="30" y="325">
        {number(60 / scale, " m")} · equal X/Y scale
      </text>
    </svg>
  );
}

const CHARTS = [
  {
    field: "position_error_m",
    label: "Position error",
    unit: " m",
    basis: "Evaluation only · ground truth required",
  },
  {
    field: "particle_position_spread_m",
    label: "Particle spread",
    unit: " m",
    threshold: "particle_spread_warn_m",
  },
  {
    field: "estimated_pose_jump_m",
    label: "Estimated pose jump",
    unit: " m",
    threshold: "pose_jump_warn_m",
  },
  {
    field: "detector_score",
    label: "Detector score",
    unit: "",
    fixedThreshold: 1,
  },
  { field: "detector_failure", label: "Alert state", unit: "", boolean: true },
];

function EvidenceChart({
  spec,
  samples,
  selected,
  current,
  interval,
  cursor,
  onSeek,
  thresholds,
}) {
  const plot = useRef(null);
  const [width, setWidth] = useState(780);
  useEffect(() => {
    if (!plot.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(240, entry.contentRect.width)),
    );
    observer.observe(plot.current);
    return () => observer.disconnect();
  }, []);
  const right = width - 20;
  const plotWidth = right - 40;
  const rows = spec.boolean
    ? samples.map((s) => ({
        ...s,
        detector_failure:
          s.detector_failure == null ? null : Number(s.detector_failure),
      }))
    : samples;
  const threshold = spec.fixedThreshold ?? thresholds[spec.threshold];
  const max =
    Math.max(
      1,
      threshold || 0,
      ...rows.map((s) => (Number.isFinite(s[spec.field]) ? s[spec.field] : 0)),
    ) * 1.1;
  const duration = Math.max(1, interval.end_ms - interval.start_ms);
  const x = (time) => 40 + ((time - interval.start_ms) / duration) * plotWidth;
  const y = (value) => 86 - (value / max) * 66;
  const clampX = (time) => Math.max(40, Math.min(right, x(time)));
  const active = samples.filter((s) => s.label_failure);
  return (
    <div className="evidence-chart">
      <div>
        <strong>{spec.label}</strong>
        <span>
          {spec.boolean
            ? current?.detector_failure == null
              ? "Unavailable"
              : current.detector_failure
                ? "Alert active"
                : "No alert"
            : number(current?.[spec.field], spec.unit)}
        </span>
        <small>
          {spec.basis || "Available during operation"}
          {Number.isFinite(threshold) &&
            ` · threshold ${number(threshold, spec.unit)}`}
        </small>
      </div>
      <svg
        ref={plot}
        viewBox={`0 0 ${width} 112`}
        role="img"
        aria-label={`${spec.label} over selected interval; use the playback time slider to inspect`}
        onPointerDown={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          onSeek(
            Math.max(
              interval.start_ms,
              Math.min(
                interval.end_ms,
                interval.start_ms +
                  ((((event.clientX - rect.left) / rect.width) * width - 40) /
                    plotWidth) *
                    duration,
              ),
            ),
          );
        }}
      >
        <rect
          x={clampX(selected.start_ms)}
          y="12"
          width={Math.max(
            1,
            clampX(selected.end_ms) - clampX(selected.start_ms),
          )}
          height="74"
          className={`event-band case-${selected.outcome}`}
        />
        {active.map((s, i) => (
          <path
            key={`${s.sample_index}:${i}`}
            d={`M${x(s.elapsed_ms)} 89v4`}
            className="label-band"
          />
        ))}
        <path d={`M40 12V86H${right}`} className="plot-axis" />
        {Number.isFinite(threshold) && (
          <path d={`M40 ${y(threshold)}H${right}`} className="plot-expected" />
        )}
        <path
          d={pathFor(rows, spec.field, (s) => x(s.elapsed_ms), y, spec.boolean)}
          className="evidence-series"
        />
        <path d={`M${x(cursor)} 10V94`} className="plot-cursor" />
        <text x="35" y="20" textAnchor="end">
          {number(max)}
        </text>
        <text x="35" y="86" textAnchor="end">
          0
        </text>
        <text x="40" y="108">
          {clock(interval.start_ms)}
        </text>
        <text x={right} y="108" textAnchor="end">
          {clock(interval.end_ms)}
        </text>
      </svg>
    </div>
  );
}

export function decisionText(selected, samples, thresholds) {
  const within = samples.filter(
    (s) => s.elapsed_ms >= selected.start_ms && s.elapsed_ms <= selected.end_ms,
  );
  const fields = [
    {
      field: "particle_position_spread_m",
      threshold: thresholds.particle_spread_warn_m,
      name: "particle spread",
      unit: " m",
    },
    {
      field: "estimated_pose_jump_m",
      threshold: thresholds.pose_jump_warn_m,
      name: "pose jump",
      unit: " m",
    },
  ];
  if (Number.isFinite(thresholds.heading_spread_warn_rad))
    fields.push({
      field: "particle_heading_spread_rad",
      threshold: thresholds.heading_spread_warn_rad,
      name: "heading spread",
      unit: " rad",
    });
  const evidence = fields.map((spec) => {
    const values = within.map((s) => s[spec.field]).filter(Number.isFinite);
    const peak = values.length ? Math.max(...values) : null;
    const crossing = within.find(
      (s) =>
        Number.isFinite(s[spec.field]) &&
        Number.isFinite(spec.threshold) &&
        s[spec.field] > spec.threshold,
    );
    return { ...spec, peak, crossing };
  });
  const available =
    within.length > 0 &&
    evidence.every(
      (s) =>
        Number.isFinite(s.threshold) &&
        within.every((row) => Number.isFinite(row[s.field])),
    );
  const crossed = evidence.filter((s) => s.crossing);
  const opening =
    selected.outcome === "detected"
      ? `A detector alert matched this labeled failure. Detection delay: ${number(selected.onset_lag_ms, " ms")}.`
      : selected.outcome === "false_alarm"
        ? "This detector alert did not match a labeled failure under the evaluation’s matching rules. That alone does not establish the physical cause."
        : "No detector alert matched this labeled failure under the evaluation’s matching rules.";
  const explanation = !available
    ? "Some detector inputs are missing; the threshold explanation is incomplete."
    : crossed.length
      ? `Recorded threshold crossings: ${crossed.map((s) => s.name).join(", ")}. Event matching and recovery rules also affect the final outcome.`
      : `No recorded detector input exceeded its configured threshold during this event.${thresholds.recovery_hold_ms > 0 ? " An alert may still be held from an earlier crossing under the recovery-hold setting." : ""}`;
  return { opening, explanation, evidence };
}

function Session({ investigation, summary, apiUrl, active = true }) {
  const cases = investigation.cases || [];
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(cases[0]?.case_id);
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState(0);
  const [steppedIndex, setSteppedIndex] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(true);
  const visible = cases.filter((c) => filter === "all" || c.outcome === filter);
  const selected = visible.find((c) => c.case_id === selectedId) || visible[0];
  const interval = loaded?.case_id === selected?.case_id ? loaded : null;
  const samples = interval?.samples || [];
  const current =
    steppedIndex != null
      ? samples[steppedIndex]
      : sampleAt(samples, cursor, interval?.gap_threshold_ms || 100);
  const currentIndex = current ? samples.indexOf(current) : -1;
  const thresholds = summary.thresholds || {};
  const selectedIndex = visible.findIndex(
    (c) => c.case_id === selected?.case_id,
  );
  useEffect(() => {
    setPlaying(false);
    setSteppedIndex(null);
    setLoaded(null);
    setError("");
    if (!selected) return;
    const abort = new AbortController();
    let active = true;
    const params = new URLSearchParams({
      case_id: selected.case_id,
      evaluation_id: investigation.evaluation_id,
    });
    fetch(`${apiUrl}/api/localization/interval?${params}`, {
      signal: abort.signal,
    })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.detail || "Unable to load this interval");
        if (
          !body.samples?.length ||
          body.evaluation_id !== investigation.evaluation_id ||
          body.case_id !== selected.case_id
        )
          throw new Error("Interval evidence does not match this selection");
        if (active) {
          setLoaded(body);
          setCursor(body.start_ms);
        }
      })
      .catch((e) => {
        if (active && e.name !== "AbortError") setError(e.message);
      });
    return () => {
      active = false;
      abort.abort();
    };
  }, [selected?.case_id, investigation.evaluation_id, apiUrl]);
  useEffect(() => {
    if (!active) setPlaying(false);
  }, [active]);
  useEffect(() => {
    if (!playing || !interval || !active) return;
    let last = performance.now();
    const timer = setInterval(() => {
      const now = performance.now(),
        delta = (now - last) * speed;
      last = now;
      setCursor((value) => {
        const next = value + delta;
        if (next >= interval.end_ms) {
          if (loop && interval.end_ms > interval.start_ms)
            return interval.start_ms;
          setPlaying(false);
          return interval.end_ms;
        }
        return next;
      });
    }, 50);
    return () => clearInterval(timer);
  }, [playing, interval, loop, speed, active]);
  const seek = (value) => {
    setPlaying(false);
    setSteppedIndex(null);
    setCursor(value);
  };
  const step = (direction) => {
    const index =
      currentIndex >= 0
        ? currentIndex + direction
        : direction > 0
          ? samples.findIndex((s) => s.elapsed_ms > cursor)
          : samples.findLastIndex((s) => s.elapsed_ms < cursor);
    if (index >= 0 && index < samples.length) {
      setPlaying(false);
      setSteppedIndex(index);
      setCursor(samples[index].elapsed_ms);
    }
  };
  const decision =
    selected && interval ? decisionText(selected, samples, thresholds) : null;
  return (
    <>
      <div
        className="investigation-filters"
        role="group"
        aria-label="Filter localization events"
      >
        {Object.entries(names).map(([key, name]) => (
          <button
            key={key}
            aria-pressed={filter === key}
            onClick={() => {
              setPlaying(false);
              setFilter(key);
            }}
          >
            {name}{" "}
            <strong>
              {key === "all"
                ? cases.length
                : cases.filter((c) => c.outcome === key).length}
            </strong>
          </button>
        ))}
      </div>
      <div className="investigation-layout">
        <aside className="investigation-cases" aria-label="Localization events">
          <div className="event-navigation">
            <button
              disabled={selectedIndex <= 0}
              onClick={() => setSelectedId(visible[selectedIndex - 1].case_id)}
            >
              Previous event
            </button>
            <button
              disabled={
                selectedIndex < 0 || selectedIndex >= visible.length - 1
              }
              onClick={() => setSelectedId(visible[selectedIndex + 1].case_id)}
            >
              Next event
            </button>
          </div>
          <ol>
            {visible.map((c) => (
              <li key={c.case_id}>
                <button
                  aria-pressed={selected?.case_id === c.case_id}
                  onClick={() => setSelectedId(c.case_id)}
                >
                  <strong>
                    {names[c.outcome]} · {clock(c.start_ms)}
                  </strong>
                  <span>
                    {number(c.duration_ms / 1000, " s")} duration
                    {c.outcome === "detected"
                      ? ` · ${number(c.onset_lag_ms, " ms")} delay`
                      : ""}
                  </span>
                  <small>
                    {c.source_file} · segment {c.segment_id}
                  </small>
                </button>
              </li>
            ))}
          </ol>
          {!visible.length && <p>No events in this category.</p>}
        </aside>
        <div
          className="investigation-inspector"
          aria-busy={Boolean(selected && !interval && !error)}
        >
          {!selected ? (
            <p>Select a category with events to investigate.</p>
          ) : error ? (
            <p role="alert">{error}</p>
          ) : !interval ? (
            <p role="status">Loading event evidence…</p>
          ) : (
            <>
              <div className="investigation-case-title">
                <h3>
                  {names[selected.outcome]} · {clock(selected.start_ms)}–
                  {clock(selected.end_ms)}
                </h3>
                <span>{interval.sample_count} samples · full resolution</span>
              </div>
              <p className="investigation-legend">
                ○ Ground truth · □ AMCL estimate · highlighted path: selected
                event · faint paths: full recording segment (sampled)
              </p>
              <Trajectory
                samples={samples}
                route={interval.route || samples}
                current={current}
                selected={selected}
                cursor={cursor}
              />
              <div className="investigation-controls">
                <button
                  disabled={interval.end_ms <= interval.start_ms}
                  onClick={() => {
                    setSteppedIndex(null);
                    if (!playing && cursor >= interval.end_ms)
                      setCursor(interval.start_ms);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? "Pause interval" : "Play interval"}
                </button>
                <button disabled={currentIndex === 0} onClick={() => step(-1)}>
                  Previous sample
                </button>
                <button
                  disabled={currentIndex === samples.length - 1}
                  onClick={() => step(1)}
                >
                  Next sample
                </button>
                <label>
                  Interval speed{" "}
                  <select
                    value={speed}
                    onChange={(e) => setSpeed(Number(e.target.value))}
                  >
                    {[0.25, 0.5, 1, 2, 5].map((n) => (
                      <option key={n} value={n}>
                        {n}×
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={loop}
                    onChange={(e) => setLoop(e.target.checked)}
                  />{" "}
                  Loop interval
                </label>
              </div>
              <label className="investigation-scrubber">
                Playback time <output>{clock(cursor)}</output>
                <input
                  aria-label="Playback time"
                  aria-valuetext={clock(cursor)}
                  type="range"
                  min={interval.start_ms}
                  max={interval.end_ms}
                  step="any"
                  value={cursor}
                  onChange={(e) => seek(Number(e.target.value))}
                />
              </label>
              <p className="investigation-note">
                Independent recording clock · up to 5 seconds of context on each
                side · no interpolation across gaps.{" "}
                {current
                  ? `Showing sample ${current.sample_index ?? ""} at ${clock(current.elapsed_ms)}.`
                  : "No sample at this time; position markers are hidden."}
              </p>
              <div className="investigation-evidence">
                <h3>Evidence at the shared time cursor</h3>
                <p>
                  Shaded band: selected event. Lower ticks: labeled failure
                  samples. Dashed line: configured threshold. Click a chart or
                  use the playback slider to inspect a time.
                </p>
                {[
                  ...CHARTS.slice(0, 3),
                  ...(Number.isFinite(thresholds.heading_spread_warn_rad)
                    ? [
                        {
                          field: "particle_heading_spread_rad",
                          label: "Heading spread",
                          unit: " rad",
                          threshold: "heading_spread_warn_rad",
                        },
                      ]
                    : []),
                  ...CHARTS.slice(3),
                ].map((spec) => (
                  <EvidenceChart
                    key={spec.field}
                    spec={spec}
                    samples={samples}
                    selected={selected}
                    current={current}
                    interval={interval}
                    cursor={cursor}
                    onSeek={seek}
                    thresholds={thresholds}
                  />
                ))}
              </div>
              <article className="detector-explanation">
                <h3>Why this outcome?</h3>
                <p>{decision.opening}</p>
                <p>{decision.explanation}</p>
                <dl>
                  {decision.evidence.map((e) => (
                    <div key={e.field}>
                      <dt>{e.name}</dt>
                      <dd>
                        Peak {number(e.peak, e.unit)} · threshold{" "}
                        {number(e.threshold, e.unit)} ·{" "}
                        {e.crossing
                          ? `first crossing ${clock(e.crossing.elapsed_ms)}`
                          : "no crossing observed"}
                      </dd>
                    </div>
                  ))}
                </dl>
                {selected.outcome === "detected" && (
                  <p>
                    Recorded recovery:{" "}
                    {Number.isFinite(selected.observed_end_timestamp_ns)
                      ? clock(selected.end_ms + (selected.recovery_lag_ms || 0))
                      : "Unavailable"}
                    . Recovery delay relative to the label:{" "}
                    {number(selected.recovery_lag_ms, " ms")}.
                  </p>
                )}
                <p>
                  Ground truth and published labels are scoring-only. These
                  observations explain detector behavior; physical cause remains
                  unconfirmed.
                </p>
              </article>
            </>
          )}
        </div>
      </div>
    </>
  );
}

export default function LocalizationInvestigation({
  evaluation,
  apiUrl,
  overview,
  standalone = false,
  active = true,
}) {
  const summary = evaluation.summary || {},
    investigation = evaluation.investigation || {};
  const available = evaluation.status === "available";
  const [open, setOpen] = useState(false);
  const [visited, setVisited] = useState(active);
  useEffect(() => {
    if (active) setVisited(true);
  }, [active]);
  const Container = standalone ? "section" : "details";
  const sample = summary.sample_metrics || {},
    event = summary.event_metrics || {};
  const dataset =
    (investigation.dataset || summary.dataset_adapter) ===
    "tuhh_robot_localization_failure_prediction_v1"
      ? "TUHH localization failure dataset"
      : investigation.dataset || summary.dataset_adapter || "Saved evaluation";
  return (
    <Container
      className="localization-investigation"
      onToggle={standalone ? undefined : (e) => setOpen(e.currentTarget.open)}
    >
      {standalone ? (
        <header className="workspace-heading investigation-heading">
          <h2>Localization Investigation</h2>
          <span className="workspace-mode">Recorded dataset</span>
          <p>Select a failure, replay its interval, inspect the evidence.</p>
          {available && (
            <div
              className="recording-context"
              aria-label="Investigation recording"
            >
              <span>{dataset}</span>
              <span>Duration {clock(investigation.duration_ms)}</span>
              <span>Independent replay clock</span>
            </div>
          )}
        </header>
      ) : (
        <>
          <summary>
            <strong>Localization Investigation</strong>
            <span>
              {available ? "Evaluation loaded" : "Evaluation unavailable"}
            </span>
          </summary>
          <p className="investigation-note">
            Separate recording from the main mission. Select a failure, replay
            its interval, and inspect the detector’s evidence.
          </p>
        </>
      )}
      {available ? (
        <>
          {!standalone && (
            <div className="investigation-context">
              <span>Dataset: {dataset}</span>
              <span>
                Recording duration: {clock(investigation.duration_ms)}
              </span>
            </div>
          )}
          <details className="evaluation-results">
            <summary>Evaluation results and detector configuration</summary>
            <div className="investigation-context">
              <span>
                Detector version:{" "}
                {investigation.detector_version || "Not recorded"}
              </span>
              <span>
                Configuration:{" "}
                {investigation.configuration_id || "See recorded thresholds"}
              </span>
            </div>
            <p className="investigation-note">
              {(investigation.recordings || summary.input_files || []).join(
                " · ",
              )}
            </p>
            <div className="evaluation-metrics">
              {[
                ["Sample precision", sample.precision],
                ["Sample recall", sample.recall],
                ["Sample F1", sample.f1],
                ["Event precision", event.precision],
                ["Event recall", event.recall],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>
                    {Number.isFinite(value) ? value.toFixed(3) : "—"}
                  </strong>
                </div>
              ))}
            </div>
            <p>
              {event.matched_event_count ?? "—"} detected ·{" "}
              {Number.isFinite(event.expected_event_count)
                ? event.expected_event_count - event.matched_event_count
                : "—"}{" "}
              missed · {event.false_alarm_event_count ?? "—"} false alarms.
              Sample scores count labeled samples; event scores count matched
              intervals.
            </p>
            <p>
              Detector inputs:{" "}
              {(summary.detector_inputs || []).join(", ") || "Not recorded"}.
              Ground truth and published labels are scoring-only.
            </p>
            <dl>
              {Object.entries(summary.thresholds || {}).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
          {(standalone ? visited : open) &&
            (investigation.status === "available" ? (
              <Session
                active={active}
                key={investigation.evaluation_id}
                investigation={investigation}
                summary={summary}
                apiUrl={apiUrl}
              />
            ) : (
              <>
                <p role="status">
                  {investigation.detail ||
                    "Detailed investigation evidence is unavailable for this evaluation. The overview and saved scores remain available."}
                </p>
                {overview}
              </>
            ))}
        </>
      ) : (
        <p>
          {evaluation.detail ||
            "Load a saved localization evaluation to investigate its failures."}
        </p>
      )}
    </Container>
  );
}
