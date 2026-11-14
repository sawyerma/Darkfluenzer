import { readFileSync } from "node:fs";
import { defineConfig } from "@playwright/test";

// Browser-Test gegen das echte Backend (darkfluenzer serve), das den gebauten Stand ausliefert.
// Host und Port stammen aus der einzigen Konfiguration local/config.toml ([server]).
const config = readFileSync(new URL("../local/config.toml", import.meta.url), "utf8");
const server = /^\[server\]$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(config)?.[1] ?? "";
const host = /^host\s*=\s*"([^"]+)"/m.exec(server)?.[1];
const port = /^port\s*=\s*(\d+)/m.exec(server)?.[1];
if (!host || !port) throw new Error("local/config.toml: [server] host/port fehlen");
const url = `http://${host}:${port}`;

export default defineConfig({
  testDir: "tests",
  testMatch: "*.spec.ts",
  reporter: "line",
  use: { baseURL: url },
  webServer: {
    command: "../local/.venv/bin/python -m darkfluenzer serve",
    url: `${url}/`,
    reuseExistingServer: true,
  },
});
