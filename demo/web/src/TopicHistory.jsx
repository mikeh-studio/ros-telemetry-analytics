import { useEffect, useMemo, useRef, useState } from "react";
import TopicInfo from "./TopicInfo";

const time = (ms) => `${String(Math.floor(Math.max(0, ms) / 60000)).padStart(2, "0")}:${String(Math.floor(Math.max(0, ms) / 1000) % 60).padStart(2, "0")}`;
const rate = (value) => Number.isFinite(value) ? `${Number(value.toFixed(2))} Hz` : "—";
const label = (topic) => ({ "/camera/image_raw": "Camera", "/imu/data": "IMU", "/odom": "Odometry", "/diagnostics": "Diagnostics" })[topic] || topic.split("/").filter(Boolean).at(-1);

export function topicSamples(history, topic, startMs, robotId) {
  if (!Number.isFinite(startMs)) return [];
  const windows = new Map();
  for (const item of history) {
    if (item.topic !== topic || (robotId && item.robot_id !== robotId) || !Number.isFinite(item.window_end_ms)) continue;
    const key = `${item.robot_id}:${item.window_start_ms}:${item.window_end_ms}`;
    if (!windows.has(key) || (item.revision || 0) > (windows.get(key).revision || 0)) windows.set(key, item);
  }
  return [...windows.values()].map((item) => ({ item, t: item.window_end_ms - startMs, value: item.payload?.mean_rate_hz }))
    .filter((sample) => sample.t >= 0).sort((a, b) => a.t - b.t);
}

export function historyPath(samples, x, y) {
  let previous = null;
  return samples.map((sample) => {
    if (!Number.isFinite(sample.value) || sample.item.payload?.window_status === "partial") { previous = null; return ""; }
    const connected = previous && sample.t - previous.t <= 1500 && sample.t > previous.t;
    previous = sample;
    return `${connected ? "L" : "M"}${x(sample.t)},${y(sample.value)}`;
  }).join(" ");
}

export default function TopicHistory({ topics = [], history = [], startMs, durationMs, incidents = [], unavailable, live, completed }) {
  const plotRoot = useRef(null);
  const [plotWidth, setPlotWidth] = useState(400);
  useEffect(() => {
    const plot = plotRoot.current?.querySelector(".lane-plot");
    if (!plot || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setPlotWidth(Math.max(120, entry.contentRect.width)));
    observer.observe(plot);
    return () => observer.disconnect();
  }, [topics.length]);
  const [cursor, setCursor] = useState(null);
  const [selected, setSelected] = useState(null);
  const duration = Math.max(1, durationMs || 90000);
  const rows = useMemo(() => topics.map((metric) => ({ metric, samples: topicSamples(history, metric.topic, startMs, metric.robot_id).filter((sample) => sample.t <= duration) })), [topics, history, startMs, duration]);
  const selectedRow = rows.find(({ metric }) => metric.topic === selected) || rows[0];
  const selectedSample = selectedRow?.samples.find((sample) => cursor != null && Math.abs(sample.t - cursor) < 500);
  const selectedIncidents = incidents.filter((incident) => incident.topic === selectedRow?.metric.topic);
  return <section ref={plotRoot} className="topic-workspace" aria-label="Topic health">
    <div className="section-title compact"><h2>Topic health</h2><span>{live ? "Live session" : "Recorded windows"} · 00:00–{time(duration)}</span></div>
    <details className="history-inspector"><summary>Inspect time</summary>
    <div className="history-controls">
      <label>Inspect mission time <span>{cursor == null ? "Latest values" : time(cursor)}</span>
        <input type="range" min="0" max={duration} step="1000" value={cursor ?? duration} onChange={(event) => setCursor(Number(event.target.value))} />
      </label>
      <button className="add-data-button" onClick={() => setCursor(null)} disabled={cursor == null}>Latest</button>
    </div>
    </details>
    <p className="history-caption">Message rate (Hz) · 10 s windows, 1 s slide · dashed line: expected · hollow dots: partial windows</p>
    {!rows.length && <p className="empty-state">Run a mission to inspect topic history.</p>}
    <div className="topic-table-wrap"><table className="topic-history-table">
      <thead><tr><th scope="col">Topic</th><th scope="col">{completed ? "End state" : "Latest health"}</th><th scope="col">Rate history · Hz</th><th scope="col">Observed</th><th scope="col">Expected</th><th scope="col">Window max gap</th></tr></thead>
      <tbody>{rows.map(({ metric, samples }) => {
      const payload = metric.payload || {};
      const expected = payload.rate_monitoring_enabled === false ? null : payload.expected_rate_hz;
      const maximum = Math.max(1, expected || 0, ...samples.map((sample) => Number.isFinite(sample.value) ? sample.value : 0)) * 1.15;
      const x = (value) => 34 + value / duration * (plotWidth - 44);
      const y = (value) => 34 - value / maximum * 22;
      const latestComplete = samples.filter((sample) => Number.isFinite(sample.value) && sample.item.payload?.window_status !== "partial").at(-1)?.item;
      const atCursor = cursor == null ? latestComplete || metric : samples.find((sample) => Math.abs(sample.t - cursor) < 500)?.item;
      return <tr className={`topic-lane${selectedRow?.metric.topic === metric.topic ? " selected" : ""}`} key={metric.topic}>
        <td className="lane-identity" data-label="Topic"><div className="topic-name"><button className="topic-select" onClick={() => setSelected(metric.topic)} aria-pressed={selectedRow?.metric.topic === metric.topic}>{label(metric.topic)}</button><TopicInfo topic={metric.topic} label={label(metric.topic)} /></div>
          <code>{metric.topic}</code></td>
        <td data-label="Health"><span className={`status-pill ${unavailable ? "warn" : ["healthy", "ok"].includes(payload.health_status || payload.status) ? "ok" : "warn"}`}>{unavailable ? "unavailable" : payload.health_status || payload.status || "waiting"}</span></td>
        <td className="lane-plot" data-label="Rate history">
          <svg onPointerDown={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setCursor(Math.min(duration, Math.round(Math.max(0, (event.clientX - rect.left - 34) / (plotWidth - 44) * duration) / 1000) * 1000)); }} viewBox={`0 0 ${plotWidth} 54}`} role="img" aria-label={`${metric.topic} message rate history, ${samples.length} recorded windows`}>
            <path d={`M34 10V34H${plotWidth - 10}`} className="plot-axis" />
            {incidents.filter((incident) => incident.topic === metric.topic).map((incident) => {
              const start = Math.max(0, incident.effective_start_stream_ms - startMs);
              const end = Math.min(duration, (incident.recovered_stream_ms ?? startMs + duration) - startMs);
              return Number.isFinite(start) && end >= start ? <rect key={incident.anomaly_id} x={x(start)} y="10" width={Math.max(1, x(end) - x(start))} height="24" className="plot-incident"><title>{incident.condition_type} · {time(start)}–{time(end)}</title></rect> : null;
            })}
            {Number.isFinite(expected) && <path d={`M34 ${y(expected)}H${plotWidth - 10}`} className="plot-expected" />}
            <path d={historyPath(samples, x, y)} className="plot-series" />
            {samples.filter((sample) => Number.isFinite(sample.value)).map((sample) => <circle key={`${sample.item.robot_id}:${sample.t}`} cx={x(sample.t)} cy={y(sample.value)} r={sample.item.payload?.window_status === "partial" ? 2.7 : 1.4} className={sample.item.payload?.window_status === "partial" ? "plot-partial" : "plot-point"}><title>{time(sample.t)}: {rate(sample.value)} · {sample.item.payload?.window_status || "window"}</title></circle>)}
            {cursor != null && <path d={`M${x(cursor)} 8V38`} className="plot-cursor" />}
            <text x="28" y="16" textAnchor="end">{Number(maximum.toFixed(1))}</text><text x="28" y="37" textAnchor="end">0</text>
            {[0, .5, 1].map((fraction) => <text key={fraction} x={x(duration * fraction)} y="50" textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}>{time(duration * fraction)}</text>)}
          </svg>
          {!samples.length && <span className="history-empty">History not available yet</span>}
        </td>
        <td className="lane-value" data-label="Observed"><strong>{rate(atCursor?.payload?.mean_rate_hz)}</strong><span>{atCursor?.payload?.window_status === "partial" ? "Partial window" : atCursor ? cursor == null ? "Latest full window" : `At ${time(cursor)}` : "No sample"}</span></td>
        <td data-label="Expected">{payload.rate_monitoring_enabled === false ? "Event-driven" : rate(expected)}</td>
        <td data-label="Window max gap">{Number.isFinite(atCursor?.payload?.max_inter_message_gap_s) ? `${Number(atCursor.payload.max_inter_message_gap_s.toFixed(3))} s` : "—"}</td>
      </tr>;
    })}</tbody></table></div>
    {selectedRow && <details className="selected-topic-detail" open={cursor != null || selected != null ? true : undefined}><summary>Inspect topic · {label(selectedRow.metric.topic)}</summary><div aria-live="polite">
      <p>{cursor == null ? `Latest raw window: ${rate(selectedRow.metric.payload?.mean_rate_hz)}${selectedRow.metric.payload?.window_status === "partial" ? " (partial)" : ""}.` : selectedSample ? `Window ending ${time(selectedSample.t)}: ${rate(selectedSample.value)} (${selectedSample.item.payload?.window_status || "window"}).` : `No recorded window ends at ${time(cursor)}.`} {selectedIncidents.length ? `${selectedIncidents.length} incident(s) recorded for this topic. See incident explanation below.` : "No incidents recorded for this topic."}</p>
      <p>Missing windows are left disconnected. The inspection cursor does not seek or restart playback.</p>
    </div></details>}
  </section>;
}
