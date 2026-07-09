import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
// Registers Testing Library's extra matchers (toBeInTheDocument, …) with
// Vitest's expect for every test file.
import "@testing-library/jest-dom/vitest";

// Testing Library only auto-registers its DOM cleanup when test globals are
// enabled; we run with globals: false, so register it explicitly — otherwise
// rendered components accumulate across tests within a file.
afterEach(cleanup);
