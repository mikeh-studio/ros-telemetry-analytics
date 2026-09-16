export function trajectoryGroups(signals) {
  const groups = new Map();
  for (const sample of signals) {
    const attrs = sample.payload?.attributes || {};
    if (!attrs.frame_id || !Number.isFinite(attrs.position_x) || !Number.isFinite(attrs.position_y)) continue;
    const key = JSON.stringify([sample.run_id, sample.robot_id, sample.topic, attrs.frame_id]);
    if (!groups.has(key)) groups.set(key, { key, topic: sample.topic, frame: attrs.frame_id, points: [] });
    groups.get(key).points.push({ x: attrs.position_x, y: attrs.position_y, time: sample.stream_timestamp_ms });
  }
  return [...groups.values()].map((group) => ({ ...group, points: group.points.sort((a, b) => a.time - b.time) }));
}

export default function IncidentTrajectory({ signals, onset, recovered }) {
  const groups = trajectoryGroups(signals);
  return <article className="incident-trajectories"><h3>Sampled position around the incident</h3>
    <p>Each topic and coordinate frame is plotted separately with equal X/Y scale. Dots are reported positions; gaps are not interpolated. Orange marks samples during the incident, blue marks before or after. No ground truth is available for these samples.</p>
    {!groups.length && <p>No finite position samples with a declared coordinate frame are available.</p>}
    <div className="incident-evidence-grid">{groups.map(({ key, topic, frame, points }) => {
      const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY, 0.1);
      const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
      const x = (value) => 140 + (value - centerX) * 200 / span;
      const y = (value) => 130 - (value - centerY) * 200 / span;
      return <figure key={key} className="incident-position-plot">
        <figcaption>{topic} · frame {frame} · {points.length} samples</figcaption>
        <svg viewBox="0 0 280 275" role="img" aria-label={`${topic} reported positions in ${frame}`}>
          <path d="M35 25 V235 H255" fill="none" stroke="currentColor" opacity="0.35" />
          {points.map((point, index) => <circle key={index} cx={x(point.x)} cy={y(point.y)} r="3"
            fill={point.time >= onset && (recovered == null || point.time <= recovered) ? "#f59e0b" : "#38bdf8"}>
            <title>{`${point.time} ms: x ${point.x} m, y ${point.y} m`}</title>
          </circle>)}
          <text x="140" y="260" textAnchor="middle" fill="currentColor" fontSize="10">X {minX.toFixed(2)} to {maxX.toFixed(2)} m</text>
          <text x="40" y="15" fill="currentColor" fontSize="10">Y {minY.toFixed(2)} to {maxY.toFixed(2)} m</text>
        </svg>
      </figure>;
    })}</div>
  </article>;
}
