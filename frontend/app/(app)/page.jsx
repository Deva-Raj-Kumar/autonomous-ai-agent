"use client";
// Vision AI - Conversational Home Page
// Clean Landing Experience with Robot with Laptop,
// Direct Links to Dedicated Module Pages (/dashboard, /memories, /knowledge),
// and Pure Dark Theme (Zero White)

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import Markdown from "@/components/Markdown";
import RobotMascot from "@/components/RobotMascot";
import RobotWithLaptop from "@/components/RobotWithLaptop";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [thinkingMode, setThinkingMode] = useState(false);

  const scrollRef = useRef(null);
  const fileInputRef = useRef(null);
  const recognitionRef = useRef(null);
  const landingTextareaRef = useRef(null);
  const chatTextareaRef = useRef(null);

  // Auto-resize textarea to expand vertically like ChatGPT (up to 220px)
  const autoResize = (target) => {
    if (!target) return;
    target.style.height = "auto";
    const scrollH = target.scrollHeight;
    const newHeight = Math.min(Math.max(scrollH, 26), 220);
    target.style.height = `${newHeight}px`;
  };

  useEffect(() => {
    if (landingTextareaRef.current) autoResize(landingTextareaRef.current);
    if (chatTextareaRef.current) autoResize(chatTextareaRef.current);
  }, [draft]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, busy]);

  // Handle new chat and prompt events from sidebar
  useEffect(() => {
    const handleNewChat = () => {
      setSessionId(null);
      setMessages([]);
      setDraft("");
      if (landingTextareaRef.current) landingTextareaRef.current.style.height = "auto";
      if (chatTextareaRef.current) chatTextareaRef.current.style.height = "auto";
    };

    const handleSendPrompt = (e) => {
      const prompt = e.detail?.prompt;
      if (prompt) handleSendMessage(prompt);
    };

    window.addEventListener("agent-new-chat", handleNewChat);
    window.addEventListener("agent-send-prompt", handleSendPrompt);

    // Check if URL has ?prompt=
    const promptFromUrl = searchParams.get("prompt");
    if (promptFromUrl) {
      handleSendMessage(promptFromUrl);
    }

    return () => {
      window.removeEventListener("agent-new-chat", handleNewChat);
      window.removeEventListener("agent-send-prompt", handleSendPrompt);
    };
  }, [searchParams]);

  const toggleVoiceInput = () => {
    if (typeof window === "undefined") return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Voice input is supported in Google Chrome, Microsoft Edge, and Safari.");
      return;
    }

    if (listening && recognitionRef.current) {
      recognitionRef.current.stop();
      setListening(false);
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = "en-US";

      recognition.onstart = () => setListening(true);
      recognition.onresult = (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript;
        if (transcript) {
          setDraft((prev) => (prev ? `${prev} ${transcript}` : transcript));
        }
      };
      recognition.onerror = () => setListening(false);
      recognition.onend = () => setListening(false);

      recognitionRef.current = recognition;
      recognition.start();
    } catch {
      setListening(false);
    }
  };

  const handleSendMessage = async (textOverride = null) => {
    const text = (textOverride || draft).trim();
    if (!text || busy) return;

    const lower = text.toLowerCase();

    // Direct navigation if user asks to open full module page
    if (lower === "open dashboard" || lower === "go to dashboard") {
      setDraft("");
      router.push("/dashboard");
      return;
    }
    if (lower === "open memory bank" || lower === "open memories" || lower === "go to memories") {
      setDraft("");
      router.push("/memories");
      return;
    }
    if (lower === "open knowledge" || lower === "open knowledge rag" || lower === "go to knowledge") {
      setDraft("");
      router.push("/knowledge");
      return;
    }

    const timeNow = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const userMsgId = `u-${Date.now()}`;
    setMessages((prev) => [...prev, { id: userMsgId, role: "user", content: text }]);
    setDraft("");
    if (landingTextareaRef.current) landingTextareaRef.current.style.height = "auto";
    if (chatTextareaRef.current) chatTextareaRef.current.style.height = "auto";
    setBusy(true);

    // Notify sidebar layout to immediately display new chat in Recents history
    if (typeof window !== "undefined") {
      const chatTitle = text.length > 36 ? text.slice(0, 36) + "..." : text;
      window.dispatchEvent(
        new CustomEvent("agent-chat-started", {
          detail: { title: chatTitle },
        })
      );
    }

    try {
      // 1. MODULE FEATURE: DASHBOARD & SYSTEM OVERVIEW IN CHAT
      const isDashboardStatsQuery =
        lower.includes("show dashboard") ||
        lower.includes("project dashboard") ||
        lower.includes("system stats") ||
        lower.includes("dashboard stats") ||
        lower === "stats" ||
        lower === "dashboard" ||
        lower.includes("recent runs");

      if (isDashboardStatsQuery) {
        const [healthRes, docsRes, memsRes, runsRes] = await Promise.allSettled([
          apiFetch("/health"),
          apiFetch("/knowledge/documents"),
          apiFetch("/memories"),
          apiFetch("/agent/runs?limit=5"),
        ]);

        const health = healthRes.status === "fulfilled" ? healthRes.value : { llm_model: "gemini-2.5-flash", llm_provider: "Google" };
        const docs = docsRes.status === "fulfilled" && Array.isArray(docsRes.value) ? docsRes.value : [];
        const mems = memsRes.status === "fulfilled" && Array.isArray(memsRes.value) ? memsRes.value : [];
        const runs = runsRes.status === "fulfilled" && Array.isArray(runsRes.value) ? runsRes.value : [];

        const replyContent = `### 📊 Vision AI Executive Dashboard Summary

Here is the real-time status across your modules:

- 🤖 **Vision AI Core**: \`${health.llm_model || "Active"}\` (${health.llm_provider || "Configured"})
- 📄 **Knowledge Base (RAG)**: **${docs.length}** document${docs.length === 1 ? "" : "s"} indexed in ChromaDB
- 🧠 **Memory Bank**: **${mems.length}** user preference${mems.length === 1 ? "" : "s"} & memories stored
- 🎯 **Autonomous Runs**: **${runs.length}** goal execution${runs.length === 1 ? "" : "s"} recorded

#### Recent Autonomous Runs
${runs.length > 0
  ? runs.slice(0, 3).map((r, i) => `${i + 1}. **Goal**: "${r.goal}" — Status: \`${r.status}\``).join("\n")
  : "_No runs recorded yet. Type `run goal: <your goal>` to start an autonomous run._"}

You can view full interactive charts in the [Dashboard](/dashboard).`;

        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            type: "text",
            content: replyContent,
            time: timeNow,
          },
        ]);
        return;
      }

      // 2. MODULE FEATURE: AUTONOMOUS GOAL / EMAIL AUTOMATION RUN
      const isGoalLaunch =
        lower.startsWith("run goal:") ||
        lower.startsWith("start goal:") ||
        lower.startsWith("execute goal:") ||
        lower.startsWith("send email") ||
        lower.startsWith("send an email") ||
        lower.startsWith("send meeting") ||
        lower.startsWith("send a meeting") ||
        lower.startsWith("draft email") ||
        lower.startsWith("draft an email");

      if (isGoalLaunch) {
        const goalText = text.replace(/^(run goal:|start goal:|execute goal:)/i, "").trim();
        if (goalText) {
          const runRes = await apiFetch("/agent/runs", {
            method: "POST",
            json: { goal: goalText },
          });
          if (runRes?.run_id) {
            router.push(`/runs/${runRes.run_id}`);
            return;
          }
        }
      }

      // 3. MODULE FEATURE: MEMORY BANK RETRIEVAL
      const isMemoryRetrievalQuery =
        lower.includes("what do you remember") ||
        lower.includes("show my memories") ||
        lower.includes("check my memories") ||
        lower.includes("list my memories") ||
        lower === "memories" ||
        lower === "my memories";

      if (isMemoryRetrievalQuery) {
        const mems = await apiFetch("/memories");
        const list = Array.isArray(mems) ? mems : [];
        const replyContent = `### 🧠 Memory Bank Records

${list.length > 0
  ? list.map((m, i) => `${i + 1}. **${m.content}**  \n   _Category: \`${m.category}\` | Importance: ${m.importance}_`).join("\n\n")
  : "No memories saved yet. You can tell me anything to remember, e.g. *'Remember that I prefer Python and dark mode'*."}

You can view and manage all memories in [Memory Bank](/memories).`;

        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            type: "text",
            content: replyContent,
            time: timeNow,
          },
        ]);
        return;
      }

      // 4. MODULE FEATURE: KNOWLEDGE BASE (RAG) RETRIEVAL & ANSWERING
      const isRagQuery =
        lower.includes("salary") ||
        lower.includes("job") ||
        lower.includes("internship") ||
        lower.includes("document") ||
        lower.includes("documents") ||
        lower.includes("sample_") ||
        lower.includes(".txt") ||
        lower.includes(".md") ||
        lower.includes(".pdf") ||
        lower.includes("knowledge base") ||
        lower.startsWith("ask doc") ||
        lower.startsWith("search doc");

      if (isRagQuery) {
        try {
          const ragRes = await apiFetch("/knowledge/ask", {
            method: "POST",
            json: { question: text, k: 3 },
          });

          if (ragRes?.answer && !ragRes.answer.toLowerCase().includes("not enough information in the documents")) {
            let citedSources = "";
            if (ragRes.sources?.length > 0) {
              citedSources =
                "\n\n📚 **Document Sources Cited:**\n" +
                ragRes.sources.map((s, idx) => `[${idx + 1}] **${s.source}** (chunk ${s.chunk_index})`).join("\n");
            }
            const replyContent = `${ragRes.answer}${citedSources}\n\n_Answered via [Knowledge RAG](/knowledge) with semantic search and citations._`;

            setMessages((prev) => [
              ...prev,
              {
                id: `a-${Date.now()}`,
                role: "assistant",
                type: "text",
                content: replyContent,
                time: timeNow,
              },
            ]);
            return;
          }
        } catch {
          // Fall through to general /chat if RAG is empty
        }
      }

      // 5. STANDARD CHAT: CONVERSATIONAL TURN + MEMORY EXTRACTION
      const turn = await apiFetch("/chat", {
        method: "POST",
        json: { message: text, session_id: sessionId },
      });
      setSessionId(turn.session_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          type: "text",
          content: turn.reply,
          used: turn.memories_used?.map((x) => x.content) || [],
          learned: turn.memory_changes?.filter((c) => c.applied)?.map((c) => `${c.action}: ${c.content}`) || [],
          time: timeNow,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          type: "text",
          content: `⚠️ Error communicating with Vision AI: ${err.message || String(err)}. Please verify the backend is running.`,
          time: timeNow,
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    const timeNow = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        content: `Uploaded file: ${file.name}`,
      },
    ]);
    setBusy(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await apiFetch("/knowledge/upload", {
        method: "POST",
        body: formData,
      });
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          type: "text",
          content: `✅ Successfully uploaded and indexed **${file.name}** into ChromaDB (${res.chunks} chunks created)! You can now ask questions about it or view it in [Knowledge RAG](/knowledge).`,
          time: timeNow,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          type: "text",
          content: `❌ Upload failed for ${file.name}: ${err.message || String(err)}`,
          time: timeNow,
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const isLandingView = messages.length === 0;
  const firstName = user?.username ? user.username.split(" ")[0] : "Deva";

  return (
    <div className="unified-conversation-hub">
      {/* Hidden File Picker Input */}
      <input
        type="file"
        ref={fileInputRef}
        style={{ display: "none" }}
        accept=".pdf,.md,.txt,.docx,.csv,.xlsx"
        onChange={(e) => {
          if (e.target.files?.[0]) handleFileUpload(e.target.files[0]);
        }}
      />

      {/* 1. LANDING SCREEN (Reference Images 1 & 2: Minimal Style with Zero White & Without Mics) */}
      {isLandingView && (
        <div className="hero-landing-container">
          <div className="hero-landing-content">
            {/* Minimal Centered Headline matching Reference Images 1 & 2 */}
            <h1 className="chatgpt-landing-title">
              Hey, {firstName}. Ready to dive in?
            </h1>

            {/* Central Sleek Capsule Composer matching Reference Pics 1 & 2 without mics */}
            <form
              className="chatgpt-capsule-composer"
              onSubmit={(e) => {
                e.preventDefault();
                handleSendMessage();
              }}
            >
              {/* Left Attachment Button: Clean '+' symbol matching user design */}
              <button
                type="button"
                className="chatgpt-clip-btn"
                title="Upload document to Knowledge base (.pdf, .md, .txt, .docx, .csv, .xlsx)"
                onClick={() => fileInputRef.current?.click()}
                aria-label="Attach file"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>

              {/* Main Text Input (Enter to send, Shift+Enter for newline, auto-expanding like ChatGPT) */}
              <textarea
                ref={landingTextareaRef}
                rows={1}
                className="chatgpt-capsule-input"
                placeholder="Ask the Agent AI..."
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  autoResize(e.target);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                disabled={busy}
                autoFocus
              />

              {/* Right Circular Send Button: Solid emerald green circle with white Arrow Up icon */}
              <button
                type="submit"
                className={`chatgpt-send-circle ${draft.trim() ? "ready" : ""}`}
                disabled={!draft.trim() || busy}
                title="Send message"
                aria-label="Send message"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" className="send-arrow-icon">
                  <path d="M12 19V5" />
                  <path d="m5 12 7-7 7 7" />
                </svg>
              </button>
            </form>

            {/* Quick Access Modules in exact order of sidebar/pics: Dashboard, Memory Bank, Knowledge RAG */}
            <div className="landing-quick-modules">
              <Link href="/dashboard" className="landing-quick-pill" title="Open Dashboard">
                <span className="pill-icon">📊</span>
                <span className="pill-text">Dashboard</span>
              </Link>
              <Link href="/memories" className="landing-quick-pill" title="Open Memory Bank">
                <span className="pill-icon">🧠</span>
                <span className="pill-text">Memory Bank</span>
              </Link>
              <Link href="/knowledge" className="landing-quick-pill" title="Open Knowledge RAG">
                <span className="pill-icon">📄</span>
                <span className="pill-text">Knowledge RAG</span>
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* 2. CONVERSATIONAL STREAM (When messages are active) */}
      {!isLandingView && (
        <div className="unified-chat-stream" ref={scrollRef}>
          <div className="unified-messages-inner">
            {messages.map((msg) => {
              const isUser = msg.role === "user";

              if (isUser) {
                return (
                  <div key={msg.id} className="message-row user-row">
                    <div className="user-message-bubble">
                      <span>{msg.content}</span>
                    </div>
                    <div className="user-avatar-badge" title={user?.username || "You"}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                        <circle cx="12" cy="7" r="4" />
                      </svg>
                    </div>
                  </div>
                );
              }

              // Assistant Message
              return (
                <div key={msg.id} className="message-row assistant-row">
                  <div className="assistant-avatar-badge">
                    <RobotMascot size={36} />
                  </div>

                  <div className="assistant-content-card">
                    {msg.content && (
                      <div className="markdown-body">
                        <Markdown content={msg.content} />
                      </div>
                    )}

                    {msg.used?.length > 0 && (
                      <div className="memory-reflection-box">
                        <span className="small bold" style={{ color: "#34d399" }}>🧠 Recalled from memory:</span>
                        <ul>
                          {msg.used.map((u, i) => (
                            <li key={i}>{u}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {msg.learned?.length > 0 && (
                      <div className="memory-learned-box">
                        <span className="small bold" style={{ color: "#60a5fa" }}>💡 Saved to memory:</span>
                        <ul>
                          {msg.learned.map((l, i) => (
                            <li key={i}>{l}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="message-timestamp">{msg.time || "Just now"}</div>
                  </div>
                </div>
              );
            })}

            {busy && (
              <div className="message-row assistant-row">
                <div className="assistant-avatar-badge">
                  <RobotMascot size={36} />
                </div>
                <div className="assistant-content-card typing-card">
                  <div className="typing-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 3. BOTTOM COMPOSER (Visible during active conversations) */}
      {!isLandingView && (
        <div className="unified-composer-wrapper">
          <form
            className="chatgpt-capsule-composer bottom-capsule"
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
          >
            <button
              type="button"
              className="chatgpt-clip-btn"
              title="Upload document (.pdf, .md, .txt, .docx, .csv, .xlsx)"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach file"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>
            <textarea
              ref={chatTextareaRef}
              rows={1}
              className="chatgpt-capsule-input"
              placeholder="Ask the Agent AI..."
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                autoResize(e.target);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              disabled={busy}
              autoFocus
            />
            <button
              type="submit"
              className={`chatgpt-send-circle ${draft.trim() ? "ready" : ""}`}
              disabled={busy || !draft.trim()}
              title="Send message"
              aria-label="Send message"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" className="send-arrow-icon">
                <path d="M12 19V5" />
                <path d="m5 12 7-7 7 7" />
              </svg>
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
