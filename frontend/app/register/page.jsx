"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorBox } from "@/components/ui";
import { register } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// SVG Icons matching reference design
function RobotBrandIcon({ size = 42 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M9 19C9 10.7 15.7 4 24 4C32.3 4 39 10.7 39 19" stroke="#047857" strokeWidth="3.2" strokeLinecap="round" />
      <rect x="6" y="15" width="5" height="10" rx="2.5" fill="#059669" />
      <rect x="37" y="15" width="5" height="10" rx="2.5" fill="#059669" />
      <line x1="24" y1="4" x2="24" y2="10" stroke="#047857" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="24" cy="3.5" r="2.5" fill="#10b981" />
      <rect x="11" y="11" width="26" height="21" rx="8" fill="#0f172a" stroke="#10b981" strokeWidth="2.8" />
      <rect x="14.5" y="15" width="19" height="12" rx="5" fill="#064e3b" />
      <circle cx="19.5" cy="20.5" r="2.2" fill="#34d399" />
      <circle cx="28.5" cy="20.5" r="2.2" fill="#34d399" />
      <path d="M21 24C22.2 25.2 25.8 25.2 27 24" stroke="#34d399" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M39 24V27C39 29.5 37 31.5 34.5 31.5H31" stroke="#047857" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="30" cy="31.5" r="2" fill="#10b981" />
    </svg>
  );
}

function BrainFeatureIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04Z"/>
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04Z"/>
    </svg>
  );
}

function BookFeatureIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/>
      <path d="M6 6h10"/>
      <path d="M6 10h10"/>
      <path d="M6 14h7"/>
    </svg>
  );
}

function SparkFeatureIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

function MascotIllustration() {
  return (
    <div className="auth-mascot-wrapper" aria-hidden="true">
      <div className="auth-float-bubble bubble-idea">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 18h6"/>
          <path d="M10 22h4"/>
          <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>
        </svg>
      </div>

      <div className="auth-float-bubble bubble-chat">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#047857" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          <line x1="8" y1="9" x2="16" y2="9"/>
          <line x1="8" y1="13" x2="13" y2="13"/>
        </svg>
      </div>

      <svg width="170" height="135" viewBox="0 0 200 160" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="100" cy="148" rx="65" ry="9" fill="rgba(4, 120, 87, 0.08)" />
        <path d="M72 105C72 94 80 87 90 87H110C120 87 128 94 128 105V132H72V105Z" fill="#f8fafc" stroke="#047857" strokeWidth="3" />
        <path d="M88 98H112" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" />
        <rect x="73" y="44" width="54" height="40" rx="14" fill="#ffffff" stroke="#047857" strokeWidth="3.2" />
        <path d="M68 62C68 47 82 34 100 34C118 34 132 47 132 62" stroke="#047857" strokeWidth="3.2" strokeLinecap="round" />
        <rect x="63" y="55" width="7" height="14" rx="3.5" fill="#059669" />
        <rect x="130" y="55" width="7" height="14" rx="3.5" fill="#059669" />
        <line x1="100" y1="34" x2="100" y2="24" stroke="#047857" strokeWidth="2.8" strokeLinecap="round" />
        <circle cx="100" cy="22" r="4" fill="#10b981" />
        <rect x="80" y="51" width="40" height="24" rx="8" fill="#064e3b" />
        <circle cx="91" cy="62" r="3.8" fill="#34d399" />
        <circle cx="109" cy="62" r="3.8" fill="#34d399" />
        <path d="M96 68C98 70 102 70 104 68" stroke="#34d399" strokeWidth="2" strokeLinecap="round" />
        <path d="M72 110L94 125" stroke="#047857" strokeWidth="5.5" strokeLinecap="round" />
        <path d="M128 110L108 125" stroke="#047857" strokeWidth="5.5" strokeLinecap="round" />
        <path d="M82 114L100 92L148 100L132 124L82 114Z" fill="#1e293b" stroke="#047857" strokeWidth="2.5" />
        <path d="M116 103L118 108L123 110L118 112L116 117L114 112L109 110L114 108Z" fill="#34d399" />
        <path d="M80 125L134 125L128 132H75L80 125Z" fill="#64748b" />
      </svg>
    </div>
  );
}

function UserBadgeIcon() {
  return (
    <div className="auth-lock-badge" aria-hidden="true">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    </div>
  );
}

function MailIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function LockInputIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

export default function RegisterPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email")).trim();
    const password = String(data.get("password"));
    if (password !== data.get("confirm")) {
      setError(new Error("Passwords don't match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register(email, String(data.get("username")).trim(), password);
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <div className="auth-split-layout">
        {/* LEFT COLUMN: Hero showcase */}
        <section className="auth-hero-showcase">
          <div className="auth-brand-header">
            <RobotBrandIcon size={46} />
            <div className="auth-brand-text">
              <span className="auth-brand-sub">Vision</span>
              <span className="auth-brand-main"> AI</span>
            </div>
          </div>

          <h1 className="auth-hero-headline">
            Your Intelligent Assistant for Smarter Decisions
          </h1>

          <div className="auth-hero-taglines">
            <p className="auth-tagline-lead">Remember. Retrieve. Assist.</p>
            <p className="auth-tagline-sub">Powered by Memory Bank and Knowledge RAG</p>
          </div>

          <div className="auth-feature-list">
            <div className="auth-feature-card">
              <div className="auth-feature-icon icon-brain">
                <BrainFeatureIcon />
              </div>
              <div className="auth-feature-content">
                <h3>Memory Bank</h3>
                <p>Save and recall your preferences and goals</p>
              </div>
            </div>

            <div className="auth-feature-card">
              <div className="auth-feature-icon icon-book">
                <BookFeatureIcon />
              </div>
              <div className="auth-feature-content">
                <h3>Knowledge RAG</h3>
                <p>Get accurate answers from your documents</p>
              </div>
            </div>

            <div className="auth-feature-card">
              <div className="auth-feature-icon icon-spark">
                <SparkFeatureIcon />
              </div>
              <div className="auth-feature-content">
                <h3>Smart Assistance</h3>
                <p>Personalized, contextual and always helpful</p>
              </div>
            </div>
          </div>

          <MascotIllustration />
        </section>

        {/* RIGHT COLUMN: Elevated Registration Card */}
        <section className="auth-form-column">
          <form className="card auth-card" method="post" onSubmit={submit}>
            <UserBadgeIcon />

            <h2 className="auth-card-title">Create Account</h2>
            <p className="auth-card-subtitle">Sign up to start your Vision AI journey</p>

            <ErrorBox error={error} />

            <div className="auth-input-group">
              <label htmlFor="reg-email" className="auth-field-label">Email Address</label>
              <div className="auth-input-wrapper">
                <span className="auth-input-prefix"><MailIcon /></span>
                <input id="reg-email" name="email" type="email" aria-label="Email" autoComplete="email" placeholder="you@example.com" required />
              </div>
            </div>

            <div className="auth-input-group">
              <label htmlFor="reg-username" className="auth-field-label">Username</label>
              <div className="auth-input-wrapper">
                <span className="auth-input-prefix"><UserIcon /></span>
                <input id="reg-username" name="username" minLength={2} maxLength={100} autoComplete="nickname" placeholder="Choose a username" required />
              </div>
            </div>

            <div className="auth-input-group">
              <label htmlFor="reg-password" className="auth-field-label">
                Password <span className="auth-label-opt">(10+ chars)</span>
              </label>
              <div className="auth-input-wrapper">
                <span className="auth-input-prefix"><LockInputIcon /></span>
                <input id="reg-password" name="password" type="password" minLength={10} maxLength={128} autoComplete="new-password" placeholder="Create strong passphrase" required />
              </div>
            </div>

            <div className="auth-input-group">
              <label htmlFor="reg-confirm" className="auth-field-label">Repeat password</label>
              <div className="auth-input-wrapper">
                <span className="auth-input-prefix"><LockInputIcon /></span>
                <input id="reg-confirm" name="confirm" type="password" autoComplete="new-password" placeholder="Confirm your password" required />
              </div>
            </div>

            <button type="submit" className="primary auth-submit-btn" disabled={busy}>
              <span>{busy ? "Creating…" : "Create account"}</span>
            </button>

            <p className="auth-footer-prompt">
              Already registered? <Link href="/login" className="auth-action-link">Log in</Link>
            </p>
          </form>
        </section>
      </div>
    </main>
  );
}
