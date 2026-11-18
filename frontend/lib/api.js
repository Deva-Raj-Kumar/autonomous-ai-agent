// The ONE place the dashboard talks to the backend.
//
// Tokens:
//   access token  -> kept in a module variable (memory). Never in localStorage: any
//                    injected script could read localStorage. Lost on reload, which is
//                    fine: we get a new one from the refresh cookie.
//   refresh token -> an httpOnly cookie set by the backend. This code can't read it,
//                    and doesn't need to: the browser sends it to /auth/session/refresh.

let accessToken = null;
let refreshInFlight = null;
let sessionExpiredHandler = () => {};

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

export function setAccessToken(token) {
  accessToken = token;
}

export function hasAccessToken() {
  return accessToken !== null;
}

/** Called when the session can't be renewed (the auth provider sends the user to /login). */
export function onSessionExpired(handler) {
  sessionExpiredHandler = handler;
}

/** FastAPI errors: {"detail": "text"} or, for validation, {"detail": [{loc, msg}, ...]}. */
export async function errorDetail(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((e) => `${e.loc?.slice(1).join(".") || "input"}: ${e.msg}`).join("; ");
    }
  } catch {
    // not JSON (e.g. the proxy couldn't reach the backend)
  }
  return response.status >= 500 ? "Server error. Is the backend running?" : `Request failed (${response.status})`;
}

/**
 * Get a new access token from the refresh cookie. SINGLE-FLIGHT, on two levels:
 *  - within this tab: concurrent callers share one request (refreshInFlight);
 *  - across tabs: the Web Locks API makes other tabs wait, then send the NEW cookie.
 * Why it matters: refresh tokens rotate. Two refreshes with the same cookie look exactly
 * like a stolen-token replay, and the backend would end the whole session.
 */
export function refreshAccessToken() {
  if (!refreshInFlight) {
    const refresh = async () => {
      const response = await fetch("/auth/session/refresh", { method: "POST", credentials: "same-origin" });
      if (!response.ok) {
        accessToken = null;
        return null;
      }
      accessToken = (await response.json()).access_token;
      return accessToken;
    };
    const locked = typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request("agent-token-refresh", refresh)
      : refresh();
    refreshInFlight = locked.finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/**
 * apiFetch("/agent/runs") -> parsed JSON. Adds the access token; on 401 refreshes ONCE
 * and retries; throws ApiError with the backend's message otherwise.
 */
export async function apiFetch(path, { method = "GET", json, form, signal } = {}) {
  const send = () => {
    const headers = {};
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (json !== undefined) headers["Content-Type"] = "application/json";
    return fetch(`/api${path}`, {
      method,
      headers,
      body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
      signal,
    });
  };

  let response = await send();
  if (response.status === 401) {
    if (await refreshAccessToken()) {
      response = await send(); // retry once with the new token
    } else {
      sessionExpiredHandler();
    }
  }
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  return response.status === 204 ? null : response.json();
}

// ------------------------------------------------------------- session calls
export async function login(email, password) {
  // OAuth2 password form: the field is called "username" but holds the email.
  const response = await fetch("/auth/session", {
    method: "POST",
    body: new URLSearchParams({ username: email, password }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  accessToken = (await response.json()).access_token;
}

export async function logout() {
  try {
    await fetch("/auth/session", { method: "DELETE", credentials: "same-origin" });
  } finally {
    accessToken = null; // forget the token even if the server is unreachable
  }
}

export function register(email, username, password) {
  return apiFetch("/auth/register", { method: "POST", json: { email, username, password } });
}

export async function googleLogin(email = null, username = null) {
  const response = await fetch("/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, username }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  accessToken = (await response.json()).access_token;
}

export async function resetPassword(email, newPassword) {
  const response = await fetch("/api/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, new_password: newPassword }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  accessToken = (await response.json()).access_token;
}

function triggerBlobDownload(blob, filename) {
  if (typeof window === "undefined") return;
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
}

export async function downloadFile(filename) {
  const url = `/api/agent/reports/${encodeURIComponent(filename)}/download`;
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let response = await fetch(url, { headers });
  if (response.status === 401) {
    if (await refreshAccessToken()) {
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
      response = await fetch(url, { headers });
    } else {
      sessionExpiredHandler();
    }
  }
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  const blob = await response.blob();
  triggerBlobDownload(blob, filename);
}

