"use client";
// Interactive Memory Bank Tool Card invoked directly in the chat stream

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Spinner, ErrorBox } from "./ui";

const CATEGORIES = ["profile", "preference", "goal", "skill", "project", "other"];

export default function MemoryBankTool({ onClose }) {
  const { data, error, loading, reload } = useApi("/memories?limit=50");
  const [newContent, setNewContent] = useState("");
  const [category, setCategory] = useState("preference");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [filterCategory, setFilterCategory] = useState("all");

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!newContent.trim() || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await apiFetch("/memories", {
        method: "POST",
        json: { content: newContent.trim(), category, importance: 3 },
      });
      setNewContent("");
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleForget = async (id, text) => {
    if (!window.confirm(`Forget memory: "${text}"?`)) return;
    setActionError(null);
    try {
      await apiFetch(`/memories/${id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setActionError(err);
    }
  };

  const memoriesList = (data || []).filter(
    (m) => filterCategory === "all" || m.category === filterCategory
  );

  return (
    <div className="embedded-tool-card memory-tool-card">
      <div className="embedded-tool-header">
        <div className="embedded-tool-title">
          <span className="tool-header-icon pink">🧠</span>
          <div>
            <h3>Memory Bank</h3>
            <span className="tool-subtitle">Persistent long-term semantic memory</span>
          </div>
        </div>
        <div className="tool-header-actions">
          <span className="badge badge-pink">{data?.length ?? 0} memories stored</span>
          {onClose && (
            <button type="button" className="tool-close-btn" onClick={onClose} title="Close tool">
              ✕
            </button>
          )}
        </div>
      </div>

      <ErrorBox error={actionError || error} />

      {/* Add Memory Form */}
      <form className="memory-add-bar" onSubmit={handleAdd}>
        <input
          type="text"
          className="memory-add-input"
          placeholder="e.g. I prefer AI Engineer roles in Bengaluru or Hyderabad"
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          maxLength={300}
          required
        />
        <select
          className="memory-category-select"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c.charAt(0).toUpperCase() + c.slice(1)}
            </option>
          ))}
        </select>
        <button type="submit" className="memory-add-btn" disabled={submitting || !newContent.trim()}>
          {submitting ? "Saving..." : "+ Remember"}
        </button>
      </form>

      {/* Category Filter Chips */}
      <div className="memory-filter-row">
        <button
          type="button"
          className={`memory-filter-chip ${filterCategory === "all" ? "active" : ""}`}
          onClick={() => setFilterCategory("all")}
        >
          All ({data?.length || 0})
        </button>
        {CATEGORIES.map((cat) => {
          const count = (data || []).filter((m) => m.category === cat).length;
          if (count === 0 && filterCategory !== cat) return null;
          return (
            <button
              key={cat}
              type="button"
              className={`memory-filter-chip ${filterCategory === cat ? "active" : ""}`}
              onClick={() => setFilterCategory(cat)}
            >
              {cat} ({count})
            </button>
          );
        })}
      </div>

      {/* Memories List */}
      <div className="memory-list-container">
        {loading && <Spinner label="Loading memory bank" />}
        {!loading && memoriesList.length === 0 && (
          <div className="memory-empty-state">
            <span>🧠</span>
            <p>No memories stored in this category yet. Add one above or chat with the agent!</p>
          </div>
        )}
        {!loading &&
          memoriesList.map((mem) => (
            <div key={mem.id} className="memory-item-card">
              <div className="memory-item-left">
                <span className="memory-category-tag">{mem.category}</span>
                <p className="memory-text">{mem.content}</p>
                <span className="memory-meta">
                  Importance {mem.importance}/5 · {formatTime(mem.updated_at || mem.created_at)}
                </span>
              </div>
              <button
                type="button"
                className="memory-forget-btn"
                onClick={() => handleForget(mem.id, mem.content)}
                title="Forget this memory"
              >
                Forget
              </button>
            </div>
          ))}
      </div>
    </div>
  );
}

