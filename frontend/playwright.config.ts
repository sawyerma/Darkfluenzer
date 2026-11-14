import { defineConfig } from "@playwright/test";

// Browser-Smoke gegen den gebauten Stand (vite preview, Vite-Standardport).
export default defineConfig({
  testDir: "tests",
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4173" },
  webServer: {
    command: "npx vite preview --host 127.0.0.1 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
});
