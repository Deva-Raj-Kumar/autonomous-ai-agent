"use client";
// Interactive Knowledge RAG Tool Card invoked directly in the chat stream

import { useRef, useState } from "react";
import Markdown from "@/components/Markdown";
import { apiFetch } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Spinner, ErrorBox } from "./ui";

const ALLOWED_EXTS = [".pdf", ".md", ".txt", ".docx", ".csv", ".xlsx"];

function FileTypeBadge({ name }) {
  const ext = name?.split(".").pop()?.toUpperCase() || "DOC";
  return <span className="doc-type-badge">{ext}</span>;
}

export default function KnowledgeRAGTool({ initialQuery = "", onClose, autoFocusUpload = false }) {
  const { data: documents, error: docsError, loading: docsLoading, reload: reloadDocs } =
    useApi("/knowledge/documents");

  const [question, setQuestion] = useState(initialQuery);
  const [asking, setAsking] = useState(false);
  const [ragResult, setRagResult] = useState(null);
  const [askError, setAskError] = useState(null);

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const sampleQuestions = [
    "What salary does the AI engineer job offer?",
    "Summarize requirements and eligibility for freshers",
    "What are the top required Python and ML skills?",
  ];

  const handleAsk = async (queryText = null) => {
    const q = (queryText || question).trim();
    if (!q || asking) return;
    setAsking(true);
    setAskError(null);
    try {
      const res = await apiFetch("/knowledge/ask", {
        method: "POST",
        json: { question: q },
      });
      setRagResult(res);
    } catch (err) {
      setAskError(err);
    } finally {
      setAsking(false);
    }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setUploadSuccess(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await apiFetch("/knowledge/upload", {
        method: "POST",
        body: formData,
      });
      setUploadSuccess(`Indexed "${file.name}" successfully (${res.chunks} chunks created)!`);
      reloadDocs();
    } catch (err) {
      setUploadError(err);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (source) => {
    if (!window.confirm(`Delete "${source}" from vector store?`)) return;
    try {
      await apiFetch(`/knowledge/documents/${encodeURIComponent(source)}`, {
        method: "DELETE",
      });
      reloadDocs();
    } catch (err) {
      setUploadError(err);
    }
  };

  return (
    <div className="embedded-tool-card knowledge-tool-card">
      <div className="embedded-tool-header">
        <div className="embedded-tool-title">
          <span className="tool-header-icon cyan">📄</span>
          <div>
            <h3>Knowledge RAG</h3>
            <span className="tool-subtitle">ChromaDB semantic vector store & citations</span>
          </div>
        </div>
        <div className="tool-header-actions">
          <span className="badge badge-cyan">{documents?.length ?? 0} documents indexed</span>
          {onClose && (
            <button type="button" className="tool-close-btn" onClick={onClose} title="Close tool">
              ✕
            </button>
          )}
        </div>
      </div>

      <ErrorBox error={askError || uploadError || docsError} />

      {uploadSuccess && (
        <div className="tool-success-banner">
          <span>✓</span> {uploadSuccess}
        </div>
      )}

      {/* RAG Document Search Box */}
      <div className="rag-search-section">
        <form
          className="rag-search-bar"
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk();
          }}
        >
          <input
            type="text"
            className="rag-search-input"
            placeholder="Ask anything from your documents (e.g. salary, skills, requirements)..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button type="submit" className="rag-search-btn" disabled={asking || !question.trim()}>
            {asking ? "Searching..." : "🔍 Ask Docs"}
          </button>
        </form>

        <div className="rag-chips-row">
          <span className="rag-chips-label">Suggested:</span>
          {sampleQuestions.map((q, idx) => (
            <button
              key={idx}
              type="button"
              className="rag-chip-btn"
              onClick={() => {
                setQuestion(q);
                handleAsk(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>

        {/* Answer Output */}
        {ragResult && (
          <div className="rag-answer-box">
            <div className="rag-answer-header">
              <span className="rag-answer-badge">Answer</span>
              <span className="rag-citation-count">
                {ragResult.citations?.length || 0} citations referenced
              </span>
            </div>
            <div className="rag-answer-text">
              <Markdown content={ragResult.answer} />
            </div>

            {/* Citations List */}
            {ragResult.citations?.length > 0 && (
              <div className="rag-citations-container">
                <div className="rag-citations-title">Sources & Citations:</div>
                <div className="rag-citations-grid">
                  {ragResult.citations.map((cite, i) => (
                    <div key={i} className="citation-chip">
                      <span className="citation-num">[{i + 1}]</span>
                      <span className="citation-source">{cite.source}</span>
                      {cite.chunk !== undefined && (
                        <span className="citation-chunk">chunk #{cite.chunk}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Document Upload & Index Management */}
      <div className="rag-upload-section">
        <div
          className={`rag-dropzone ${isDragOver ? "dragover" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragOver(true);
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragOver(false);
            if (e.dataTransfer.files?.[0]) handleFileUpload(e.dataTransfer.files[0]);
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: "none" }}
            accept={ALLOWED_EXTS.join(",")}
            onChange={(e) => {
              if (e.target.files?.[0]) handleFileUpload(e.target.files[0]);
            }}
          />
          <div className="dropzone-content">
            <span className="dropzone-icon">📤</span>
            <div className="dropzone-text">
              <strong>{uploading ? "Ingesting document..." : "Click or drag & drop to upload"}</strong>
              <span>Supports PDF, Markdown (.md), TXT, DOCX, CSV, Excel (.xlsx)</span>
            </div>
          </div>
        </div>

        {/* Document List */}
        <div className="rag-docs-list-wrap">
          <div className="rag-docs-header">
            <span>Indexed Documents</span>
            <button type="button" className="refresh-mini-btn" onClick={reloadDocs}>
              ↻ Refresh
            </button>
          </div>

          {docsLoading && <Spinner label="Loading documents" />}

          {!docsLoading && documents?.length === 0 && (
            <p className="docs-empty-text">No documents in knowledge base yet. Upload one above!</p>
          )}

          {!docsLoading && documents?.length > 0 && (
            <div className="rag-docs-pills">
              {documents.map((doc) => (
                <div key={doc.source} className="rag-doc-pill">
                  <FileTypeBadge name={doc.source} />
                  <span className="rag-doc-name" title={doc.source}>
                    {doc.source}
                  </span>
                  <span className="rag-doc-chunks">{doc.chunk_count} chunks</span>
                  <button
                    type="button"
                    className="rag-doc-del-btn"
                    onClick={() => handleDelete(doc.source)}
                    title="Remove from index"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

