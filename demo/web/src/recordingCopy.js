export function explanationStatusLabel(status) {
  return (
    {
      supported: "Evidence available",
      insufficient_evidence: "Limited evidence",
      unsupported: "Explanation unavailable",
    }[status] || "Explanation unavailable"
  );
}
