// Vitest runs the frontend tests in Node with jsdom (a simulated browser DOM).
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.js"],
    include: ["tests/**/*.test.{js,jsx}"],
    coverage: {
      provider: "v8",
      include: ["lib/**", "components/**"],
      // Pages are covered by the Playwright E2E tests (a real browser), not by jsdom.
      reporter: ["text-summary", "text", "html"],
      thresholds: { lines: 80, functions: 75, branches: 70, statements: 80 },
    },
  },
});
