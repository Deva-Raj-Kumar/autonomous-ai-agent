// Small display helpers.

export const FINISHED = new Set(["completed", "partial", "failed", "stopped", "needs_clarification", "error"]);

/** Is the run still changing (worth polling)? */
export function isActive(run) {
  return Boolean(run) && (run.running || !FINISHED.has(run.status)) && run.status !== "waiting_approval";
}

/** "2026-11-09T11:41:21Z" -> local time, e.g. "9 Nov, 5:11 pm". */
export function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function prettyJson(value) {
  return JSON.stringify(value ?? {}, null, 2);
}
