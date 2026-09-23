import { useEffect, useEffectEvent, useState } from "react";

export default function EvidencePreparation({ apiUrl, datasetId, onComplete }) {
  const [attempt, setAttempt] = useState(0);
  const [job, setJob] = useState({ status: "checking" });
  const notifyComplete = useEffectEvent(() => onComplete());

  useEffect(() => {
    const controller = new AbortController();
    let timer;
    let watching = attempt > 0;
    const url = `${apiUrl}/api/investigations/${encodeURIComponent(datasetId)}/preparation`;
    async function check(start = false) {
      try {
        const response = await fetch(url, {
          method: start ? "POST" : "GET",
          ...(start
            ? { headers: { "X-Requested-With": "ROS-Workbench" } }
            : {}),
          signal: controller.signal,
        });
        const body = await response.json();
        if (controller.signal.aborted) return;
        if (!response.ok)
          throw new Error(body.detail || "Could not check evidence rebuild");
        setJob(body);
        if (body.status === "running") {
          watching = true;
          timer = setTimeout(() => check(), 1000);
        } else if (body.status === "completed" && watching) {
          notifyComplete();
        }
      } catch (reason) {
        if (!controller.signal.aborted)
          setJob({ status: "failed", error: reason.message });
      }
    }
    check(attempt > 0);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [apiUrl, datasetId, attempt]);

  const busy = job.status === "running" || job.status === "checking";
  return (
    <div className="evidence-preparation">
      <button
        disabled={busy}
        onClick={() => {
          setJob({ status: "running", stage: "Starting rebuild" });
          setAttempt((n) => n + 1);
        }}
      >
        {busy
          ? job.status === "checking"
            ? "Checking evidence…"
            : "Rebuilding evidence…"
          : "Rebuild evidence"}
      </button>
      {job.status === "running" && (
        <p role="status">
          {job.stage}… This may take a few minutes. Results will load
          automatically.
        </p>
      )}
      {job.status === "completed" && (
        <p role="status">{job.warning || "Last rebuild completed."}</p>
      )}
      {job.status === "failed" && <p role="alert">{job.error}</p>}
    </div>
  );
}
