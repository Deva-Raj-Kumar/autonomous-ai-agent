"use client";
// Production AI Chat Agent: Long-term Semantic Memory + Modern White/Dark Green Aesthetic

import { useEffect, useRef, useState } from "react";

import Markdown from "@/components/Markdown";
import { ErrorBox, Spinner } from "@/components/ui";
import { apiFetch } from "@/lib/api";

const STARTERS = [
  {
    title: "🎯 10 Startup Job Openings",
    desc: "Review the top 10 AI Engineer and Python fresher roles in Bengaluru & Hyderabad",
    prompt: "Give me a summary of the 10 AI Engineer and Python Developer fresher job openings in Bengaluru and Hyderabad from our latest report, including companies and eligibility.",
  },
  {
    title: "💰 Salary & Stipend Benchmark",
    desc: "Compare packages across AI startups (Sarvam AI, Yellow.ai, Darwinbox)",
    prompt: "Compare the expected fresher salaries and stipends between Bengaluru and Hyderabad tech startups based on the collected job data.",
  },
  {
    title: "🛠️ Top In-Demand Skills",
    desc: "Analyze languages, ML frameworks, and tools needed for freshers",
    prompt: "What are the top required skills, libraries, and frameworks across these fresher job listings? Which ones should I learn first?",
  },
  {
    title: "🧠 Check Agent Memory",
    desc: "Inspect what the agent has remembered about you and your preferences",
    prompt: "What have you learned and remembered about my interests and workflow in our previous sessions?",
  },
];

export default function ChatPage() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, busy]);

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
    <div className="chat-shell">
      {/* Header Card */}
      <section className="chat-header-card">
        <div className="chat-header-agent">
          <div className="chat-header-avatar">⚡</div>
          <div className="chat-header-info">
            <div className="chat-header-title">
              Autonomous AI Copilot
              <span className="status-indicator-dot" title="Online" />
            </div>
            <div className="chat-header-tags">
              <span className="small badge badge-good">Gemini 3.5 Flash</span>
              <span className="small badge badge-info">🧠 Long-Term Memory Active</span>
              {sessionId && <span className="small muted">Session: {sessionId.slice(0, 8)}…</span>}
            </div>
          </div>
        </div>

        <button type="button" className="secondary-btn" onClick={newChat}>
          🔄 New Chat
        </button>
      </section>

      <ErrorBox error={error} />

      {/* Main Chat Window */}
      <section className="chat-window-card">
        <div className="chat-scroll-area" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="chat-empty-state">
              <div className="chat-empty-icon">💬</div>
              <h2>How can I assist your workflow today?</h2>
              <p className="muted small" style={{ maxWidth: "460px", margin: "0.4rem 0 1rem" }}>
                Ask questions about analyzed job openings, query database reports, or instruct the
                agent. Useful preferences and facts are automatically remembered across sessions.
              </p>

              <div className="chat-starter-grid">
                {STARTERS.map((s, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="chat-starter-btn"
                    onClick={() => send(null, s.prompt)}
                  >
                    <strong>{s.title}</strong>
                    <span className="small muted">{s.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={index} className={`chat-msg-row ${message.role}`}>
                <div
                  className={`chat-msg-avatar ${
                    message.role === "user" ? "user-av" : "ai-av"
                  }`}
                >
                  {message.role === "user" ? "You" : "⚡"}
                </div>

                <div className="chat-msg-bubble">
                  {message.role === "assistant" ? (
                    <Markdown>{message.content}</Markdown>
                  ) : (
                    <p style={{ margin: 0 }}>{message.content}</p>
                  )}

                  {message.used?.length > 0 && (
                    <div className="chat-memories-box">
                      <span className="muted" style={{ fontWeight: 600 }}>
                        Recalled Memories:
                      </span>
                      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                        {message.used.map((mem, i) => (
                          <span key={i} className="memory-used-pill">
                            🧠 {mem}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {message.learned?.length > 0 && (
                    <div className="chat-memories-box">
                      <span style={{ color: "var(--accent)", fontWeight: 600 }}>
                        Memory Updated:
                      </span>
                      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                        {message.learned.map((change, i) => (
                          <span key={i} className="memory-learned-pill">
                            ✨ {change}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {busy && (
            <div className="chat-msg-row assistant">
              <div className="chat-msg-avatar ai-av">⚡</div>
              <div className="chat-msg-bubble" style={{ background: "#ffffff" }}>
                <div className="typing-dots">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
                <span className="small muted" style={{ marginLeft: "0.4rem" }}>
                  Autonomous Agent is thinking…
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <form className="chat-input-area" onSubmit={(e) => send(e)}>
          <input
            className="chat-text-input"
            aria-label="Message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={4000}
            placeholder="Ask anything about startup jobs, skills, reports, or teach the agent a memory…"
            disabled={busy}
          />
          <button
            type="submit"
            className="chat-send-btn"
            disabled={busy || !draft.trim()}
          >
            {busy ? "Thinking…" : "Send ➤"}
          </button>
        </form>
      </section>
    </div>
  );
}
