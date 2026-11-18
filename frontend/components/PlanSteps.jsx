// The plan as a live checklist: one row per task with its status.

import { StatusBadge } from "@/components/ui";

export default function PlanSteps({ plan }) {
  if (!plan?.tasks?.length) return null;
  return (
    <ol className="steps steps-pro">
      {plan.tasks.map((task) => (
        <li key={task.id} className={`step step-${task.status}`}>
          <div className="step-head">
            <span className="step-id">{task.id}</span>
            <span className="step-title">{task.title}</span>
            <span className="step-tool-badge">
              <code className="step-tool">{task.tool}</code>
            </span>
            <StatusBadge status={task.status} />
            {task.attempts > 1 && <span className="small muted step-attempts">{task.attempts} attempts</span>}
          </div>
          {task.depends_on?.length > 0 && <div className="small muted step-dep">after {task.depends_on.join(", ")}</div>}
          {task.error && (
            <div className="step-error-box">
              <div className="step-error-header">
                <span className="step-error-tag">Error:</span>
                <span className="small error-text">{task.error}</span>
              </div>
              {task.error.includes("EMAIL_ALLOWED_RECIPIENTS") && (
                <div className="step-error-help">
                  💡 <em>Recipient is not allowed. To send emails to any recipient, ensure <code>EMAIL_ALLOWED_RECIPIENTS=[&quot;*&quot;]</code> is configured in <code>.env</code>.</em>
                </div>
              )}
            </div>
          )}
          {task.feedback && <div className="small muted">Reviewer feedback: {task.feedback}</div>}
        </li>
      ))}
    </ol>
  );
}
