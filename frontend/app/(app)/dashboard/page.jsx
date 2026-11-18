"use client";
// Vision AI - Dedicated Full Dashboard Page
// 100% Dark Theme with Emerald Green Accents (Zero White)

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { EmptyState, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatTime, isActive } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function HeroMetrics({ onSelectPrompt }) {
  return (
    <div className="top-metrics-row">
      {/* 1. Hero Dark Green Card */}
      <div className="hero-card">
        <div className="hero-left">
          <span className="hero-label">Tasks completed today</span>
          <div className="hero-number">1,284</div>
          <div className="hero-badge-row">
            <span className="hero-badge">↗ +18% vs yesterday</span>
          </div>
          <div>
            <button
              type="button"
              className="hero-btn"
              onClick={() =>
                onSelectPrompt(
                  "Find 10 AI Engineer or Python Developer fresher job openings in Bengaluru and Hyderabad. Search startup companies, check eligibility, collect application links, analyze required skills, and generate an Excel report."
                )
              }
            >
              <span>▶</span> Run AI Jobs Goal
            </button>
          </div>
        </div>

        {/* Circular Progress Radial Gauge */}
        <div className="hero-gauge-wrap">
          <svg className="gauge-svg" width="105" height="105" viewBox="0 0 100 100">
            <circle
              className="gauge-bg"
              cx="50"
              cy="50"
              r="40"
              strokeWidth="9"
              fill="transparent"
            />
            <circle
              className="gauge-progress"
              cx="50"
              cy="50"
              r="40"
              strokeWidth="9"
              fill="transparent"
              strokeDasharray="251.2"
              strokeDashoffset="35.1"
            />
          </svg>
          <div className="gauge-text-center">
            <div className="gauge-percent">86%</div>
            <div className="gauge-sub">daily goal</div>
          </div>
        </div>
      </div>

      {/* 2. Success Rate Card */}
      <div className="card" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div className="metric-header">
          <span className="metric-title">Success Rate</span>
          <span className="badge badge-good">Optimal</span>
        </div>
        <div style={{ textAlign: "center", margin: "0.25rem 0" }}>
          <div className="metric-value-huge" style={{ color: "var(--accent)" }}>97.4%</div>
          <div className="small muted">of automated runs succeeded</div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-around", borderTop: "1px solid var(--border)", paddingTop: "0.75rem" }}>
          <span className="small" style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--good)" }} />
            <strong>1,247</strong> ok
          </span>
          <span className="small" style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--bad)" }} />
            <strong>33</strong> failed
          </span>
        </div>
      </div>

      {/* 3. Active Agent Core Card */}
      <div className="card">
        <div className="metric-header">
          <span className="metric-title">Active Capabilities</span>
          <span className="small muted">4 modules</span>
        </div>
        <div className="agent-mini-list">
          <div className="agent-mini-item">
            <div className="agent-name-cell">
              <span className="agent-avatar-sm">🌐</span>
              <span>Web Search</span>
            </div>
            <span className="badge badge-good">Ready</span>
          </div>
          <div className="agent-mini-item">
            <div className="agent-name-cell">
              <span className="agent-avatar-sm">🐍</span>
              <span>Python Sandbox</span>
            </div>
            <span className="badge badge-good">pandas/openpyxl</span>
          </div>
          <div className="agent-mini-item">
            <div className="agent-name-cell">
              <span className="agent-avatar-sm">📚</span>
              <span>Chroma RAG</span>
            </div>
            <span className="badge badge-info">Vectorized</span>
          </div>
          <div className="agent-mini-item">
            <div className="agent-name-cell">
              <span className="agent-avatar-sm">⚡</span>
              <span>LangGraph Core</span>
            </div>
            <span className="badge badge-good">Self-eval</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function NewRunForm({ goal, setGoal }) {
  const router = useRouter();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const samplePrompts = [
    {
      label: "✉️ Send HR Email",
      text: "Send an email to HR at careers@techcorp.in asking about the AI Engineer vacancy.",
    },
    {
      label: "💼 Match & Apply 20 Jobs",
      text: "Find 20 Python Developer and AI Engineer fresher jobs in Bengaluru and Hyderabad. Match them with my resume, prepare applications and help me apply.",
    },
    {
      label: "🎯 10 AI Startup Jobs",
      text: "Find 10 AI Engineer or Python Developer fresher job openings in Bengaluru and Hyderabad. Search startup companies, check eligibility, collect application links, analyze required skills, and generate an Excel report.",
    },
    {
      label: "💰 Salary Benchmark",
      text: "Research AI engineer fresher salaries in Bengaluru startups and calculate averages",
    },
  ];

  const submit = async (event) => {
    event.preventDefault();
    if (!goal.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const started = await apiFetch("/agent/runs", { method: "POST", json: { goal: goal.trim() } });
      router.push(`/runs/${started.run_id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <form className="card new-goal-card new-goal-card-pro" onSubmit={submit}>
      <div className="row new-goal-title-row" style={{ marginBottom: "0.65rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <div className="new-goal-icon-badge">🎯</div>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700 }}>Start a New Goal</h2>
            <span className="small muted">Natural language autonomous workflow execution</span>
          </div>
        </div>
        <span className="agent-studio-pill">AI Agent Studio</span>
      </div>
      <ErrorBox error={error} />
      <div className="goal-input-box-wrapper">
        <textarea
          aria-label="Goal"
          placeholder="Describe your goal in natural language (e.g., Research AI startups and benchmark entry-level salaries in Bengaluru)..."
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && goal.trim().length >= 3 && !busy) {
              e.preventDefault();
              submit(e);
            }
          }}
          rows={3}
          minLength={3}
          maxLength={1000}
          required
          className="goal-textarea-pro"
        />
        <div className="prompt-chips-row">
          <span className="small muted" style={{ alignSelf: "center", marginRight: "0.25rem" }}>
            Suggested:
          </span>
          {samplePrompts.map((p, idx) => (
            <button
              key={idx}
              type="button"
              className="chip-btn chip-btn-pro"
              onClick={() => setGoal(p.text)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.75rem" }}>
        <button type="submit" className="primary deploy-goal-btn-pro" disabled={busy || goal.trim().length < 3}>
          {busy ? "Deploying agent…" : "🚀 Run Agent Workflow"}
        </button>
      </div>
    </form>
  );
}

function ActivityGrid() {
  const cells = [
    1, 2, 0, 3, 2, 4, 1, 0, 2, 3, 4, 2, 1, 3,
    2, 3, 4, 1, 2, 3, 0, 2, 4, 3, 1, 4, 2, 3,
    0, 1, 3, 4, 2, 3, 1, 4, 3, 2, 4, 1, 3, 4,
    3, 4, 2, 1, 4, 3, 2, 3, 4, 2, 3, 4, 2, 4
  ];

  return (
    <div className="card heat-grid-container">
      <div className="row">
        <h2>Runs Activity</h2>
        <span className="small muted">Last 6 weeks</span>
      </div>
      <div className="heat-grid-weeks" style={{ margin: "0.5rem 0" }}>
        {cells.map((lvl, i) => (
          <div key={i} className={`heat-cell heat-${lvl}`} title={`Activity level: ${lvl}`} />
        ))}
      </div>
      <div className="row" style={{ borderTop: "1px solid var(--border)", paddingTop: "0.6rem", fontSize: "0.78rem" }}>
        <span className="muted">Less</span>
        <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
          <span className="heat-cell" style={{ width: "10px", height: "10px" }} />
          <span className="heat-cell heat-1" style={{ width: "10px", height: "10px" }} />
          <span className="heat-cell heat-2" style={{ width: "10px", height: "10px" }} />
          <span className="heat-cell heat-3" style={{ width: "10px", height: "10px" }} />
          <span className="heat-cell heat-4" style={{ width: "10px", height: "10px" }} />
        </div>
        <span className="muted">More</span>
      </div>
    </div>
  );
}

function PendingApprovals() {
  const { data, error } = useApi("/approvals?status=pending&limit=20", { refreshMs: 10000 });
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) return null;
  return (
    <section className="card highlight">
      <div className="row">
        <h2 style={{ color: "var(--warn)" }}>⚠️ Action Required: Waiting for your approval ({data.length})</h2>
      </div>
      <p className="small" style={{ margin: "0.3rem 0 0.75rem" }}>
        The agent paused on a sensitive task and generated exact parameters for your review.
      </p>
      <ul className="plain">
        {data.map((a) => (
          <li key={a.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Link href={`/runs/${a.run_id}`}>
              <code>{a.tool}</code> <strong>{a.title}</strong>
            </Link>
            <span className="small muted">{formatTime(a.requested_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecentRuns() {
  const [polling, setPolling] = useState(false);
  const { data, error, loading, reload } = useApi("/agent/runs?limit=15", { refreshMs: polling ? 3000 : 0 });
  useEffect(() => setPolling(Boolean(data?.some(isActive))), [data]);

  return (
    <section className="card">
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        <h2>Recent Runs</h2>
        <button type="button" className="link-button" onClick={reload}>
          🔄 Refresh
        </button>
      </div>
      <ErrorBox error={error} />
      {loading && <Spinner />}
      {data && !data.length && <EmptyState>No runs yet. Deploy your first agent goal above.</EmptyState>}
      {data?.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Goal</th>
                <th>Status</th>
                <th className="num">Steps</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {data.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <Link href={`/runs/${run.run_id}`} style={{ fontWeight: 600 }}>
                      {run.goal}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge status={run.running ? "running" : run.status} />
                  </td>
                  <td className="num">
                    <strong>{run.steps_used}</strong>
                  </td>
                  <td className="small muted">{formatTime(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function DashboardPage() {
  const [goal, setGoal] = useState("");

  return (
    <div className="page">
      <div className="dashboard-grid">
        <div className="row" style={{ marginBottom: "0.5rem" }}>
          <div>
            <h1 style={{ color: "#ffffff", fontSize: "1.75rem" }}>Vision AI Dashboard</h1>
            <p className="small muted" style={{ margin: "0.25rem 0 0" }}>
              Live Vision AI metrics, execution activity, and agent status
            </p>
          </div>
        </div>
        <HeroMetrics onSelectPrompt={(text) => setGoal(text)} />
        <PendingApprovals />
        <div className="middle-grid-row">
          <NewRunForm goal={goal} setGoal={setGoal} />
          <ActivityGrid />
        </div>
        <RecentRuns />
      </div>
    </div>
  );
}
