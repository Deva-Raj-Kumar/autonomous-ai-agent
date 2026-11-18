// Small presentational components used across pages.

const STATUS_LABELS = {
  planning: "Planning",
  executing: "Running",
  running: "Running",
  waiting_approval: "Needs approval",
  completed: "Completed",
  partial: "Partly done",
  failed: "Failed",
  stopped: "Stopped",
  needs_clarification: "Needs clarification",
  error: "Error",
  pending: "Pending",
  skipped: "Skipped",
  success: "Success",
  approved: "Approved",
  rejected: "Rejected",
  denied: "Denied",
};

const STATUS_TONE = {
  completed: "good", success: "good", approved: "good",
  waiting_approval: "warn", needs_clarification: "warn", partial: "warn", pending: "muted",
  failed: "bad", error: "bad", rejected: "bad", denied: "bad", stopped: "bad",
  planning: "info", executing: "info", running: "info",
  skipped: "muted",
};

export function StatusBadge({ status }) {
  const tone = STATUS_TONE[status] || "muted";
  return <span className={`badge badge-${tone}`}>{STATUS_LABELS[status] || status || "unknown"}</span>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      {error.message || String(error)}
    </div>
  );
}

export function Spinner({ label = "Loading" }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" aria-hidden="true" />
      {label}…
    </div>
  );
}

export function EmptyState({ children }) {
  return <p className="empty">{children}</p>;
}
