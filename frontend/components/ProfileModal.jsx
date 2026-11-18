"use client";
// Professional Profile Modal with Editability for Vision AI

import { useEffect, useState } from "react";

export default function ProfileModal({ isOpen, onClose, user }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("Full Stack Developer");
  const [bio, setBio] = useState("AI enthusiast & full-stack engineer building autonomous agents.");
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setSavedSuccess(false);
      try {
        const stored = localStorage.getItem("vision_ai_profile");
        if (stored) {
          const parsed = JSON.parse(stored);
          setName(parsed.name || user?.username || "Deva");
          setEmail(parsed.email || user?.email || "pandu@gmail.com");
          setRole(parsed.role || "Full Stack Developer");
          setBio(parsed.bio || "AI enthusiast & full-stack engineer building autonomous agents.");
          return;
        }
      } catch {}
      setName(user?.username || "Deva");
      setEmail(user?.email || "pandu@gmail.com");
    }
  }, [isOpen, user]);

  if (!isOpen) return null;

  const handleSave = (e) => {
    e.preventDefault();
    const updated = {
      name: name.trim() || user?.username || "Deva",
      email: email.trim() || user?.email || "pandu@gmail.com",
      role: role.trim() || "Full Stack Developer",
      bio: bio.trim(),
    };

    try {
      localStorage.setItem("vision_ai_profile", JSON.stringify(updated));
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("vision-profile-updated", { detail: updated }));
      }
    } catch {}

    setSavedSuccess(true);
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 900);
  };

  const initials = (name.trim() || "Deva")
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="profile-modal-backdrop" onClick={onClose}>
      <div className="profile-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="profile-modal-header">
          <div className="profile-header-title-wrap">
            <div className="profile-header-icon-box">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </div>
            <div>
              <h3 className="profile-modal-title">My Profile</h3>
              <p className="profile-modal-subtitle">Manage your personal credentials & preferences</p>
            </div>
          </div>
          <button type="button" className="profile-modal-close" onClick={onClose} title="Close (Esc)">
            ✕
          </button>
        </div>

        {/* Profile Card Banner */}
        <div className="profile-banner-card">
          <div className="profile-avatar-large">{initials}</div>
          <div className="profile-banner-info">
            <div className="profile-banner-name">{name || "Deva"}</div>
            <div className="profile-banner-email">{email || "pandu@gmail.com"}</div>
            <div className="profile-badge-row">
              <span className="profile-status-pill">
                <span className="profile-status-dot" /> Verified Account
              </span>
              <span className="profile-role-pill">{role}</span>
            </div>
          </div>
        </div>

        {/* Editable Form */}
        <form onSubmit={handleSave} className="profile-edit-form">
          <div className="profile-form-group">
            <label className="profile-form-label" htmlFor="profile-name">
              Full Name / Display Name
            </label>
            <input
              id="profile-name"
              type="text"
              className="profile-form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Deva Raj"
              required
            />
          </div>

          <div className="profile-form-group">
            <label className="profile-form-label" htmlFor="profile-email">
              Email Address
            </label>
            <input
              id="profile-email"
              type="email"
              className="profile-form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. user@example.com"
              required
            />
          </div>

          <div className="profile-form-group">
            <label className="profile-form-label" htmlFor="profile-role">
              Professional Role
            </label>
            <input
              id="profile-role"
              type="text"
              className="profile-form-input"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g. Full Stack Developer / AI Engineer"
            />
          </div>

          <div className="profile-form-group">
            <label className="profile-form-label" htmlFor="profile-bio">
              Bio / Objective
            </label>
            <textarea
              id="profile-bio"
              rows={2}
              className="profile-form-input profile-form-textarea"
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="Brief overview of your focus & expertise..."
            />
          </div>

          {/* Action Row */}
          <div className="profile-actions-row">
            {savedSuccess ? (
              <div className="profile-saved-toast">
                ✓ Changes saved successfully!
              </div>
            ) : <div />}

            <div className="profile-btn-group">
              <button type="button" className="profile-btn-cancel" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="profile-btn-save">
                Save Changes
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
