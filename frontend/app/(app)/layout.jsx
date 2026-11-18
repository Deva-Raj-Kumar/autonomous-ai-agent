"use client";
// Vision AI - Sleek Executive Dark Layout
// Top Sidebar: Vision AI brand + Search [🔍] + Sidebar Toggle [|] on Row 1.
// New chat + Modules grouped without "MODULES" header label (User Request).
// Floating Search Modal Dialog (Matching Image 3).
// Recents Section: Full-height scrollable list with all chat & module history (Matching Image 5).
// Landing view centered in the middle (Matching Image 2).

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import RobotMascot from "@/components/RobotMascot";
import ProfileModal from "@/components/ProfileModal";
import { Spinner } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const INITIAL_MODULE_HISTORY = [
  { id: "c-1", type: "chat", title: "Nextjs Warning Explained", module: "Chat", icon: "💬" },
  { id: "c-2", type: "chat", title: "Software Development Life Cycle", module: "Chat", icon: "💬" },
  { id: "c-3", type: "chat", title: "UI Logout Design", module: "Chat", icon: "💬" },
  { id: "c-4", type: "chat", title: "Test Failures Debugging", module: "Chat", icon: "💬" },
  { id: "c-5", type: "chat", title: "Customer Ticketing System", module: "Chat", icon: "💬" },
  { id: "c-6", type: "chat", title: "Admin Alarms Unit Test", module: "Chat", icon: "💬" },
  { id: "c-7", type: "chat", title: "Git line ending warnings", module: "Chat", icon: "💬" },
  { id: "c-8", type: "chat", title: "Login Flow Error Fix", module: "Chat", icon: "💬" },
  { id: "c-9", type: "chat", title: "Permission Handling Example", module: "Chat", icon: "💬" },
  { id: "c-10", type: "chat", title: "Hello Assistance", module: "Chat", icon: "💬" },
  { id: "c-11", type: "chat", title: "Next.js Admin Dashboard Setup", module: "Chat", icon: "💬" },
  { id: "c-12", type: "chat", title: "Client Permissions Setup", module: "Chat", icon: "💬" },
  { id: "c-13", type: "chat", title: "Protecting Pages with Permissions", module: "Chat", icon: "💬" },
  { id: "c-14", type: "chat", title: "SQLAlchemy Timestamp Explanation", module: "Chat", icon: "💬" },
  { id: "c-15", type: "chat", title: "AI Project Usage", module: "Chat", icon: "💬" },
  { id: "c-16", type: "chat", title: "Build AI Agent Roadmap", module: "Chat", icon: "💬" },
  { id: "c-17", type: "chat", title: "Python Binary Tree Validation", module: "Chat", icon: "💬" },
  { id: "c-18", type: "chat", title: "Build Hostel Voice Agent", module: "Chat", icon: "💬" },
  { id: "c-19", type: "chat", title: "Run In Terminal", module: "Chat", icon: "💬" },
  { id: "c-20", type: "chat", title: "Project Build Options", module: "Chat", icon: "💬" },
  { id: "c-21", type: "chat", title: "What is RAG in AI?", module: "Chat", icon: "💬" },
  { id: "c-22", type: "chat", title: "Summarize my documents", module: "Chat", icon: "💬" },
  { id: "c-23", type: "knowledge", title: "sample_job_description.txt", module: "Knowledge", icon: "📄" },
  { id: "c-24", type: "knowledge", title: "sample_internship.md", module: "Knowledge", icon: "📄" },
  { id: "c-25", type: "memory", title: "Python Developer preference", module: "Memory", icon: "🧠" },
  { id: "c-26", type: "dashboard", title: "RAG pipeline audit run", module: "Dashboard", icon: "🎯" },
];

export default function AppLayout({ children }) {
  const { user, status, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileOverride, setProfileOverride] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchModalOpen, setSearchModalOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [moduleHistory, setModuleHistory] = useState(INITIAL_MODULE_HISTORY);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("vision_ai_profile");
      if (stored) setProfileOverride(JSON.parse(stored));
    } catch {}

    const handleProfileUpdate = (e) => {
      if (e.detail) setProfileOverride(e.detail);
    };
    window.addEventListener("vision-profile-updated", handleProfileUpdate);
    return () => window.removeEventListener("vision-profile-updated", handleProfileUpdate);
  }, []);

  useEffect(() => {
    if (status === "anonymous") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, router, pathname]);

  // Load persisted history from localStorage on initial mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const deletedRaw = localStorage.getItem("vision_ai_deleted_chats");
      const deletedSet = new Set(deletedRaw ? JSON.parse(deletedRaw).map((t) => t.toLowerCase()) : []);

      const stored = localStorage.getItem("vision_ai_recent_chats");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setModuleHistory((prev) => {
            const seen = new Set(parsed.map((p) => p.title.toLowerCase()));
            const remaining = prev.filter((item) => !seen.has(item.title.toLowerCase()) && !deletedSet.has(item.title.toLowerCase()));
            return [...parsed.filter((p) => !deletedSet.has(p.title.toLowerCase())), ...remaining];
          });
          return;
        }
      }
      if (deletedSet.size > 0) {
        setModuleHistory((prev) => prev.filter((item) => !deletedSet.has(item.title.toLowerCase())));
      }
    } catch {
      // ignore
    }
  }, []);

  // Listen for newly sent chats to instantly prepend to Recents history
  useEffect(() => {
    const handleNewChatStarted = (e) => {
      const title = e.detail?.title;
      if (!title) return;
      setModuleHistory((prev) => {
        const filtered = prev.filter((item) => item.title.toLowerCase() !== title.toLowerCase());
        const newItem = {
          id: `chat-${Date.now()}`,
          type: "chat",
          title,
          module: "Chat",
          icon: "💬",
        };
        const updated = [newItem, ...filtered];
        try {
          localStorage.setItem("vision_ai_recent_chats", JSON.stringify(updated.slice(0, 40)));
        } catch {
          // ignore
        }
        return updated;
      });
    };

    window.addEventListener("agent-chat-started", handleNewChatStarted);
    return () => window.removeEventListener("agent-chat-started", handleNewChatStarted);
  }, []);

  // Dynamically load active module documents & runs from backend
  useEffect(() => {
    if (status !== "authenticated") return;

    let isMounted = true;
    async function fetchLiveHistory() {
      try {
        const [docsRes, memsRes, runsRes] = await Promise.allSettled([
          apiFetch("/knowledge/documents"),
          apiFetch("/memories?limit=3"),
          apiFetch("/agent/runs?limit=3"),
        ]);

        if (!isMounted) return;
        const liveItems = [];

        if (docsRes.status === "fulfilled" && Array.isArray(docsRes.value)) {
          docsRes.value.slice(0, 3).forEach((d, idx) => {
            const docKey = d.source || d.id || `idx-${idx}`;
            liveItems.push({
              id: `doc-${docKey}`,
              type: "knowledge",
              title: d.source || "Document",
              module: "Knowledge",
              icon: "📄",
            });
          });
        }
        if (memsRes.status === "fulfilled" && Array.isArray(memsRes.value)) {
          memsRes.value.slice(0, 3).forEach((m, idx) => {
            const memKey = m.id || m.memory_id || `idx-${idx}`;
            liveItems.push({
              id: `mem-${memKey}`,
              type: "memory",
              title: m.content?.slice(0, 34) || "Saved memory",
              module: "Memory",
              icon: "🧠",
            });
          });
        }
        if (runsRes.status === "fulfilled" && Array.isArray(runsRes.value)) {
          runsRes.value.slice(0, 5).forEach((r, idx) => {
            const runKey = r.run_id || r.id || `idx-${idx}`;
            liveItems.push({
              id: `run-${runKey}`,
              type: "dashboard",
              title: r.goal?.slice(0, 34) || "Autonomous goal",
              module: "Dashboard",
              icon: "🎯",
            });
          });
        }

        if (liveItems.length > 0) {
          const deletedRaw = localStorage.getItem("vision_ai_deleted_chats");
          const deletedSet = new Set(deletedRaw ? JSON.parse(deletedRaw).map((t) => t.toLowerCase()) : []);
          const allowedLiveItems = liveItems.filter((item) => !deletedSet.has(item.title.toLowerCase()));

          setModuleHistory((prev) => {
            const seen = new Set(allowedLiveItems.map((item) => item.title.toLowerCase()));
            const remaining = prev.filter((item) => !seen.has(item.title.toLowerCase()) && !deletedSet.has(item.title.toLowerCase()));
            return [...allowedLiveItems, ...remaining];
          });
        }
      } catch {
        // Fall back gracefully
      }
    }
    fetchLiveHistory();
    return () => {
      isMounted = false;
    };
  }, [status]);

  // Close menus when clicking outside
  useEffect(() => {
    const handleWindowClick = () => {
      setUserMenuOpen(false);
    };
    window.addEventListener("click", handleWindowClick);
    return () => window.removeEventListener("click", handleWindowClick);
  }, []);

  // Keyboard shortcut Ctrl+K / Cmd+K to open Search Modal (Image 3)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchModalOpen((prev) => !prev);
      }
      if (e.key === "Escape" && searchModalOpen) {
        setSearchModalOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [searchModalOpen]);

  if (status !== "authenticated") {
    return (
      <main className="center">
        <Spinner label={status === "loading" ? "Checking your session" : "Redirecting to login"} />
      </main>
    );
  }

  const handleNewChat = () => {
    if (pathname !== "/") {
      router.push("/");
    }
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("agent-new-chat"));
    }
  };

  const handleHistoryItemClick = (item) => {
    setSearchModalOpen(false);
    if (item.type === "chat") {
      if (pathname !== "/") {
        router.push(`/?prompt=${encodeURIComponent(item.title)}`);
      } else if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("agent-send-prompt", { detail: { prompt: item.title } }));
      }
    } else if (item.type === "knowledge") {
      if (pathname !== "/") {
        router.push(`/?prompt=${encodeURIComponent(`What does ${item.title} contain?`)}`);
      } else if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("agent-send-prompt", {
            detail: { prompt: `What does ${item.title} contain?` },
          })
        );
      }
    } else if (item.type === "memory") {
      if (pathname !== "/") {
        router.push(`/?prompt=${encodeURIComponent(`Show details for memory: ${item.title}`)}`);
      } else if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("agent-send-prompt", {
            detail: { prompt: `Show details for memory: ${item.title}` },
          })
        );
      }
    } else if (item.type === "dashboard") {
      if (pathname !== "/") {
        router.push("/dashboard");
      } else if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("agent-send-prompt", {
            detail: { prompt: "Show my project dashboard stats" },
          })
        );
      }
    }
  };

  const handleDeleteRecentChat = (e, item) => {
    e.stopPropagation();
    e.preventDefault();
    setModuleHistory((prev) => {
      const updated = prev.filter((h) => h.id !== item.id && h.title.toLowerCase() !== item.title.toLowerCase());
      try {
        localStorage.setItem("vision_ai_recent_chats", JSON.stringify(updated.slice(0, 40)));
        const deletedRaw = localStorage.getItem("vision_ai_deleted_chats");
        const deleted = deletedRaw ? JSON.parse(deletedRaw) : [];
        if (!deleted.map((d) => d.toLowerCase()).includes(item.title.toLowerCase())) {
          deleted.push(item.title);
          localStorage.setItem("vision_ai_deleted_chats", JSON.stringify(deleted));
        }
      } catch {
        // ignore
      }
      return updated;
    });
  };

  const displayName = profileOverride?.name || user?.username || "Deva";
  const displayEmail = profileOverride?.email || user?.email || "pandu@gmail.com";
  const initials = displayName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "D";

  const isNewChat = pathname === "/";
  const isDashboard = pathname === "/dashboard";
  const isMemories = pathname.startsWith("/memories");
  const isKnowledge = pathname.startsWith("/knowledge");

  const filteredHistory = searchQuery.trim()
    ? moduleHistory.filter((item) =>
        item.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : moduleHistory;

  return (
    <div className={`unified-app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      {/* Persistent Left Dark Sidebar */}
      <aside className={`unified-sidebar ${sidebarCollapsed ? "collapsed" : ""}`} aria-label="Sidebar">
        {/* Row 1: Collapsed → only Toggle icon. Expanded → Brand + Search + Toggle */}
        <div className="sidebar-top-header">
          {/* Brand link — hidden when collapsed */}
          {!sidebarCollapsed && (
            <Link href="/" className="sidebar-brand-clean-link" onClick={handleNewChat} title="Vision AI">
              <div className="brand-mascot-glow">
                <RobotMascot size={28} />
              </div>
              <div className="brand-title-line">
                <span className="brand-white">Vision </span>
                <span className="brand-green">AI</span>
              </div>
            </Link>
          )}

          <div className={`sidebar-header-actions ${sidebarCollapsed ? "collapsed-actions" : ""}`}>
            {/* Search Icon Button — always visible */}
            <button
              type="button"
              className="sidebar-icon-action-btn"
              onClick={(e) => {
                e.stopPropagation();
                setSearchModalOpen(true);
              }}
              title="Search chats (Ctrl+K)"
              aria-label="Search"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </button>

            {/* Toggle Sidebar Icon Button: PanelLeftClose to collapse, PanelLeftOpen to expand */}
            <button
              type="button"
              className="sidebar-icon-action-btn"
              onClick={(e) => {
                e.stopPropagation();
                setSidebarCollapsed(!sidebarCollapsed);
              }}
              title={sidebarCollapsed ? "PanelLeftOpen – expand sidebar" : "PanelLeftClose – collapse sidebar"}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed ? (
                /* PanelLeftOpen: sidebar collapsed, chevron points right to open */
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="18" height="18" x="3" y="3" rx="2" />
                  <path d="M9 3v18" />
                  <path d="m14 9 3 3-3 3" />
                </svg>
              ) : (
                /* PanelLeftClose: sidebar open, chevron points left to close */
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="18" height="18" x="3" y="3" rx="2" />
                  <path d="M9 3v18" />
                  <path d="m16 15-3-3 3-3" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {/* Top Navigation Group: New Chat + Modules (NO "MODULES" header text) */}
        <div className="sidebar-top-nav-group">
          {/* 1. New Chat Button: without selecting, background is transparent identical to Dashboard */}
          <button
            type="button"
            className={`sidebar-new-chat-btn-wide ${isNewChat ? "active-module" : ""}`}
            onClick={handleNewChat}
            title="Start new conversation"
          >
            <span className="sidebar-new-chat-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
            </span>
            {!sidebarCollapsed && <span className="sidebar-new-chat-label">New chat</span>}
          </button>

          {/* 2, 3, 4: Dedicated Module Links */}
          <div className="sidebar-integrated-modules">
            {/* Dashboard */}
            <Link
              href="/dashboard"
              className={`sidebar-nav-item module-item ${isDashboard ? "active-module" : ""}`}
              title="Dashboard"
            >
              <span className="module-icon">📊</span>
              {!sidebarCollapsed && <span className="module-nav-label">Dashboard</span>}
            </Link>

            {/* Memory Bank */}
            <Link
              href="/memories"
              className={`sidebar-nav-item module-item ${isMemories ? "active-module" : ""}`}
              title="Memory Bank"
            >
              <span className="module-icon">🧠</span>
              {!sidebarCollapsed && <span className="module-nav-label">Memory Bank</span>}
            </Link>

            {/* Knowledge RAG */}
            <Link
              href="/knowledge"
              className={`sidebar-nav-item module-item ${isKnowledge ? "active-module" : ""}`}
              title="Knowledge RAG"
            >
              <span className="module-icon">📄</span>
              {!sidebarCollapsed && <span className="module-nav-label">Knowledge RAG</span>}
            </Link>
          </div>

          {/* Divider between Modules and Recent Chats */}
          {!sidebarCollapsed && <div className="sidebar-divider" />}
        </div>

        {/* Recents Section: Full Height Smooth Scrolling (Matching Image 1 Reference) */}
        {!sidebarCollapsed && (
          <div className="sidebar-recents-section">
            <div className="sidebar-section-header">RECENT CHATS</div>
            <div className="recents-list-scrollable">
              {filteredHistory.map((item, idx) => (
                <div
                  key={item.id ? `${item.id}-${idx}` : `hist-${idx}`}
                  className="recent-history-row"
                  onClick={() => handleHistoryItemClick(item)}
                  title={item.title}
                  role="button"
                  tabIndex={0}
                >
                  <span className="recent-row-title">{item.title}</span>
                  <button
                    type="button"
                    className="recent-row-delete-btn"
                    onClick={(e) => handleDeleteRecentChat(e, item)}
                    title="Delete chat"
                    aria-label={`Delete ${item.title}`}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 6h18" />
                      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              ))}
              {filteredHistory.length === 0 && (
                <div className="recents-empty-hint">No matches found</div>
              )}
            </div>
          </div>
        )}

        {/* Professional User Profile Footer */}
        <div className="sidebar-bottom-footer" onClick={(e) => e.stopPropagation()}>
          {/* Professional Popover Menu */}
          {userMenuOpen && (
            <div className="user-popover-menu-pro" onClick={(e) => e.stopPropagation()}>
              <div className="popover-user-summary">
                <div className="popover-avatar-pro">{initials}</div>
                <div className="popover-user-info">
                  <div className="popover-user-name">{displayName}</div>
                  <div className="popover-user-email">{displayEmail}</div>
                </div>
              </div>
              <div className="popover-divider-pro" />

              <button
                type="button"
                className="user-popover-item-pro"
                onClick={() => {
                  setUserMenuOpen(false);
                  setProfileOpen(true);
                }}
              >
                <div className="popover-item-left">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <span>My Profile</span>
                </div>
              </button>

              <button
                type="button"
                className="user-popover-item-pro logout-item-pro"
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                }}
              >
                <div className="popover-item-left">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                  <span>Logout</span>
                </div>
              </button>
            </div>
          )}

          {/* User Profile Badge (Click to open menu) */}
          <div
            className={`user-profile-badge-pro ${userMenuOpen ? "active" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              setUserMenuOpen(!userMenuOpen);
            }}
            title={`${displayName} (${displayEmail})`}
          >
            <div className="avatar-circle-pro">{initials}</div>

            {!sidebarCollapsed && (
              <div className="user-profile-meta-pro">
                <span className="profile-name-pro">{displayName}</span>
                <span className="profile-email-pro">{displayEmail}</span>
              </div>
            )}

            {!sidebarCollapsed && (
              <div className="profile-more-btn-pro">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="12" r="2" />
                  <circle cx="19" cy="12" r="2" />
                  <circle cx="5" cy="12" r="2" />
                </svg>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content Area without Top Nav (Zero Header Text as requested) */}
      <div className="unified-main-content">
        <main className="unified-main-body">{children}</main>
      </div>

      {/* Search Modal Dialog matching Reference Image 3 */}
      {searchModalOpen && (
        <div className="search-modal-backdrop" onClick={() => setSearchModalOpen(false)}>
          <div className="search-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="search-modal-header">
              <div className="search-input-wrap">
                <input
                  type="text"
                  className="search-modal-input"
                  placeholder="Search..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                />
              </div>
              <button
                type="button"
                className="search-modal-close"
                onClick={() => setSearchModalOpen(false)}
                title="Close (Esc)"
              >
                ✕
              </button>
            </div>

            <div className="search-modal-subtitle">Recent chats</div>

            <div className="search-modal-list">
              {filteredHistory.map((item) => (
                <div
                  key={item.id}
                  className="search-modal-item"
                  onClick={() => handleHistoryItemClick(item)}
                  role="button"
                  tabIndex={0}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="search-modal-bubble-icon">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                  </svg>
                  <span className="search-modal-item-title">{item.title}</span>
                  <button
                    type="button"
                    className="recent-row-delete-btn search-delete-btn"
                    onClick={(e) => handleDeleteRecentChat(e, item)}
                    title="Delete chat"
                    aria-label={`Delete ${item.title}`}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 6h18" />
                      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              ))}
              {filteredHistory.length === 0 && (
                <div className="search-modal-empty">No chats found matching &ldquo;{searchQuery}&rdquo;</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Professional Profile Modal with Editability */}
      <ProfileModal
        isOpen={profileOpen}
        onClose={() => setProfileOpen(false)}
        user={{ ...user, username: displayName, email: displayEmail }}
      />
    </div>
  );
}
