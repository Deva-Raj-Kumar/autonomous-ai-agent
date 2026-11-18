"use client";
// Vision AI - Dedicated Knowledge Base (RAG Engine) Page
// 100% Dark Theme (Zero White) with Document Upload, Vector Indexing & Semantic Question Answering

import { useRef, useState } from "react";
import Markdown from "@/components/Markdown";
import { EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { useApi } from "@/lib/useApi";

function FileFormatIcon({ filename }) {
  const ext = filename?.split(".").pop()?.toUpperCase() || "DOC";
  return (
    <div
      style={{
        width: 38,
        height: 38,
        borderRadius: 10,
        backgroundColor: "rgba(16, 185, 129, 0.15)",
        color: "#34d399",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 800,
        fontSize: "0.72rem",
        letterSpacing: "0.04em",
        border: "1.5px solid rgba(16, 185, 129, 0.3)",
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      {ext}
    </div>
  );
}

function AskDocuments() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const SUGGESTIONS = [
    "What salary does the AI engineer job offer?",
    "Summarize requirements and eligibility for freshers",
    "What are the top required Python and ML skills?",
  ];

  const handleAsk = async (queryToUse = null) => {
    const q = (queryToUse || question).trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(
        await apiFetch("/knowledge/ask", {
          method: "POST",
          json: { question: q },
        })
      );
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "1.25rem" }}>💬</span>
        <h2 style={{ margin: 0, color: "#ffffff" }}>Ask your documents</h2>
      </div>
      <p className="small muted" style={{ marginTop: 0, marginBottom: "1rem" }}>
        Ask any natural language question across all indexed knowledge files:
      </p>

      <form
        className="row-form"
        onSubmit={(e) => {
          e.preventDefault();
          handleAsk();
        }}
        style={{ display: "flex", gap: "0.65rem" }}
      >
        <input
          aria-label="Question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          minLength={2}
          maxLength={1000}
          placeholder="e.g. What salary does the AI engineer job offer?"
          required
          style={{ flex: 1 }}
        />
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Searching…" : "Ask"}
        </button>
      </form>

      {/* Suggested chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.85rem" }}>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQuestion(s);
              handleAsk(s);
            }}
            className="chip-btn"
          >
            💡 {s}
          </button>
        ))}
      </div>

      <ErrorBox error={error} />

      {answer && (
        <div className="answer" style={{ marginTop: "1.25rem" }}>
          <div style={{ background: "#111823", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 14, padding: "1.25rem", boxShadow: "0 4px 16px rgba(0,0,0,0.3)" }}>
            <h4 style={{ margin: "0 0 0.6rem 0", color: "#10b981", fontSize: "1rem" }}>Answer</h4>
            <div style={{ color: "#f1f5f9", fontSize: "0.95rem", lineHeight: 1.6 }}>
              <Markdown>{answer.answer}</Markdown>
            </div>
          </div>

          {answer.invalid_citations?.length > 0 && (
            <p className="error-text small" style={{ marginTop: "0.75rem", color: "#ef4444" }}>
              Warning: cites non-existent sources ({answer.invalid_citations.join(", ")}).
            </p>
          )}

          {answer.sources?.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <h4 style={{ margin: "0 0 0.5rem 0", fontSize: "0.9rem", color: "#94a3b8" }}>Retrieved Sources</h4>
              <ol className="sources" style={{ margin: 0, paddingLeft: "1.25rem" }}>
                {answer.sources.map((source, index) => (
                  <li
                    key={source.id || index}
                    className={answer.cited?.includes(index + 1) ? "cited" : undefined}
                    style={{ marginBottom: "0.6rem", color: "#cbd5e1" }}
                  >
                    <strong style={{ color: "#ffffff" }}>{source.source}</strong>
                    {source.page != null && ` (p. ${source.page})`}
                    <span className="small muted"> · relevance {source.score?.toFixed(2)}</span>
                    <p className="small" style={{ margin: "0.2rem 0 0 0", color: "#94a3b8" }}>
                      {source.text.slice(0, 240)}
                      {source.text.length > 240 ? "…" : ""}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function DocumentUploadCard({ onUploaded }) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setReport(null);

    const form = new FormData();
    form.append("file", file);

    try {
      const res = await apiFetch("/knowledge/upload", {
        method: "POST",
        body: form,
      });
      setReport(res);
      onUploaded();
    } catch (err) {
      setError(err);
    } finally {
      setUploading(false);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    setError(null);
    try {
      const res = await apiFetch("/knowledge/ingest", { method: "POST" });
      setReport(Array.isArray(res) ? res[0] : res);
      onUploaded();
    } catch (err) {
      setError(err);
    } finally {
      setReindexing(false);
    }
  };

  return (
    <section className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <span style={{ fontSize: "1.25rem" }}>📤</span>
          <h2 style={{ margin: 0, color: "#ffffff" }}>Upload Documents</h2>
        </div>
        <button
          type="button"
          onClick={handleReindex}
          disabled={reindexing || uploading}
          style={{
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 10,
            padding: "0.45rem 0.85rem",
            fontSize: "0.82rem",
            fontWeight: 600,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            color: "#f1f5f9",
          }}
        >
          <span>{reindexing ? "Re-indexing…" : "🔄 Re-index All"}</span>
        </button>
      </div>

      <p className="small muted" style={{ marginTop: 0, marginBottom: "1rem" }}>
        Upload job descriptions, resumes, technical specs, or markdown guides to vectorize and query:
      </p>

      {/* Drag & Drop Dropzone */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: dragActive ? "2px dashed #10b981" : "2px dashed rgba(255,255,255,0.18)",
          backgroundColor: dragActive ? "rgba(16, 185, 129, 0.1)" : "#0f1620",
          borderRadius: 16,
          padding: "2rem 1.5rem",
          textAlign: "center",
          cursor: "pointer",
          transition: "all 0.2s ease",
          position: "relative",
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.csv,.xlsx"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            handleFileUpload(f);
          }}
          style={{ display: "none" }}
        />

        <div style={{ width: 48, height: 48, borderRadius: "50%", background: "rgba(16, 185, 129, 0.15)", color: "#10b981", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 0.75rem auto", fontSize: "1.4rem" }}>
          📁
        </div>

        <p style={{ margin: "0 0 0.35rem 0", fontWeight: 700, color: "#ffffff", fontSize: "0.98rem" }}>
          {uploading ? "Uploading & chunking document…" : "Click to browse or drag & drop documents here"}
        </p>
        <span className="small muted">
          Supports PDF, DOCX, TXT, MD, CSV, Excel (max 10 MB). Automatically chunked and embedded in Chroma vector store.
        </span>
      </div>

      {uploading && (
        <div style={{ marginTop: "1rem" }}>
          <Spinner label="Extracting text, creating chunks & computing embeddings…" />
        </div>
      )}

      <ErrorBox error={error} />

      {/* Upload Success Report */}
      {report && (
        <div
          style={{
            marginTop: "1rem",
            padding: "0.85rem 1.15rem",
            background: "rgba(16, 185, 129, 0.12)",
            border: "1px solid rgba(16, 185, 129, 0.35)",
            borderRadius: 12,
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            fontSize: "0.88rem",
            color: "#a7f3d0",
          }}
        >
          <span style={{ fontSize: "1.1rem" }}>✅</span>
          <div>
            <strong>{report.source}</strong>: {report.status || "indexed"} ({report.chunks || 0} chunks generated)
            {report.detail && <span className="small muted"> · {report.detail}</span>}
          </div>
        </div>
      )}
    </section>
  );
}

function DocumentsList({ documents, loading, error, onDeleted }) {
  const [deleting, setDeleting] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const handleDelete = async (source) => {
    if (!confirm(`Remove "${source}" from the knowledge base?`)) return;
    setDeleting(source);
    setDeleteError(null);
    try {
      await apiFetch(`/knowledge/documents/${encodeURIComponent(source)}`, {
        method: "DELETE",
      });
      onDeleted();
    } catch (err) {
      setDeleteError(err);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <section className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <span style={{ fontSize: "1.25rem" }}>📚</span>
          <h2 style={{ margin: 0, color: "#ffffff" }}>Indexed Documents</h2>
        </div>
        {documents && (
          <span className="badge badge-good">
            {documents.length} files
          </span>
        )}
      </div>

      <ErrorBox error={error || deleteError} />
      {loading && <Spinner label="Loading documents" />}

      {documents && !documents.length && (
        <EmptyState>No documents indexed yet. Upload a file above to enable RAG.</EmptyState>
      )}

      {documents?.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.source}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      <FileFormatIcon filename={doc.source} />
                      <div>
                        <strong style={{ color: "#ffffff" }}>{doc.source}</strong>
                        {doc.title && <span className="small muted"> — {doc.title}</span>}
                      </div>
                    </div>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      className="delete-icon-btn"
                      onClick={() => handleDelete(doc.source)}
                      disabled={deleting === doc.source}
                      title={deleting === doc.source ? "Deleting…" : "Delete document"}
                      aria-label="Delete document"
                      style={{ marginLeft: "auto" }}
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 6h18" />
                        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                        <line x1="10" y1="11" x2="10" y2="17" />
                        <line x1="14" y1="11" x2="14" y2="17" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function KnowledgePage() {
  const { data: documents, error, loading, reload } = useApi("/knowledge/documents");

  return (
    <div className="page">
      <div className="stack" style={{ maxWidth: 960, margin: "0 auto" }}>
        <div className="row">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <span style={{ fontSize: "1.75rem" }}>📚</span>
              <h1 style={{ color: "#ffffff", fontSize: "1.75rem", margin: 0 }}>Knowledge RAG</h1>
            </div>
            <p className="small muted" style={{ margin: "0.35rem 0 0" }}>
              Upload your documents and query them with semantic retrieval & citations powered by ChromaDB.
            </p>
          </div>
        </div>

        <AskDocuments />
        <DocumentUploadCard onUploaded={reload} />
        <DocumentsList documents={documents} loading={loading} error={error} onDeleted={reload} />
      </div>
    </div>
  );
}
