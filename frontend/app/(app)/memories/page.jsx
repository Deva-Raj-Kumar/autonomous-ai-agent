"use client";
// Vision AI - Dedicated Memory Bank Page
// 100% Dark Theme (Zero White) with Real Time Add, Delete, and Category Filters

import { useState } from "react";
import { EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const CATEGORIES = ["profile", "preference", "goal", "skill", "project", "other"];

export default function MemoriesPage() {
  const { data, error, loading, reload } = useApi("/memories?limit=200");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("preference");
  const [filterCategory, setFilterCategory] = useState("all");
  const [actionError, setActionError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const add = async (event) => {
    event.preventDefault();
    if (!content.trim() || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await apiFetch("/memories", {
        method: "POST",
        json: { content: content.trim(), category, importance: 3 },
      });
      setContent("");
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (memory) => {
    if (!window.confirm(`Forget "${memory.content}"?`)) return;
    setActionError(null);
    try {
      await apiFetch(`/memories/${memory.id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setActionError(err);
    }
  };

  const memoriesList = (data || []).filter(
    (m) => filterCategory === "all" || m.category === filterCategory
  );

  return (
    <div className="page">
      <div className="stack" style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* Header */}
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <span style={{ fontSize: "1.75rem" }}>🧠</span>
              <h1 style={{ color: "#ffffff", fontSize: "1.75rem", margin: 0 }}>Memory Bank</h1>
            </div>
            <p className="small muted" style={{ margin: "0.35rem 0 0" }}>
              Vision AI automatically saves and recalls your preferences, background, and goals across sessions.
            </p>
          </div>
          <span className="badge badge-good">{data?.length ?? 0} memories active</span>
        </div>

        {/* Add Memory Card */}
        <form className="card" onSubmit={add} style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <h3 style={{ color: "#ffffff", margin: 0 }}>Add a New Memory</h3>
          <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap" }}>
            <input
              aria-label="New memory"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              maxLength={300}
              placeholder="e.g. I prefer remote Python and AI engineering roles in Bengaluru"
              required
              style={{ flex: 1, minWidth: 260 }}
            />
            <select
              aria-label="Category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              style={{ width: "auto", minWidth: 140 }}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                </option>
              ))}
            </select>
            <button type="submit" className="primary" disabled={submitting || !content.trim()}>
              {submitting ? "Saving…" : "+ Add Memory"}
            </button>
          </div>
        </form>

        {/* Category Filters */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center" }}>
          <span className="small muted" style={{ marginRight: "0.25rem" }}>Filter:</span>
          <button
            type="button"
            className={`chip-btn ${filterCategory === "all" ? "active" : ""}`}
            onClick={() => setFilterCategory("all")}
          >
            All ({data?.length || 0})
          </button>
          {CATEGORIES.map((cat) => {
            const count = (data || []).filter((m) => m.category === cat).length;
            return (
              <button
                key={cat}
                type="button"
                className={`chip-btn ${filterCategory === cat ? "active" : ""}`}
                onClick={() => setFilterCategory(cat)}
              >
                {cat} ({count})
              </button>
            );
          })}
        </div>

        <ErrorBox error={actionError || error} />
        {loading && <Spinner label="Loading memory bank" />}
        {data && !memoriesList.length && (
          <EmptyState>No memories in this category yet. Add one above or chat with Vision AI.</EmptyState>
        )}

        {/* Memories List */}
        {memoriesList.length > 0 && (
          <div className="card" style={{ padding: "0.5rem" }}>
            <ul className="plain memory-list" style={{ margin: 0, padding: 0 }}>
              {memoriesList.map((memory) => (
                <li
                  key={memory.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "0.85rem 1rem",
                    borderBottom: "1px solid var(--border)",
                    gap: "1rem",
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: "0 0 0.3rem 0", color: "#f1f5f9", fontSize: "0.95rem" }}>
                      {memory.content}
                    </p>
                    <p className="small muted" style={{ margin: 0 }}>
                      <span className="badge badge-info" style={{ textTransform: "uppercase", fontSize: "0.68rem" }}>
                        {memory.category}
                      </span>{" "}
                      · importance {memory.importance}/5 · {formatTime(memory.updated_at || memory.created_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="delete-icon-btn"
                    onClick={() => remove(memory)}
                    title="Delete memory"
                    aria-label="Delete memory"
                  >
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 6h18" />
                      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
