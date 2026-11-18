import { expect, test } from "@playwright/test";

// Default-Kette (SP1 Schritt 5): jede Kloner-Karte zeigt ihren Zustand als Marke, dazu steht die
// Chat-Antwort im Verlauf. Testdaten: scratchpad/sp1/seed_cloner_cards.py (nur isolierter Server).

test("Default: Kloner-Karten mit Zustand und Chat-Antwort", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testkarten nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const log = page.getByRole("log", { name: "Verlauf" });
  const rejected = log.locator(".g-event", { hasText: "Kein Workflow für clone" }).last();
  await expect(rejected.locator("strong").first()).toHaveText("INTERNER AUFTRAG · CLONE · TELEGRAM");
  await expect(rejected.locator(".g-badge")).toHaveText("ABGELEHNT");
  await expect(rejected.locator(".g-badge")).toHaveAttribute("data-tone", "bad");
  await expect(log.locator(".g-bubble", { hasText: "Kein Workflow für clone" }).last()).toBeVisible();
  const failed = log.locator(".g-event", { hasText: "Graph kaputt" }).last();
  await expect(failed.locator(".g-badge")).toHaveText("FEHLGESCHLAGEN");
  await failed.scrollIntoViewIfNeeded();
  await log.screenshot({ path: "test-results/sp1-kloner-karten.png" });
  expect(errors).toEqual([]);
});
