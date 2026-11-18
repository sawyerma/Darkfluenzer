import { readFileSync } from "node:fs";
import { defineConfig } from "@playwright/test";

// Browser-Test gegen das echte Backend (darkfluenzer serve), das den gebauten Stand ausliefert.
// Host und Port stammen aus der einzigen Konfiguration local/config.toml ([server]).
const config = readFileSync(new URL("../local/config.toml", import.meta.url), "utf8");
const server = /^\[server\]$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(config)?.[1] ?? "";
const host = /^host\s*=\s*"([^"]+)"/m.exec(server)?.[1];
const port = /^port\s*=\s*(\d+)/m.exec(server)?.[1];
if (!host || !port) throw new Error("local/config.toml: [server] host/port fehlen");
// DF_BASE_URL: isolierter Testserver (eigener DARKFLUENZER_ROOT) für schreibende Tests
const url = process.env.DF_BASE_URL ?? `http://${host}:${port}`;

export default defineConfig({
  testDir: "tests",
  testMatch: "*.spec.ts",
  reporter: "line",
  // schreibende Läufe gegen einen Testserver nacheinander (gemeinsamer Default, CAS)
  workers: process.env.DF_E2E_WRITE ? 1 : undefined,
  // echter Chrome (GUI-Auftrag 18.11.: Browser-E2E in Chrome)
  use: { baseURL: url, channel: "chrome" },
  webServer: {
    command: "../local/.venv/bin/python -m darkfluenzer serve",
    url: `${url}/`,
    reuseExistingServer: true,
  },
});
