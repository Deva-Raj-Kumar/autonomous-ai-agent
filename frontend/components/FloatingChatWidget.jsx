"use client";
// Dedicated AI Chat Assistant Widget
// Floating button icon: AI Robot with Headset (Picture 2 reference)
// Popup modal: Pure AI Chat Bot without bottom tabs (Picture 3 reference updated)

import { useEffect, useRef, useState } from "react";

import Markdown from "@/components/Markdown";
import { ErrorBox } from "@/components/ui";
import { apiFetch, downloadFile } from "@/lib/api";

function RobotIcon({ size = 32, className = "" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      {/* Antenna */}
      <line x1="24" y1="3" x2="24" y2="9" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" />
      <circle cx="24" cy="3.5" r="2.5" fill="currentColor" />

      {/* Headset Arc */}
      <path
        d="M10 18C10 10.5 16 5 24 5C32 5 38 10.5 38 18"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      {/* Headset Ear Cups */}
      <rect x="7" y="14" width="4.5" height="9.5" rx="2.2" fill="currentColor" />
      <rect x="36.5" y="14" width="4.5" height="9.5" rx="2.2" fill="currentColor" />

      {/* Headset Mic Boom */}
      <path
        d="M38.5 22V25.5C38.5 28 36.5 30 34 30H27"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="26" cy="30" r="2.2" fill="currentColor" />

      {/* Robot Head */}
      <rect
        x="12"
        y="10"
        width="24"
        height="18"
        rx="7"
        fill="currentColor"
        fillOpacity="0.2"
        stroke="currentColor"
        strokeWidth="2.8"
      />

      {/* Robot Eyes */}
      <circle cx="18" cy="18" r="2.6" fill="currentColor" />
      <circle cx="30" cy="18" r="2.6" fill="currentColor" />

      {/* Smile */}
      <path
        d="M19 23C20.8 24.8 27.2 24.8 29 23"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />

      {/* Torso / Body */}
      <path
        d="M13 35C13 32 15.5 30 19 30H29C32.5 30 35 32 35 35V42H13V35Z"
        fill="currentColor"
        fillOpacity="0.25"
        stroke="currentColor"
        strokeWidth="2.8"
      />

      {/* "AI" on Chest */}
      <text
        x="24"
        y="38.5"
        textAnchor="middle"
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        fontSize="7.5"
        fontWeight="900"
        fill="currentColor"
        letterSpacing="0.8"
      >
        AI
      </text>
    </svg>
  );
}

const STARTERS = [
  {
    title: "🎯 10 Startup Job Openings",
    prompt: "Summarize the 10 AI Engineer and Python Developer fresher job openings in Bengaluru and Hyderabad from the latest report, including companies and eligibility.",
  },
  {
    title: "💰 Salary & Stipend Benchmark",
    prompt: "Compare the expected fresher salaries and stipends between Bengaluru and Hyderabad tech startups based on the collected job data.",
  },
  {
    title: "🛠️ In-Demand Skills",
    prompt: "What are the top required programming skills, libraries, and frameworks across these fresher job listings?",
  },
  {
    title: "📊 Download Reports (.xlsx / .csv)",
    isDownload: true,
  },
];

export default function FloatingChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, busy]);

  const handleDownload = async (filename) => {
    try {
      await downloadFile(filename);
    } catch (err) {
      setError(err.message || "Failed to download file");
    }
  };

  const send = async (e, textOverride = null) => {
    if (e) e.preventDefault();
    const text = (textOverride || draft).trim();
    if (!text || busy) return;

    setMessages((m) => [...m, { role: "user", content: text }]);
    setDraft("");
    setBusy(true);
    setError(null);

    try {
      const turn = await apiFetch("/chat", {
        method: "POST",
        json: { message: text, session_id: sessionId },
      });
      setSessionId(turn.session_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: turn.reply,
          used: turn.memories_used?.map((x) => x.content) || [],
          learned:
            turn.memory_changes
              ?.filter((c) => c.applied)
              ?.map((c) => `${c.action}: ${c.content}`) || [],
        },
      ]);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const newChat = () => {
    setSessionId(null);
    setMessages([]);
    setError(null);
  };

  return (
    <aside aria-label="AI Chat Assistant Widget">
      {/* Floating Action Button with AI Robot Icon (Picture 2 Reference) */}
      {!isOpen && (
        <button
          type="button"
          className="floating-chat-fab"
          onClick={() => setIsOpen(true)}
          aria-label="Open AI Chat Assistant"
          title="Chat with AI Agent"
        >
          <RobotIcon size={34} className="fab-robot-icon" />
          <span className="fab-online-dot" />
        </button>
      )}

      {/* Floating Popup Window - Dedicated AI Chatbot without bottom tabs */}
      {isOpen && (
        <div
          className="floating-chat-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Autonomous AI Chatbot"
        >
          {/* Header Card (Rich Dark Green) */}
          <div className="widget-header">
            <div className="widget-header-top">
              <div className="widget-brand-row">
                <div className="widget-brand-avatar">
                  <RobotIcon size={20} />
                </div>
                <div>
                  <div className="widget-brand-title">Autonomous Agent</div>
                  <div className="widget-status-row">
                    <span className="status-indicator-dot" />
                    <span className="small" style={{ color: "#d1fae5", fontSize: "0.72rem" }}>
                      Online · Ready to assist
                    </span>
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                <button
                  type="button"
                  className="widget-icon-btn"
                  onClick={newChat}
                  title="New conversation"
                >
                  🔄
                </button>
                <button
                  type="button"
                  className="widget-icon-btn"
                  onClick={() => setIsOpen(false)}
                  aria-label="Close Assistant"
                  title="Close"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="widget-greeting-title">Hey! How can we help you today?</div>
          </div>

          <ErrorBox error={error} />

          {/* Main Chat Conversation Area (No bottom tabs) */}
          <div className="widget-chat-messages" ref={scrollRef}>
            {messages.length === 0 ? (
              <div className="widget-empty-chat">
                <div className="widget-empty-robot">
                  <RobotIcon size={44} />
                </div>
                <h3>AI Career & Research Assistant</h3>
                <p className="small muted" style={{ margin: "0.25rem 0 0.85rem" }}>
                  Ask questions about Bengaluru and Hyderabad startup jobs, skills, or download verified reports.
                </p>

                <div className="widget-starter-chips">
                  {STARTERS.map((s, idx) => (
                    <button
                      key={idx}
                      type="button"
                      className="widget-chip"
                      onClick={() => {
                        if (s.isDownload) {
                          handleDownload("ai_python_fresher_jobs_blr_hyd.xlsx");
                        } else {
                          send(null, s.prompt);
                        }
                      }}
                    >
                      {s.title}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div key={idx} className={`widget-msg ${m.role}`}>
                  <div className="widget-bubble">
                    {m.role === "assistant" ? (
                      <Markdown>{m.content}</Markdown>
                    ) : (
                      <p style={{ margin: 0 }}>{m.content}</p>
                    )}

                    {m.used?.length > 0 && (
                      <div className="widget-mem-note">
                        🧠 <em>Recalled: {m.used.join(", ")}</em>
                      </div>
                    )}

                    {m.learned?.length > 0 && (
                      <div className="widget-mem-note good">
                        ✨ <em>Learned: {m.learned.join(", ")}</em>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}

            {busy && (
              <div className="widget-msg assistant">
                <div className="widget-bubble thinking">
                  <div className="typing-dots">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                  </div>
                  <span className="small muted" style={{ marginLeft: "0.35rem" }}>
                    Agent is thinking…
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Bottom Chat Input Row (Directly pinned at the bottom) */}
          <form className="widget-input-row" onSubmit={(e) => send(e)}>
            <input
              className="widget-chat-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask agent anything…"
              disabled={busy}
              autoFocus
            />
            <button
              type="submit"
              className="widget-send-btn"
              disabled={busy || !draft.trim()}
              title="Send message"
            >
              ➤
            </button>
          </form>
        </div>
      )}
    </aside>
  );
}
