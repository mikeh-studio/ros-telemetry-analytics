import { useEffect, useState } from "react";
import "./RecordingInvestigation.css";

async function get(url, signal) {
  const response = await fetch(url, { signal });
  const body = await response.json();
  if (!response.ok)
    throw new Error(body.detail || "Recorded evidence is unavailable");
  return body;
}
const number = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });

function Plot({ series, start, end, cursor, events, topicHealth, onCursor }) {
  const points = series.points.filter((p) => p.count);
  const kinds = {
    mean_intensity: ["dark_frames", "bright_frames"],
    sharpness_score: ["low_sharpness"],
    inter_message_gap_ms: ["reference_gap", "recorded_gap"],
    valid_range_fraction: ["low_valid_range_fraction"],
  };
  const relevant = events.filter(
    (e) =>
      e.topic === series.topic &&
      kinds[series.field]?.includes(e.event_type) &&
      Number.isFinite(e.threshold),
  );
  if (series.field === "inter_message_gap_ms") {
    const health = topicHealth?.find((row) => row.topic === series.topic);
    if (health?.gap_threshold_s != null && !relevant.length)
      relevant.push({ threshold: health.gap_threshold_s * 1000 });
  }
  const values = points
    .flatMap((p) => [p.min, p.max])
    .concat(relevant.map((e) => e.threshold));
  let low = values.length ? Math.min(...values) : 0;
  let high = values.length ? Math.max(...values) : 1;
  if (high === low) {
    high += 0.5;
    low -= 0.5;
  }
  const x = (t) => 45 + ((t - start) / (end - start)) * 625;
  const y = (v) => 105 - ((v - low) / (high - low)) * 90;
  return (
    <figure className="recording-plot">
      <figcaption>
        <strong>{series.field.replaceAll("_", " ")}</strong>
        <span>
          {series.unit} · {series.topic} · {series.frame || "frame unspecified"}
        </span>
      </figcaption>
      <svg
        viewBox="0 0 700 135"
        role="img"
        aria-label={`${series.field} for ${series.topic}`}
        onClick={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          onCursor(
            start +
              Math.max(
                0,
                Math.min(
                  1,
                  (((event.clientX - bounds.left) / bounds.width) * 700 - 45) /
                    625,
                ),
              ) *
                (end - start),
          );
        }}
      >
        {events
          .filter(
            (e) =>
              e.topic === series.topic && e.end_s >= start && e.start_s <= end,
          )
          .map((e, i) => (
            <rect
              key={i}
              x={x(Math.max(start, e.start_s))}
              y="10"
              width={Math.max(
                2,
                x(Math.min(end, e.end_s)) - x(Math.max(start, e.start_s)),
              )}
              height="100"
              fill="#d5964430"
            />
          ))}
        <text x="1" y="19">
          {number(high)}
        </text>
        <text x="1" y="106">
          {number(low)}
        </text>
        {relevant.map((e, i) => (
          <line
            key={i}
            x1="45"
            x2="670"
            y1={y(e.threshold)}
            y2={y(e.threshold)}
            stroke="#d3a94c"
            strokeDasharray="4 3"
          >
            <title>
              Configured threshold {number(e.threshold)} {e.unit}
            </title>
          </line>
        ))}
        {points.map((p, i) => (
          <g key={i}>
            <line
              x1={x(p.t)}
              x2={x(p.t)}
              y1={y(p.min)}
              y2={y(p.max)}
              stroke="#63c4bd"
              strokeWidth="2"
            />
            <circle cx={x(p.t)} cy={y(p.value)} r="1.5" fill="#63c4bd">
              <title>
                {number(p.t)}s: {number(p.min)}–{number(p.max)}, n={p.count}
              </title>
            </circle>
          </g>
        ))}
        <line x1={x(cursor)} x2={x(cursor)} y1="10" y2="110" stroke="#ff8c93" />
        <text x="45" y="130">
          {number(start)}s
        </text>
        <text x="625" y="130">
          {number(end)}s
        </text>
      </svg>
    </figure>
  );
}

function Preview({ item }) {
  const extent = Math.max(
    1,
    ...(item.points || []).flatMap((p) => p.map(Math.abs)),
  );
  return (
    <figure className="recording-preview">
      {item.image ? (
        <img
          src={item.image}
          alt={`${item.topic} at ${number(item.t)} seconds`}
        />
      ) : item.points ? (
        <svg
          viewBox="-110 -110 220 220"
          role="img"
          aria-label={`Laser scan ${item.topic} at ${number(item.t)} seconds`}
        >
          <circle r="100" fill="none" stroke="#45595f" />
          <path d="M-100 0H100M0-100V100" stroke="#45595f" />
          {item.points.map(([x, y], i) => (
            <circle
              key={i}
              cx={(x / extent) * 95}
              cy={(-y / extent) * 95}
              r="1.2"
              fill="#63c4bd"
            />
          ))}
          <circle r="3" fill="#ff8c93" />
          <text x="-100" y="108">
            ±{number(extent)} m · sensor frame
          </text>
        </svg>
      ) : (
        <p>{item.detail || "No supported visual preview"}</p>
      )}
      <figcaption>
        <strong>
          {number(item.t)} s · {item.verified ? "source checked" : "unverified"}
        </strong>
        <span>
          {item.topic} · header.frame_id: {item.frame_id || "none"}
        </span>
        <span>
          {item.preview_scale ||
            `Every ${item.sample_stride} beam(s); invalid returns omitted`}
        </span>
        <code>{item.timestamp_ns} ns</code>
      </figcaption>
    </figure>
  );
}

export default function RecordingInvestigation({ apiUrl, active, datasetId }) {
  const selected = datasetId;
  const [detail, setDetail] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [window, setWindow] = useState(null);
  const [draft, setDraft] = useState([0, 10]);
  const [cursor, setCursor] = useState(0);
  const [caseId, setCaseId] = useState("");
  const [plots, setPlots] = useState([]);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    setDetail(null);
    setData(null);
    setWindow(null);
    setError("");
    setCaseId("");
    if (!active || !selected) return;
    const controller = new AbortController();
    get(
      `${apiUrl}/api/investigations/${encodeURIComponent(selected)}`,
      controller.signal,
    )
      .then((body) => {
        if (controller.signal.aborted) return;
        setDetail(body);
        const bounds = [0, body.duration_s];
        setDraft(bounds);
        setWindow(bounds);
        setCursor(0);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [selected, apiUrl, active, refresh]);

  useEffect(() => {
    setData(null);
    if (!detail || !window || !active) return;
    const controller = new AbortController();
    const query = new URLSearchParams({
      analysis_id: detail.analysis_id,
      start_s: window[0],
      end_s: window[1],
    });
    get(
      `${apiUrl}/api/investigations/${encodeURIComponent(selected)}/interval?${query}`,
      controller.signal,
    )
      .then((body) => {
        if (
          controller.signal.aborted ||
          body.analysis_id !== detail.analysis_id
        )
          return;
        setData(body);
        const study = detail.cases.find((c) => c.id === caseId);
        const desired =
          study?.plots ||
          (selected.startsWith("liloc")
            ? ["valid_range_fraction", "linear_x", "inter_message_gap_ms"]
            : ["mean_intensity", "sharpness_score", "inter_message_gap_ms"]);
        setPlots(
          desired.map((field, i) => {
            const topic = study?.topics?.[i];
            const index = body.series.findIndex(
              (s) => s.field === field && (!topic || s.topic === topic),
            );
            return index >= 0 ? index : 0;
          }),
        );
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [detail, window, selected, apiUrl, active, caseId]);

  const study = detail?.cases.find((c) => c.id === caseId);
  function chooseCase(id) {
    setError("");
    setCaseId(id);
    const item = detail.cases.find((c) => c.id === id);
    const bounds = item ? [item.start_s, item.end_s] : [0, detail.duration_s];
    setWindow(bounds);
    setDraft(bounds);
    setCursor(item?.focus_s ?? bounds[0]);
  }
  const nearest = data
    ? [...data.previews]
        .sort((a, b) => Math.abs(a.t - cursor) - Math.abs(b.t - cursor))
        .slice(0, 6)
        .sort((a, b) => a.t - b.t)
    : [];
  return (
    <div className="recording-investigation">
      <div className="recording-heading">
        <div>
          <p className="eyebrow">RECORDED EVIDENCE</p>
          <h2>Small questions. Inspectable answers.</h2>
          <p>
            Explore recorded signals and source samples without starting a
            replay.
          </p>
        </div>
        <button onClick={() => setRefresh((n) => n + 1)}>
          Refresh evidence
        </button>
      </div>
      {error && (
        <p role="alert" className="recording-error">
          {error}. Prepare evidence with{" "}
          <code>python scripts/prepare_investigations.py</code>, then refresh.
        </p>
      )}
      {!selected && !error && (
        <p>
          No prepared recordings. Fetch the comparison pack and prepare evidence
          using the repository guide.
        </p>
      )}
      {detail && (
        <>
          <div className="recording-summary">
            <span>Real recording · {number(detail.duration_s)} s</span>
            <span>{number(detail.message_count)} messages</span>
            <span>
              {detail.verified_previews}/{detail.preview_count} previews
              reconciled
            </span>
            <span>{detail.extraction_errors} extraction errors</span>
          </div>
          <p>
            {detail.purpose}. {detail.interpretation}
          </p>
          <label className="recording-select">
            Investigation
            <select value={caseId} onChange={(e) => chooseCase(e.target.value)}>
              <option value="">Explore recording / nominal intervals</option>
              {detail.cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.question}
                </option>
              ))}
            </select>
          </label>
          {study && (
            <article className="recording-case">
              <h3>{study.question}</h3>
              <p>
                <strong>Observation:</strong> {study.observation}
              </p>
              <p>
                <strong>Conclusion:</strong> {study.conclusion}
              </p>
              <p>
                <strong>Next check:</strong> {study.next_check}
              </p>
              <p className="recording-muted">{study.limits}</p>
            </article>
          )}
          <form
            className="recording-window"
            onSubmit={(e) => {
              e.preventDefault();
              if (
                draft[0] >= 0 &&
                draft[0] < draft[1] &&
                draft[1] <= detail.duration_s
              ) {
                setError("");
                setCaseId("");
                setWindow([...draft]);
                setCursor(draft[0]);
              } else setError("Choose an interval inside the recording");
            }}
          >
            <label>
              From (s)
              <input
                aria-label="Interval start seconds"
                type="number"
                step="any"
                min="0"
                max={detail.duration_s}
                value={draft[0]}
                onChange={(e) => setDraft([Number(e.target.value), draft[1]])}
              />
            </label>
            <label>
              To (s)
              <input
                aria-label="Interval end seconds"
                type="number"
                step="any"
                min="0"
                max={detail.duration_s}
                value={draft[1]}
                onChange={(e) => setDraft([draft[0], Number(e.target.value)])}
              />
            </label>
            <button type="submit">Inspect interval</button>
          </form>
          {data && window ? (
            <>
              <label className="recording-cursor">
                Shared recorded-time cursor · {number(cursor)} s
                <input
                  aria-label="Recorded time cursor"
                  type="range"
                  min={window[0]}
                  max={window[1]}
                  step="0.001"
                  value={cursor}
                  onChange={(e) => setCursor(Number(e.target.value))}
                />
              </label>
              <details className="recording-availability">
                <summary>
                  Topic availability · reference streams labeled
                </summary>
                {data.series
                  .filter((s) => s.domain === "timing")
                  .map((s) => (
                    <div key={s.topic}>
                      <span>
                        {s.topic}
                        {detail.reference_topics.includes(s.topic)
                          ? " · reference"
                          : ""}
                      </span>
                      <svg
                        viewBox="0 0 720 10"
                        role="img"
                        aria-label={`${s.topic} recorded interval availability`}
                      >
                        {s.points.map((p, i) => (
                          <rect
                            key={i}
                            x={i * 3}
                            y="0"
                            width="3"
                            height="10"
                            fill={p.count ? "#63c4bd" : "#222c31"}
                          />
                        ))}
                      </svg>
                    </div>
                  ))}
                <p>
                  Colored buckets contain inter-message interval samples. Gray
                  buckets contain none; this is not a packet-loss measurement.
                </p>
              </details>
              <p className="recording-muted">
                Min–max bars and mean dots in 240 time buckets; empty buckets
                stay blank. Amber bands mark recorded events; dashed lines show
                matching configured thresholds. Click a plot or move the cursor.
              </p>
              <div className="recording-plots">
                {plots.map(
                  (index, slot) =>
                    data.series[index] && (
                      <div key={slot}>
                        <label>
                          Signal {slot + 1}
                          <select
                            aria-label={`Signal ${slot + 1}`}
                            value={index}
                            onChange={(e) =>
                              setPlots(
                                plots.map((v, i) =>
                                  i === slot ? Number(e.target.value) : v,
                                ),
                              )
                            }
                          >
                            {data.series.map((s, i) => (
                              <option key={i} value={i}>
                                {s.topic} · {s.field}
                              </option>
                            ))}
                          </select>
                        </label>
                        <Plot
                          series={data.series[index]}
                          start={window[0]}
                          end={window[1]}
                          cursor={cursor}
                          events={data.events}
                          topicHealth={detail.topic_health}
                          onCursor={setCursor}
                        />
                      </div>
                    ),
                )}
              </div>
              <h3>Source samples near the cursor</h3>
              <p className="recording-muted">
                {data.preview_policy} The six nearest available samples are
                shown at their actual times.
              </p>
              <div className="recording-previews">
                {nearest.map((item) => (
                  <Preview key={item.id} item={item} />
                ))}
              </div>
              {!nearest.length && (
                <p>
                  No cached source samples in this interval. Broaden the
                  interval to inspect the prepared controls.
                </p>
              )}
              <details>
                <summary>
                  Events · {data.event_count} in interval
                  {data.events_truncated ? " (first 200 shown)" : ""}
                </summary>
                <div className="recording-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Time (s)</th>
                        <th>Topic</th>
                        <th>Observation</th>
                        <th>Value / threshold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.events
                        .filter(
                          (e) => e.end_s >= window[0] && e.start_s <= window[1],
                        )
                        .map((e, i) => (
                          <tr key={i}>
                            <td>
                              {number(e.start_s)}–{number(e.end_s)}
                            </td>
                            <td>{e.topic}</td>
                            <td>
                              {e.event_type}
                              <br />
                              {e.detail}
                            </td>
                            <td>
                              {number(e.observed_value)} / {number(e.threshold)}{" "}
                              {e.unit}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          ) : (
            !error && <p role="status">Loading recorded signals…</p>
          )}
          <details>
            <summary>Coverage and provenance</summary>
            <p>
              <a href={detail.source} target="_blank" rel="noreferrer">
                Original dataset source
              </a>{" "}
              · {detail.license} · {detail.integrity.replaceAll("_", " ")}{" "}
              (local identity; not an upstream checksum certification)
            </p>
            <p>
              Analysis: <code>{detail.analysis_id}</code> · {detail.created_at}
            </p>
            <p className="recording-digest">
              Source SHA-256: <code>{detail.source_sha256}</code>
            </p>
            <div className="recording-table">
              <table>
                <thead>
                  <tr>
                    <th>Topic</th>
                    <th>Coverage</th>
                    <th>Analyzed / source messages</th>
                    <th>Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.coverage.map((row) => (
                    <tr key={row.topic}>
                      <td>
                        {row.topic}
                        {detail.reference_topics.includes(row.topic)
                          ? " (reference context)"
                          : ""}
                      </td>
                      <td>
                        {row.analysis_status}
                        <br />
                        {row.detail}
                      </td>
                      <td>
                        {row.analyzed_message_count} / {row.message_count}
                      </td>
                      <td>{row.extraction_error_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {detail.continuity_checks?.length > 0 && (
              <div className="recording-table">
                <h3>Continuity and synchronization checks</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Topic / pair</th>
                      <th>Check</th>
                      <th>Status</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.continuity_checks.map((check, index) => (
                      <tr key={index}>
                        <td>
                          {check.topic ||
                            `${check.topic_left} / ${check.topic_right}`}
                        </td>
                        <td>{check.check_type}</td>
                        <td>{check.status}</td>
                        <td>{check.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p>
                  These checks include non-periodic and mixed TF traffic. A gap
                  ratio alone does not establish missing transforms or
                  localization failure.
                </p>
              </div>
            )}
            <p>
              Header time and recorded arrival time are distinct. Unstamped
              commands do not establish source-clock faults. Cross-recording
              differences do not establish causality.
            </p>
          </details>
        </>
      )}
    </div>
  );
}
