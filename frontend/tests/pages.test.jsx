// Page-level behaviour with Next.js navigation and the auth context mocked.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = { replace: vi.fn(), push: vi.fn() };
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => searchParams,
  usePathname: () => "/runs/abc",
}));

const auth = { login: vi.fn(), logout: vi.fn(), user: null, status: "anonymous" };
vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => auth,
}));

const { default: LoginForm } = await import("@/components/LoginForm");
const { default: AppLayout } = await import("@/app/(app)/layout");
const { useApi } = await import("@/lib/useApi");

beforeEach(() => {
  router.replace.mockReset();
  auth.login.mockReset();
  searchParams = new URLSearchParams();
});

describe("LoginForm", () => {
  it("logs in and goes back to the page that asked for login", async () => {
    searchParams = new URLSearchParams("next=/runs/abc");
    auth.login.mockResolvedValue({ id: 1 });
    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "ravi@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(auth.login).toHaveBeenCalledWith("ravi@example.com", "correct horse battery staple");
    expect(router.replace).toHaveBeenCalledWith("/runs/abc");
  });

  it("ignores an external ?next= (open redirect)", async () => {
    searchParams = new URLSearchParams("next=https://evil.example/phish");
    auth.login.mockResolvedValue({ id: 1 });
    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "ravi@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(router.replace).toHaveBeenCalledWith("/");
  });

  it("shows the server's error and stays on the page", async () => {
    auth.login.mockRejectedValue(new Error("Incorrect email or password."));
    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "ravi@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(router.replace).not.toHaveBeenCalled();
  });
});

describe("logged-in layout", () => {
  it("sends anonymous visitors to login, remembering where they were", () => {
    auth.status = "anonymous";
    render(<AppLayout><p>secret page</p></AppLayout>);

    expect(router.replace).toHaveBeenCalledWith("/login?next=%2Fruns%2Fabc");
    expect(screen.queryByText("secret page")).toBeNull();
  });

  it("shows the page once authenticated", () => {
    auth.status = "authenticated";
    auth.user = { username: "ravi", is_admin: false };
    render(<AppLayout><p>secret page</p></AppLayout>);

    expect(screen.getByText("secret page")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("allows deleting a recent chat from the sidebar", async () => {
    auth.status = "authenticated";
    auth.user = { username: "ravi", is_admin: false };
    render(<AppLayout><p>secret page</p></AppLayout>);

    const chatTitle = screen.getByText("Nextjs Warning Explained");
    expect(chatTitle).toBeInTheDocument();

    const deleteBtn = screen.getByRole("button", { name: "Delete Nextjs Warning Explained" });
    await userEvent.click(deleteBtn);

    expect(screen.queryByText("Nextjs Warning Explained")).toBeNull();
  });
});

describe("useApi polling", () => {
  afterEach(() => vi.useRealTimers());

  function Probe({ path, refreshMs }) {
    const { data } = useApi(path, { refreshMs });
    return <p>{data ? `count ${data.count}` : "loading"}</p>;
  }

  it("polls while visible and pauses in a hidden tab", async () => {
    vi.useFakeTimers();
    let count = 0;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ count: ++count }))));
    let visibility = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);

    render(<Probe path="/agent/runs" refreshMs={1000} />);
    // One act() per interval, so React renders after each tick like a real browser.
    for (let i = 0; i < 2; i += 1) await act(() => vi.advanceTimersByTimeAsync(1000));
    const visibleCalls = fetch.mock.calls.length;
    visibility = "hidden";
    for (let i = 0; i < 5; i += 1) await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(visibleCalls).toBe(3); // first load + 2 polls
    expect(fetch.mock.calls.length).toBe(visibleCalls); // nothing while hidden
  });
});
