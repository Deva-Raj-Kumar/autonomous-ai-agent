"use client";
// One run, live: plan progress, approvals, the report, evaluation and tool history.
// While the run is working, the page re-fetches it every 2 seconds (polling).

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import ApprovalPanel from "@/components/ApprovalPanel";
import Markdown from "@/components/Markdown";
import PlanSteps from "@/components/PlanSteps";
import RunHistory from "@/components/RunHistory";
import { ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { apiFetch, downloadFile } from "@/lib/api";
import { FINISHED, formatTime, isActive } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function Evaluation({ run }) {
  const evaluation = run.evaluation;
  if (!evaluation) return null;
  return (
    <section className="card">
      <h2>Self-evaluation</h2>
      <p>
        <strong>{evaluation.verdict.replaceAll("_", " ")}</strong>
        {evaluation.quality_score != null && <> · quality {evaluation.quality_score}/10</>}
        {run.replans > 0 && <> · re-planned {run.replans}×</>}
      </p>
      {evaluation.reason && <p className="muted">{evaluation.reason}</p>}
      {evaluation.open_issues?.length > 0 && (
        <ul>
          {evaluation.open_issues.map((issue) => <li key={issue}>{issue}</li>)}
        </ul>
      )}
    </section>
  );
}

export default function RunPage() {
  const { runId } = useParams();
  const [actionError, setActionError] = useState(null);
  const [polling, setPolling] = useState(true);
  const { data: run, error, reload } = useApi(`/agent/runs/${runId}`, { refreshMs: polling ? 2000 : 0 });
  const finished = run && FINISHED.has(run.status) && !run.running;
  const { data: history } = useApi(finished ? `/agent/runs/${runId}/history` : null);

  // Keep polling while the run works; stop when it finishes or waits for a human.
  useEffect(() => {
    if (run) setPolling(isActive(run));
  }, [run]);

  const act = async (path, json) => {
    setActionError(null);
    try {
      await apiFetch(`/agent/runs/${runId}/${path}`, { method: "POST", json });
      setPolling(true); // the run resumes in the background
      reload();
    } catch (err) {
      setActionError(err);
    }
  };

  if (error?.status === 404) {
    return <div className="card"><h1>Run not found</h1><Link href="/">Back to the dashboard</Link></div>;
  }
  if (error) return <ErrorBox error={error} />;
  if (!run) return <Spinner label="Loading run" />;

  return (
    <div className="stack">
      <section className="card run-hero-card-pro">
        <div className="row" style={{ alignItems: "flex-start", gap: "1rem" }}>
          <div style={{ flex: 1 }}>
            <div className="run-kicker-label">
              <span className="run-kicker-icon">🤖</span> Autonomous Agent Workflow
            </div>
            <h1 className="goal run-hero-goal">{run.goal}</h1>
          </div>
          <StatusBadge status={run.running ? "running" : run.status} />
        </div>
        <div className="run-meta-chips">
          <span className="run-meta-chip">⏱ Started {formatTime(run.created_at)}</span>
          <span className="run-meta-chip">⚡ {run.steps_used} step{run.steps_used === 1 ? "" : "s"} used</span>
          {run.running && (
            <span className="run-meta-chip running-chip">
              <span className="pulsing-green-dot" /> Autonomous execution in progress…
            </span>
          )}
          {run.stop_reason && <span className="run-meta-chip">Stopped: {run.stop_reason}</span>}
        </div>
        {run.plan?.strategy && (
          <div className="run-strategy-banner">
            <span className="strategy-tag">Strategy:</span> {run.plan.strategy}
          </div>
        )}
        {run.error && (
          <div className="run-error-box-pro">
            <span className="run-error-icon">⚠️</span>
            <div>
              <strong>Run Execution Halted:</strong>
              <div>{run.error}</div>
            </div>
          </div>
        )}
        {run.resumable && (
          <div style={{ marginTop: "0.75rem" }}>
            <button type="button" className="primary deploy-goal-btn-pro" onClick={() => act("continue")}>
              ▶ Continue Run
            </button>
          </div>
        )}
        <ErrorBox error={actionError} />
      </section>

      {run.pending_approvals?.length > 0 && !run.running && (
        <ApprovalPanel
          key={run.pending_approvals.map((t) => t.id).join(",")}
          tasks={run.pending_approvals}
          onDecide={(approved) => act("approval", { approved })}
        />
      )}

      {run.plan && (
        <section className="card plan-card-pro">
          <div className="row" style={{ marginBottom: "0.75rem" }}>
            <h2>Execution Plan</h2>
            <span className="small muted">{run.plan.tasks?.length || 0} tasks orchestrated</span>
          </div>
          <PlanSteps plan={run.plan} />
        </section>
      )}

      {run.status === "needs_clarification" && run.planning?.clarifying_questions?.length > 0 && (
        <section className="card clarification-card-pro">
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem" }}>
            <span style={{ fontSize: "1.4rem" }}>❓</span>
            <div>
              <h2 style={{ margin: 0 }}>The agent needs more detail</h2>
              <span className="small muted">Clarifying questions from autonomous goal analysis</span>
            </div>
          </div>
          <ul style={{ paddingLeft: "1.4rem", margin: "0.75rem 0", lineHeight: 1.6 }}>
            {run.planning.clarifying_questions.map((q) => (
              <li key={q} style={{ color: "#e2e8f0" }}>{q}</li>
            ))}
          </ul>
          <div style={{ marginTop: "0.75rem" }}>
            <Link href="/" className="secondary-btn" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
              ← Start a new, more specific goal
            </Link>
          </div>
        </section>
      )}

      {run.final_output && (() => {
        const goalLower = (run.goal || "").toLowerCase();
        const outputLower = (run.final_output || "").toLowerCase();
        const isEmailTask =
          goalLower.includes("email") ||
          goalLower.includes("meet") ||
          goalLower.includes("invitation") ||
          outputLower.includes("dispatched via gmail") ||
          outputLower.includes("saved to the outbox") ||
          outputLower.includes("outbox mode");
        const hasSpreadsheet =
          !isEmailTask &&
          (goalLower.includes("excel") ||
            goalLower.includes("csv") ||
            goalLower.includes("spreadsheet") ||
            (goalLower.includes("job") && !goalLower.includes("email")) ||
            outputLower.includes(".xlsx") ||
            outputLower.includes(".csv"));

        return (
          <section className="card">
            <div className="row" style={{ marginBottom: "0.85rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.75rem" }}>
              <h2>Report</h2>
              {hasSpreadsheet && (
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => downloadFile("ai_python_fresher_jobs_blr_hyd.xlsx")}
                  >
                    📥 Download Excel (.xlsx)
                  </button>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => downloadFile("ai_python_fresher_jobs_blr_hyd.csv")}
                  >
                    📥 Download CSV (.csv)
                  </button>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => downloadFile("job_openings.xlsx")}
                  >
                    📥 Run Output (.xlsx)
                  </button>
                </div>
              )}
            </div>
            <Markdown>{run.final_output}</Markdown>
          </section>
        );
      })()}

      <Evaluation run={run} />

      {history?.tool_logs?.length > 0 && (
        <section className="card">
          <h2>Tool calls ({history.tool_logs.length})</h2>
          <RunHistory history={history} />
        </section>
      )}
    </div>
  );
}
