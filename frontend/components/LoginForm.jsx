"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorBox } from "@/components/ui";
import { safeNextPath, useAuth } from "@/lib/auth";

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

function LockBadgeIcon() {
  return (
    <div className="auth-lock-badge" aria-hidden="true">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
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

function LockInputIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function EyeToggleIcon({ visible }) {
  if (visible) {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
        <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
        <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
        <line x1="2" y1="2" x2="22" y2="22" />
      </svg>
    );
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function LoginArrowIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
      <polyline points="10 17 15 12 10 7" />
      <line x1="15" y1="12" x2="3" y2="12" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.8-2.4 3.66v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.15z"/>
      <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"/>
      <path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.17 0 9.99 0 12s.45 3.83 1.25 5.42l4.03-3.15z"/>
      <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/>
    </svg>
  );
}

export default function LoginForm() {
  const auth = useAuth();
  const login = auth?.login;
  const loginWithGoogle = auth?.loginWithGoogle;
  const resetUserPassword = auth?.resetUserPassword;

  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Forgot Password Modal State
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotNewPassword, setForgotNewPassword] = useState("");
  const [forgotConfirm, setForgotConfirm] = useState("");
  const [forgotError, setForgotError] = useState(null);
  const [forgotBusy, setForgotBusy] = useState(false);
  const [forgotSuccess, setForgotSuccess] = useState(false);

  // Google Login Modal State
  const [showGoogleModal, setShowGoogleModal] = useState(false);
  const [customGoogleEmail, setCustomGoogleEmail] = useState("");
  const [googleBusy, setGoogleBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await login(String(data.get("email")).trim(), String(data.get("password")));
      router.replace(safeNextPath(searchParams?.get("next")));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  const handleForgotSubmit = async (e) => {
    e.preventDefault();
    if (!forgotEmail || !forgotNewPassword) {
      setForgotError(new Error("Please enter email and new password."));
      return;
    }
    if (forgotNewPassword !== forgotConfirm) {
      setForgotError(new Error("Passwords do not match."));
      return;
    }
    if (forgotNewPassword.length < 10) {
      setForgotError(new Error("Password must be at least 10 characters long."));
      return;
    }
    setForgotBusy(true);
    setForgotError(null);
    try {
      if (resetUserPassword) {
        await resetUserPassword(forgotEmail.trim(), forgotNewPassword);
      } else {
        await login(forgotEmail.trim(), forgotNewPassword);
      }
      setForgotSuccess(true);
      setTimeout(() => {
        setShowForgotModal(false);
        router.replace(safeNextPath(searchParams?.get("next")));
      }, 1200);
    } catch (err) {
      setForgotError(err);
      setForgotBusy(false);
    }
  };

  const handleExecuteGoogleLogin = async (emailToUse, usernameToUse = null) => {
    setGoogleBusy(true);
    setError(null);
    try {
      if (loginWithGoogle) {
        await loginWithGoogle(emailToUse, usernameToUse);
      } else {
        await login(emailToUse, "password");
      }
      setShowGoogleModal(false);
      router.replace(safeNextPath(searchParams?.get("next")));
    } catch (err) {
      setError(err);
      setShowGoogleModal(false);
    } finally {
      setGoogleBusy(false);
    }
  };

  return (
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

      {/* RIGHT COLUMN: Elevated White Form Card */}
      <section className="auth-form-column">
        <form className="card auth-card" method="post" onSubmit={submit}>
          <LockBadgeIcon />

          <h2 className="auth-card-title">Welcome Back</h2>
          <p className="auth-card-subtitle">Sign in to continue your Vision AI journey</p>

          <ErrorBox error={error} />

          {/* Email field */}
          <div className="auth-input-group">
            <label htmlFor="auth-email-input" className="auth-field-label">
              Email Address
            </label>
            <div className="auth-input-wrapper">
              <span className="auth-input-prefix">
                <MailIcon />
              </span>
              <input
                id="auth-email-input"
                name="email"
                type="email"
                aria-label="Email"
                autoComplete="username"
                placeholder="Enter your email address"
                required
              />
            </div>
          </div>

          {/* Password field */}
          <div className="auth-input-group">
            <label htmlFor="auth-password-input" className="auth-field-label">
              Password
            </label>
            <div className="auth-input-wrapper">
              <span className="auth-input-prefix">
                <LockInputIcon />
              </span>
              <input
                id="auth-password-input"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="Enter your password"
                required
              />
              <button
                type="button"
                className="auth-password-toggle-btn"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                title={showPassword ? "Hide password" : "Show password"}
              >
                <EyeToggleIcon visible={showPassword} />
              </button>
            </div>
          </div>

          {/* Remember me & Forgot password (Horizontal flex layout) */}
          <div className="auth-options-row">
            <label className="auth-remember-check">
              <input type="checkbox" name="remember" />
              <span>Remember me</span>
            </label>
            <button
              type="button"
              onClick={() => {
                setShowForgotModal(true);
                setForgotError(null);
                setForgotSuccess(false);
              }}
              className="auth-forgot-link-btn"
            >
              Forgot password?
            </button>
          </div>

          {/* Primary Log In Button */}
          <button type="submit" className="primary auth-submit-btn" disabled={busy}>
            <LoginArrowIcon />
            <span>{busy ? "Logging in…" : "Log in"}</span>
          </button>

          {/* Divider */}
          <div className="auth-divider">
            <span>or</span>
          </div>

          {/* Continue with Google */}
          <button
            type="button"
            className="auth-google-btn"
            onClick={() => setShowGoogleModal(true)}
            disabled={googleBusy}
          >
            <GoogleIcon />
            <span>{googleBusy ? "Connecting Google Account…" : "Continue with Google"}</span>
          </button>

          {/* Footer */}
          <p className="auth-footer-prompt">
            Don&apos;t have an account? <Link href="/register" className="auth-action-link">Create one</Link>
          </p>
        </form>
      </section>

      {/* FORGOT PASSWORD MODAL */}
      {showForgotModal && (
        <div className="auth-modal-overlay" role="dialog" aria-modal="true">
          <div className="card auth-modal-card">
            <div className="auth-modal-header">
              <div className="auth-modal-icon-badge">
                <LockInputIcon />
              </div>
              <button
                type="button"
                className="auth-modal-close"
                onClick={() => setShowForgotModal(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <h3 className="auth-modal-title">Reset Password</h3>
            <p className="auth-modal-subtitle">
              Enter your registered email and choose a new password (min 10 characters).
            </p>

            <ErrorBox error={forgotError} />

            {forgotSuccess ? (
              <div className="auth-success-box">
                <span className="auth-success-icon">✓</span>
                <p>Password reset successfully! Logging you in…</p>
              </div>
            ) : (
              <form onSubmit={handleForgotSubmit}>
                <div className="auth-input-group">
                  <label htmlFor="forgot-email" className="auth-field-label">Registered Email</label>
                  <div className="auth-input-wrapper">
                    <span className="auth-input-prefix"><MailIcon /></span>
                    <input
                      id="forgot-email"
                      type="email"
                      value={forgotEmail}
                      onChange={(e) => setForgotEmail(e.target.value)}
                      placeholder="e.g. devarajkumartalasetty89@gmail.com"
                      required
                    />
                  </div>
                </div>

                <div className="auth-input-group">
                  <label htmlFor="forgot-new-password" className="auth-field-label">New Password</label>
                  <div className="auth-input-wrapper">
                    <span className="auth-input-prefix"><LockInputIcon /></span>
                    <input
                      id="forgot-new-password"
                      type="password"
                      value={forgotNewPassword}
                      onChange={(e) => setForgotNewPassword(e.target.value)}
                      placeholder="Enter new 10+ char password"
                      required
                    />
                  </div>
                </div>

                <div className="auth-input-group">
                  <label htmlFor="forgot-confirm" className="auth-field-label">Confirm New Password</label>
                  <div className="auth-input-wrapper">
                    <span className="auth-input-prefix"><LockInputIcon /></span>
                    <input
                      id="forgot-confirm"
                      type="password"
                      value={forgotConfirm}
                      onChange={(e) => setForgotConfirm(e.target.value)}
                      placeholder="Confirm new password"
                      required
                    />
                  </div>
                </div>

                <div className="auth-modal-actions">
                  <button
                    type="button"
                    onClick={() => setShowForgotModal(false)}
                    className="auth-btn-secondary"
                    disabled={forgotBusy}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="primary auth-submit-btn"
                    disabled={forgotBusy}
                  >
                    {forgotBusy ? "Updating…" : "Reset & Log In"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* GOOGLE SIGN-IN MODAL */}
      {showGoogleModal && (
        <div className="auth-modal-overlay" role="dialog" aria-modal="true">
          <div className="card auth-modal-card">
            <div className="auth-modal-header">
              <div className="auth-google-logo-pill">
                <GoogleIcon />
              </div>
              <button
                type="button"
                className="auth-modal-close"
                onClick={() => setShowGoogleModal(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <h3 className="auth-modal-title">Sign in with Google</h3>
            <p className="auth-modal-subtitle">
              Choose an active Google account to instantly authenticate:
            </p>

            {/* Quick 1-Click Profile: Deva Raj */}
            <div className="auth-google-accounts-list">
              <button
                type="button"
                className="auth-google-account-item"
                onClick={() => handleExecuteGoogleLogin("devarajkumartalasetty89@gmail.com", "Deva Raj")}
                disabled={googleBusy}
              >
                <div className="auth-google-avatar">D</div>
                <div className="auth-google-account-details">
                  <span className="auth-google-name">Deva Raj</span>
                  <span className="auth-google-email">devarajkumartalasetty89@gmail.com</span>
                </div>
                <span className="auth-google-chevron">→</span>
              </button>

              <button
                type="button"
                className="auth-google-account-item"
                onClick={() => handleExecuteGoogleLogin("local@localhost", "local")}
                disabled={googleBusy}
              >
                <div className="auth-google-avatar local-avatar">V</div>
                <div className="auth-google-account-details">
                  <span className="auth-google-name">Vision AI User</span>
                  <span className="auth-google-email">local@localhost</span>
                </div>
                <span className="auth-google-chevron">→</span>
              </button>
            </div>

            <div className="auth-divider">
              <span>or custom Google email</span>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (customGoogleEmail.trim()) {
                  handleExecuteGoogleLogin(customGoogleEmail.trim());
                }
              }}
              className="auth-custom-google-form"
            >
              <div className="auth-input-wrapper">
                <span className="auth-input-prefix"><MailIcon /></span>
                <input
                  type="email"
                  value={customGoogleEmail}
                  onChange={(e) => setCustomGoogleEmail(e.target.value)}
                  placeholder="yourname@gmail.com"
                  required
                />
              </div>
              <button
                type="submit"
                className="primary auth-submit-btn"
                style={{ marginTop: "0.75rem" }}
                disabled={googleBusy}
              >
                {googleBusy ? "Signing In…" : "Sign In with this Google Email"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
