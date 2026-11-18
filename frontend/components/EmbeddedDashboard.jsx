"use client";
// Embedded Live Dashboard Tool Component
// Renders inside the conversation stream as an interactive tool card

import RobotMascot from "./RobotMascot";

export default function EmbeddedDashboard({ onInvokeTool, stats = null }) {
  const totalChats = stats?.chats ?? 248;
  const totalDocs = stats?.docs ?? 2;
  const totalMemories = stats?.memories ?? 15;
  const uptime = "99.9%";

  return (
    <div className="embedded-dash-container">
      {/* Mini Left Sidebar */}
      <div className="embedded-dash-sidebar">
        <div className="embedded-dash-brand">
          <RobotMascot size={28} />
          <div className="embedded-dash-brand-title">
            <span style={{ color: "#ffffff" }}>Vision </span>
            <span style={{ color: "#10b981", fontWeight: 700 }}>AI</span>
          </div>
        </div>

        <nav className="embedded-dash-nav">
          <button
            type="button"
            className="embedded-nav-item active"
            onClick={() => onInvokeTool?.("dashboard")}
          >
            <span className="dash-icon">📊</span>
            <span>Dashboard</span>
          </button>
          <button
            type="button"
            className="embedded-nav-item"
            onClick={() => onInvokeTool?.("memories")}
          >
            <span className="dash-icon">🧠</span>
            <span>Memory Bank</span>
          </button>
          <button
            type="button"
            className="embedded-nav-item"
            onClick={() => onInvokeTool?.("knowledge")}
          >
            <span className="dash-icon">📄</span>
            <span>Knowledge RAG</span>
          </button>
        </nav>

        <div className="embedded-quick-access">
          <div className="quick-access-title">Quick Access ❯</div>
          <button
            type="button"
            className="quick-link"
            onClick={() => onInvokeTool?.("chat")}
          >
            <span className="bullet-check">⚡</span>
            <span>Chat with AI Agent</span>
          </button>
          <button
            type="button"
            className="quick-link"
            onClick={() => onInvokeTool?.("memories")}
          >
            <span className="bullet-check">🧠</span>
            <span>Remember Info</span>
          </button>
          <button
            type="button"
            className="quick-link"
            onClick={() => onInvokeTool?.("knowledge")}
          >
            <span className="bullet-check">🔍</span>
            <span>Search Documents</span>
          </button>
        </div>
      </div>

      {/* Main Area of Embedded Dashboard */}
      <div className="embedded-dash-main">
        {/* Top 4 Stat Metric Cards */}
        <div className="embedded-dash-stats-grid">
          {/* 1. Total Chats */}
          <div
            className="embedded-stat-card stat-chats"
            onClick={() => onInvokeTool?.("chat")}
            role="button"
            tabIndex={0}
          >
            <div className="stat-icon-wrap mint">💬</div>
            <div className="stat-meta">
              <span className="stat-label">Total Chats</span>
              <div className="stat-number">{totalChats}</div>
              <span className="stat-growth green">↑ 12%</span>
            </div>
          </div>

          {/* 2. Documents */}
          <div
            className="embedded-stat-card stat-docs"
            onClick={() => onInvokeTool?.("knowledge")}
            role="button"
            tabIndex={0}
          >
            <div className="stat-icon-wrap blue">📄</div>
            <div className="stat-meta">
              <span className="stat-label">Documents</span>
              <div className="stat-number">{totalDocs}</div>
              <span className="stat-growth blue">↑ 0%</span>
            </div>
          </div>

          {/* 3. Memories */}
          <div
            className="embedded-stat-card stat-memories"
            onClick={() => onInvokeTool?.("memories")}
            role="button"
            tabIndex={0}
          >
            <div className="stat-icon-wrap pink">🧠</div>
            <div className="stat-meta">
              <span className="stat-label">Memories</span>
              <div className="stat-number">{totalMemories}</div>
              <span className="stat-growth pink">↑ 8%</span>
            </div>
          </div>

          {/* 4. Uptime */}
          <div className="embedded-stat-card stat-uptime">
            <div className="stat-icon-wrap purple">⚡</div>
            <div className="stat-meta">
              <span className="stat-label">Uptime</span>
              <div className="stat-number">{uptime}</div>
              <span className="stat-growth purple">↑ 0.1%</span>
            </div>
          </div>
        </div>

        {/* Lower Row: Activity Overview & Recent Activity */}
        <div className="embedded-dash-lower-grid">
          {/* Activity Overview Spline Wave Chart */}
          <div className="embedded-dash-chart-card">
            <div className="chart-header-row">
              <span className="chart-title">Activity Overview</span>
              <div className="chart-legend">
                <span className="legend-item">
                  <span className="dot dot-green" /> Chats
                </span>
                <span className="legend-item">
                  <span className="dot dot-teal" /> Documents
                </span>
              </div>
            </div>

            {/* SVG Spline Wave Chart */}
            <div className="chart-svg-wrap">
              <svg viewBox="0 0 400 130" className="spline-chart-svg" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="chartWaveGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.28" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                  </linearGradient>
                </defs>

                {/* Horizontal Grid Lines */}
                <line x1="25" y1="20" x2="390" y2="20" stroke="#f1f5f9" strokeWidth="1" />
                <line x1="25" y1="50" x2="390" y2="50" stroke="#f1f5f9" strokeWidth="1" />
                <line x1="25" y1="80" x2="390" y2="80" stroke="#f1f5f9" strokeWidth="1" />
                <line x1="25" y1="110" x2="390" y2="110" stroke="#e2e8f0" strokeWidth="1" />

                {/* Y Axis Numbers */}
                <text x="8" y="24" fill="#94a3b8" fontSize="10">4</text>
                <text x="8" y="54" fill="#94a3b8" fontSize="10">3</text>
                <text x="8" y="84" fill="#94a3b8" fontSize="10">2</text>
                <text x="8" y="114" fill="#94a3b8" fontSize="10">0</text>

                {/* Gradient Fill Area */}
                <path
                  d="M 30 92 C 60 92, 75 92, 105 85 C 135 70, 160 55, 190 68 C 220 80, 240 50, 275 52 C 310 54, 335 78, 365 60 C 375 54, 385 45, 388 42 L 388 110 L 30 110 Z"
                  fill="url(#chartWaveGrad)"
                />

                {/* Green Spline Stroke */}
                <path
                  d="M 30 92 C 60 92, 75 92, 105 85 C 135 70, 160 55, 190 68 C 220 80, 240 50, 275 52 C 310 54, 335 78, 365 60 C 375 54, 385 45, 388 42"
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />

                {/* Data Points */}
                <circle cx="30" cy="92" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
                <circle cx="105" cy="85" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
                <circle cx="190" cy="68" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
                <circle cx="275" cy="52" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
                <circle cx="365" cy="60" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
                <circle cx="388" cy="42" r="3.5" fill="#ffffff" stroke="#10b981" strokeWidth="2" />
              </svg>

              {/* X Axis Days */}
              <div className="chart-x-labels">
                <span>Mon</span>
                <span>Tue</span>
                <span>Wed</span>
                <span>Thu</span>
                <span>Fri</span>
                <span>Sat</span>
                <span>Sun</span>
              </div>
            </div>
          </div>

          {/* Recent Activity Card */}
          <div className="embedded-dash-recent-card">
            <div className="chart-header-row">
              <span className="chart-title">Recent Activity</span>
            </div>
            <div className="recent-activity-list">
              <div
                className="recent-activity-item"
                onClick={() => onInvokeTool?.("knowledge")}
                role="button"
                tabIndex={0}
              >
                <div className="activity-icon-pill green">📄</div>
                <div className="activity-info">
                  <span className="activity-name">New document uploaded</span>
                  <span className="activity-time">2 min ago</span>
                </div>
                <span className="activity-arrow">›</span>
              </div>

              <div
                className="recent-activity-item"
                onClick={() => onInvokeTool?.("memories")}
                role="button"
                tabIndex={0}
              >
                <div className="activity-icon-pill orange">🧠</div>
                <div className="activity-info">
                  <span className="activity-name">Memory updated</span>
                  <span className="activity-time">5 min ago</span>
                </div>
                <span className="activity-arrow">›</span>
              </div>

              <div
                className="recent-activity-item"
                onClick={() => onInvokeTool?.("chat")}
                role="button"
                tabIndex={0}
              >
                <div className="activity-icon-pill purple">💬</div>
                <div className="activity-info">
                  <span className="activity-name">Chat session started</span>
                  <span className="activity-time">10 min ago</span>
                </div>
                <span className="activity-arrow">›</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

