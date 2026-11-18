// Runs before every test file.
import "@testing-library/jest-dom/vitest"; // adds matchers like toBeInTheDocument()

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup(); // unmount what the test rendered
  vi.restoreAllMocks(); // undo vi.spyOn / mocked globals between tests
});
