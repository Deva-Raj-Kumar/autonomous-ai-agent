// lib/api.js: tokens, automatic refresh, single-flight, error messages.
// fetch is replaced by vi.fn() (the JavaScript counterpart of MagicMock).
import { beforeEach, describe, expect, it, vi } from "vitest";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let api;
let fetchMock;

beforeEach(async () => {
  vi.resetModules(); // fresh module = no access token left over from another test
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  api = await import("@/lib/api");
});

describe("apiFetch", () => {
  it("sends the access token and parses JSON", async () => {
    api.setAccessToken("token-1");
    fetchMock.mockResolvedValueOnce(json([{ run_id: "r1" }]));

    const runs = await api.apiFetch("/agent/runs");

    expect(runs).toEqual([{ run_id: "r1" }]);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/agent/runs");
    expect(options.headers.Authorization).toBe("Bearer token-1");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    api.setAccessToken("expired");
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Invalid or expired token." }, 401))
      .mockResolvedValueOnce(json({ access_token: "fresh", expires_in: 900 })) // the refresh
      .mockResolvedValueOnce(json({ id: 1 }));

    expect(await api.apiFetch("/auth/me")).toEqual({ id: 1 });

    expect(fetchMock.mock.calls[1][0]).toBe("/auth/session/refresh");
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe("Bearer fresh");
  });

  it("makes ONE refresh call for many requests failing at once", async () => {
    api.setAccessToken("expired");
    let refreshes = 0;
    fetchMock.mockImplementation(async (url, options) => {
      if (url === "/auth/session/refresh") {
        refreshes += 1;
        return json({ access_token: "fresh" });
      }
      return options.headers.Authorization === "Bearer fresh" ? json({ ok: true }) : json({ detail: "expired" }, 401);
    });

    await Promise.all([api.apiFetch("/a"), api.apiFetch("/b"), api.apiFetch("/c")]);

    // Rotation: a second refresh with the same cookie would look like token theft.
    expect(refreshes).toBe(1);
  });

  it("reports an expired session when the refresh fails", async () => {
    const expired = vi.fn();
    api.onSessionExpired(expired);
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Not authenticated." }, 401))
      .mockResolvedValueOnce(json({ detail: "Not logged in." }, 401));

    await expect(api.apiFetch("/memories")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    expect(api.hasAccessToken()).toBe(false);
  });

  it("turns FastAPI validation errors into readable text", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: [{ loc: ["body", "goal"], msg: "String should have at least 3 characters" }] }, 422));

    await expect(api.apiFetch("/agent/runs", { method: "POST", json: { goal: "x" } }))
      .rejects.toThrow("goal: String should have at least 3 characters");
  });

  it("explains a backend that is down", async () => {
    fetchMock.mockResolvedValueOnce(new Response("Internal Server Error", { status: 500 }));

    await expect(api.apiFetch("/agent/runs")).rejects.toThrow("Is the backend running?");
  });
});

describe("refreshAccessToken", () => {
  it("uses a cross-tab Web Lock when the browser has one", async () => {
    const request = vi.fn((_name, callback) => callback());
    vi.stubGlobal("navigator", { locks: { request } });
    fetchMock.mockResolvedValueOnce(json({ access_token: "fresh" }));

    expect(await api.refreshAccessToken()).toBe("fresh");
    expect(request).toHaveBeenCalledWith("agent-token-refresh", expect.any(Function));
  });
});

describe("session calls", () => {
  it("logs in with the OAuth2 form and keeps the token in memory only", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fetchMock.mockResolvedValueOnce(json({ access_token: "abc", token_type: "bearer", expires_in: 900 }));

    await api.login("ravi@example.com", "correct horse battery staple");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/auth/session");
    expect(options.body.get("username")).toBe("ravi@example.com");
    expect(api.hasAccessToken()).toBe(true);
    expect(setItem).not.toHaveBeenCalled(); // never localStorage / sessionStorage
  });

  it("forgets the token on logout even if the server is unreachable", async () => {
    api.setAccessToken("abc");
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(api.logout()).rejects.toThrow("Failed to fetch");
    expect(api.hasAccessToken()).toBe(false);
  });
});
