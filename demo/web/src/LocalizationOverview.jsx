import { useMemo } from "react";

export default function LocalizationOverview({ points }) {
  const geometry = useMemo(() => {
    const valid = points.filter((point) =>
      [
        point.ground_truth_x,
        point.ground_truth_y,
        point.estimated_x,
        point.estimated_y,
      ].every(Number.isFinite),
    );
    if (!valid.length) return null;
    const xs = valid.flatMap((point) => [
      point.ground_truth_x,
      point.estimated_x,
    ]);
    const ys = valid.flatMap((point) => [
      point.ground_truth_y,
      point.estimated_y,
    ]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = Math.max(maxX - minX, 0.1);
    const spanY = Math.max(maxY - minY, 0.1);
    const scale = Math.min(560 / spanX, 280 / spanY);
    const offsetX = (600 - spanX * scale) / 2;
    const offsetY = (320 - spanY * scale) / 2;
    const project = (x, y) => [
      offsetX + (x - minX) * scale,
      320 - offsetY - (y - minY) * scale,
    ];
    const path = (xKey, yKey) => {
      const segments = new Map();
      valid.forEach((point) => {
        const segment = point.segment_id ?? 0;
        if (!segments.has(segment)) segments.set(segment, []);
        segments.get(segment).push(point);
      });
      return [...segments.entries()].map(([segment, segmentPoints]) => ({
        segment,
        d: segmentPoints
          .map((point, index) => {
            const [x, y] = project(point[xKey], point[yKey]);
            return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
          })
          .join(" "),
      }));
    };
    return {
      estimated: path("estimated_x", "estimated_y"),
      groundTruth: path("ground_truth_x", "ground_truth_y"),
      failures: valid
        .filter((point) => point.label_failure)
        .map((point) => {
          const [x, y] = project(point.estimated_x, point.estimated_y);
          return {
            x,
            y,
            detected: point.detector_failure,
            timestamp: point.elapsed_ms,
          };
        }),
    };
  }, [points]);

  if (!geometry)
    return (
      <div className="trajectory-empty">No trajectory samples available.</div>
    );
  return (
    <svg
      className="trajectory-map"
      viewBox="0 0 600 320"
      role="img"
      aria-label="Ground-truth and AMCL estimated trajectories"
    >
      {geometry.groundTruth.map((path) => (
        <path
          className="trajectory-ground-truth"
          d={path.d}
          key={`ground-truth-${path.segment}`}
        />
      ))}
      {geometry.estimated.map((path) => (
        <path
          className="trajectory-estimated"
          d={path.d}
          key={`estimated-${path.segment}`}
        />
      ))}
      {geometry.failures.map((point, index) => (
        <circle
          className={point.detected ? "failure-detected" : "failure-missed"}
          cx={point.x}
          cy={point.y}
          r="2.4"
          key={`${point.timestamp}-${index}`}
        />
      ))}
    </svg>
  );
}
