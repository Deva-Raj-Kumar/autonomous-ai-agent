"use client";
// Settings Modal for Autonomous AI Agent

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export default function SettingsModal({ isOpen, onClose, user, onLogout }) {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    if (isOpen) {
      apiFetch("/health")
        .then(setHealth)
        .catch(() => {});
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <div className="settings-title-wrap">
            <span className="settings-header-icon">⚙️</span>
            <div>
              <h3>System Settings</h3>
              <span className="small muted">Configure your Vision AI environment</span>
            </div>
          </div>
          <button type="button" className="tool-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="settings-body">
          {/* User Account Info */}
          <div className="settings-section">
            <h4 className="settings-section-title">User Account</h4>
            <div className="settings-card">
              <div className="settings-row">
                <span className="settings-label">Display Name</span>
                <span className="settings-val bold">{user?.username || "Deva Raj"}</span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Email</span>
                <span className="settings-val">{user?.email || "devarajkumartalasetty89@gmail.com"}</span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Role</span>
                <span className="badge badge-good">
                  {user?.is_admin ? "Administrator" : "Standard User"}
                </span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Subscription</span>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <span className="badge badge-info">Free Plan</span>
                  <button type="button" className="settings-upgrade-btn">
                    Upgrade to Pro
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* AI & Autonomous Agent Architecture */}
          <div className="settings-section">
            <h4 className="settings-section-title">Vision AI Core Architecture</h4>
            <div className="settings-card">
              <div className="settings-row">
                <span className="settings-label">LLM Provider</span>
                <span className="settings-val bold">
                  {health?.llm_provider?.toUpperCase() || "GEMINI"}
                </span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Active Model</span>
                <span className="settings-val bold" style={{ color: "var(--accent)" }}>
                  {health?.llm_model || "gemini-2.5-flash"}
                </span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Workflow Engine</span>
                <span className="settings-val">LangGraph ReAct Agent with Tool Execution</span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Knowledge Engine</span>
                <span className="settings-val">ChromaDB Local Vector Embeddings (RAG)</span>
              </div>
            </div>
          </div>

          {/* Security & Authentication */}
          <div className="settings-section">
            <h4 className="settings-section-title">Security & Credentials</h4>
            <div className="settings-card">
              <div className="settings-row">
                <span className="settings-label">Auth Algorithm</span>
                <span className="settings-val">JWT HS256 (30 min access expiration)</span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Password Hashing</span>
                <span className="settings-val">bcrypt (with legacy Argon2id fallback)</span>
              </div>
              <div className="settings-row">
                <span className="settings-label">Session Protection</span>
                <span className="badge badge-good">OAuth2 Bearer Tokens</span>
              </div>
            </div>
          </div>
        </div>

        <div className="settings-footer">
          <button type="button" className="settings-logout-btn" onClick={onLogout}>
            🚪 Log out
          </button>
          <button type="button" className="primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

