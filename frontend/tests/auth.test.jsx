// AuthProvider: silent login, login, logout and session expiry, with lib/api mocked.
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = { replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({
  refreshAccessToken: vi.fn(),
  apiFetch: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  onSessionExpired: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

const { AuthProvider, useAuth } = await import("@/lib/auth");
const { formatTime, isActive, prettyJson } = await import("@/lib/format");

function Probe() {
  const { status, user, login, logout } = useAuth();
  return (
    <div>
      <p>status: {status}</p>
      <p>user: {user?.username ?? "none"}</p>
      <button type="button" onClick={() => login("ravi@example.com", "pw")}>login</button>
      <button type="button" onClick={logout}>logout</button>
    </div>
  );
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  router.replace.mockReset();
});

describe("AuthProvider", () => {
  it("logs in silently when the refresh cookie is still valid", async () => {
    api.refreshAccessToken.mockResolvedValue("token");
    api.apiFetch.mockResolvedValue({ username: "ravi" });

    render(<AuthProvider><Probe /></AuthProvider>);

    expect(await screen.findByText("status: authenticated")).toBeInTheDocument();
    expect(screen.getByText("user: ravi")).toBeInTheDocument();
    expect(api.apiFetch).toHaveBeenCalledWith("/auth/me");
  });

  it("is anonymous without a valid cookie, or when the backend is down", async () => {
    api.refreshAccessToken.mockResolvedValueOnce(null);
    const { unmount } = render(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText("status: anonymous")).toBeInTheDocument();
    unmount();

    api.refreshAccessToken.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText("status: anonymous")).toBeInTheDocument();
  });

  it("login loads the user; logout forgets them and goes to /login", async () => {
    api.refreshAccessToken.mockResolvedValue(null);
    api.apiFetch.mockResolvedValue({ username: "ravi" });
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("status: anonymous");

    await act(() => screen.getByText("login").click());
    expect(await screen.findByText("user: ravi")).toBeInTheDocument();
    expect(api.login).toHaveBeenCalledWith("ravi@example.com", "pw");

    await act(() => screen.getByText("logout").click());
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.getByText("user: none")).toBeInTheDocument();
  });

  it("becomes anonymous when the API reports an expired session", async () => {
    api.refreshAccessToken.mockResolvedValue("token");
    api.apiFetch.mockResolvedValue({ username: "ravi" });
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("status: authenticated");

    const expired = api.onSessionExpired.mock.calls[0][0]; // the handler registered with lib/api
    act(() => expired());

    expect(screen.getByText("status: anonymous")).toBeInTheDocument();
  });

  it("refuses to be used outside the provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => {}); // React logs the thrown error
    expect(() => render(<Probe />)).toThrow("inside <AuthProvider>");
  });
});

describe("format helpers", () => {
  it("polls only runs that are still working", () => {
    expect(isActive({ status: "executing", running: true })).toBe(true);
    expect(isActive({ status: "planning", running: false })).toBe(true);
    expect(isActive({ status: "completed", running: false })).toBe(false);
    expect(isActive({ status: "waiting_approval", running: false })).toBe(false); // waits for a human
    expect(isActive(null)).toBe(false);
  });

  it("formats times and JSON defensively", () => {
    expect(formatTime("")).toBe("");
    expect(formatTime("not a date")).toBe("not a date");
    expect(formatTime("2026-11-09T11:41:21Z")).toMatch(/9|Nov/);
    expect(prettyJson(null)).toBe("{}");
    expect(prettyJson({ to: ["a@b.c"] })).toContain('"a@b.c"');
  });
});
