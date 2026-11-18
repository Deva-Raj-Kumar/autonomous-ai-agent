// Component tests: what the user SEES and DOES (Testing Library queries by role/text).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ApprovalPanel from "@/components/ApprovalPanel";
import Markdown from "@/components/Markdown";
import PlanSteps from "@/components/PlanSteps";
import RunHistory from "@/components/RunHistory";
import { safeNextPath } from "@/lib/auth";

const TASKS = [
  { id: "t2", title: "Email the report", tool: "send_email", description: "Send to my mentor",
    arguments: { to: ["mentor@example.com"], subject: "AI jobs", body: "Report attached" } },
  { id: "t3", title: "Run analysis code", tool: "python_exec", description: "",
    arguments: { code: "print(sum([45000, 52000]) / 2)" } },
];

describe("ApprovalPanel: approve what you see", () => {
  it("shows the exact arguments that will run", () => {
    render(<ApprovalPanel tasks={TASKS} onDecide={vi.fn()} />);

    expect(screen.getByTestId("arguments-t2")).toHaveTextContent("mentor@example.com");
    expect(screen.getByTestId("arguments-t3")).toHaveTextContent("print(sum([45000, 52000]) / 2)");
  });

  it("selects nothing by default: submitting rejects everything", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel tasks={TASKS} onDecide={onDecide} />);

    await userEvent.click(screen.getByRole("button", { name: "Reject all" }));

    expect(onDecide).toHaveBeenCalledWith([]);
  });

  it("sends only the ticked tasks", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel tasks={TASKS} onDecide={onDecide} />);

    await userEvent.click(screen.getByRole("checkbox", { name: /Email the report/ }));
    await userEvent.click(screen.getByRole("button", { name: "Approve 1, reject 1" }));

    expect(onDecide).toHaveBeenCalledWith(["t2"]);
  });
});

describe("Markdown: untrusted model output", () => {
  it("shows raw HTML as text instead of running it", () => {
    const { container } = render(<Markdown>{'Hello <img src=x onerror="alert(1)"> <script>alert(2)</script>'}</Markdown>);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("removes javascript: links and isolates external ones", () => {
    render(<Markdown>{"[evil](javascript:alert(1)) and [docs](https://example.com)"}</Markdown>);

    expect(screen.getByText("evil").getAttribute("href") || "").not.toContain("javascript");
    const docs = screen.getByRole("link", { name: "docs" });
    expect(docs).toHaveAttribute("rel", "noopener noreferrer");
    expect(docs).toHaveAttribute("target", "_blank");
  });

  it("still renders normal Markdown", () => {
    render(<Markdown>{"# Report\n\n* **52,666.67** average"}</Markdown>);

    expect(screen.getByRole("heading", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("52,666.67").tagName).toBe("STRONG");
  });
});

describe("PlanSteps and RunHistory", () => {
  it("shows each task with its status, retries and errors", () => {
    const plan = { tasks: [
      { id: "t1", title: "Search jobs", tool: "web_search", status: "completed", attempts: 2, depends_on: [] },
      { id: "t2", title: "Write report", tool: "generate_report", status: "failed", attempts: 1, depends_on: ["t1"], error: "timeout" },
    ] };
    render(<PlanSteps plan={plan} />);

    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText("Completed")).toBeInTheDocument();
    expect(within(items[0]).getByText("2 attempts")).toBeInTheDocument();
    expect(within(items[1]).getByText("after t1")).toBeInTheDocument();
    expect(within(items[1]).getByText("timeout")).toBeInTheDocument();
  });

  it("highlights tool calls that raised security flags", () => {
    const history = { tool_logs: [
      { step_key: "t1", attempt: 1, tool_name: "web_search", status: "success", execution_time_ms: 812,
        output_data: { security_flags: ["role hijack"] } },
    ] };
    render(<RunHistory history={history} />);

    expect(screen.getByText(/Security flags: role hijack/)).toBeInTheDocument();
    expect(screen.getByText("812 ms")).toBeInTheDocument();
  });
});

describe("safeNextPath: no open redirects after login", () => {
  it.each([
    ["/runs/abc", "/runs/abc"],
    ["https://evil.example", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    [null, "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});
