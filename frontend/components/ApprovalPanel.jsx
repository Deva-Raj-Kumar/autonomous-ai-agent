"use client";
// APPROVE WHAT YOU SEE (Phase 10, now in the browser).
// Each waiting task shows the EXACT arguments that will run (email recipients and body,
// Python code). Nothing is pre-selected: approving must be a deliberate click, and any
// task left unticked is REJECTED when the decision is sent.

import { useState } from "react";

import { prettyJson } from "@/lib/format";

export default function ApprovalPanel({ tasks, onDecide }) {
  const [selected, setSelected] = useState(() => new Set());
  const [sending, setSending] = useState(false);
  const [showRawArgs, setShowRawArgs] = useState(false);

  const toggle = (id) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async (event) => {
    event.preventDefault();
    setSending(true);
    try {
      await onDecide([...selected]);
    } finally {
      setSending(false);
    }
  };

  const rejected = tasks.length - selected.size;
  const label =
    selected.size === 0 ? "Reject all" : `Approve ${selected.size}${rejected ? `, reject ${rejected}` : ""}`;

  return (
    <form className="card approval approval-panel-pro" onSubmit={submit} aria-label="Approval required">
      <div className="approval-header-pro">
        <div className="approval-badge-pro">
          <span className="approval-shield-icon">🛡️</span>
          <span>HUMAN APPROVAL REQUIRED</span>
        </div>
        <h2 className="approval-title-pro">Review Action Before Execution</h2>
        <p className="approval-subtitle-pro">
          The autonomous agent has prepared the exact parameters below. For safety and control, confirm or reject before any external action is taken.
        </p>
      </div>

      {tasks.map((task) => {
        const isEmail = task.tool === "send_email" && task.arguments;
        const isPython = task.tool === "python_exec" && task.arguments?.code;
        const isSelected = selected.has(task.id);

        return (
          <fieldset key={task.id} className={`approval-task approval-task-pro ${isSelected ? "task-selected" : ""}`}>
            <label className="approval-choice approval-choice-pro">
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggle(task.id)}
                className="approval-checkbox-pro"
              />
              <span className="approval-task-meta">
                <span className="approval-task-title">{task.title}</span>
                <code className="approval-tool-tag">{task.tool}</code>
                {isEmail && <span className="approval-email-badge">✉️ Email Automation</span>}
              </span>
            </label>

            {task.description && <p className="muted approval-desc-pro">{task.description}</p>}

            {/* Specialized Rich Preview for Email Automation */}
            {isEmail && (
              <div className="email-preview-card">
                <div className="email-preview-banner">
                  <span className="email-preview-icon">✉️</span>
                  <strong>AI Generated Email Draft</strong>
                  <span className="email-preview-status">Ready to Send</span>
                </div>

                <div className="email-preview-fields">
                  <div className="email-preview-row">
                    <span className="email-preview-label">To:</span>
                    <div className="email-recipients-wrap">
                      {(Array.isArray(task.arguments.to) ? task.arguments.to : [task.arguments.to]).map((addr) => (
                        <span key={addr} className="email-recipient-chip">
                          👤 {addr}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="email-preview-row">
                    <span className="email-preview-label">Subject:</span>
                    <span className="email-preview-subject">{task.arguments.subject}</span>
                  </div>

                  <div className="email-preview-body-wrap">
                    <span className="email-preview-label">Message Body:</span>
                    <div className="email-preview-body-content">
                      {task.arguments.body}
                    </div>
                  </div>
                </div>

                <div className="email-preview-tip">
                  🔒 <em>Human confirmation required: This email will only be sent after you check the box and approve.</em>
                </div>
              </div>
            )}

            {/* Specialized Rich Preview for Python Sandbox */}
            {isPython && (
              <div className="code-preview-card">
                <div className="code-preview-banner">
                  <span className="code-preview-icon">🐍</span>
                  <strong>Python Code to Execute (Sandboxed)</strong>
                </div>
                <pre className="code-preview-block">
                  <code>{task.arguments.code}</code>
                </pre>
              </div>
            )}

            {/* Technical JSON Arguments block - always in DOM for test suite & debug inspection */}
            <div className="arguments-inspection-wrap">
              <button
                type="button"
                className="toggle-args-btn"
                onClick={() => setShowRawArgs(!showRawArgs)}
              >
                {showRawArgs ? "▼ Hide Technical Arguments JSON" : "▶ View Raw JSON Arguments"}
              </button>
              <pre
                className="arguments"
                data-testid={`arguments-${task.id}`}
                style={{ display: showRawArgs ? "block" : (isEmail || isPython) ? "none" : "block" }}
              >
                {task.arguments ? prettyJson(task.arguments) : "(arguments not prepared yet)"}
              </pre>
            </div>
          </fieldset>
        );
      })}

      <div className="approval-actions-bar">
        <button
          type="submit"
          className={`approval-submit-btn ${selected.size ? "primary-approved" : "danger-rejected"}`}
          disabled={sending}
        >
          {sending ? "Processing Decision…" : label}
        </button>
        {selected.size > 0 && (
          <span className="approval-confirm-hint">
            ✓ Ready to execute {selected.size} approved action{selected.size === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </form>
  );
}
