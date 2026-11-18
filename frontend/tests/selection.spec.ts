import { expect, test } from "@playwright/test";

// Automatische Prüfung und Auswahl (SP5 Schritt 7): ohne qualifizierte Schwellen steht am
// Kandidaten „Prüfung nicht qualifiziert, Freigabe durch Betreiber“, Karte AUSWAHL DURCH
// BETREIBER, die Auswahl bleibt beim Betreiber. Testdaten: scratchpad/sp5s7/seed_selection.py.

test("Auswahl: Prüfung nicht qualifiziert, Betreiber wählt", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Auswahl");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  const card = log.locator(".g-event", { hasText: "ANGEBOT · Foto · 20,00 € (Auswahl" }).last();
  await expect(card).toContainText("Prüfung nicht qualifiziert, Freigabe durch Betreiber");
  await expect(log.locator(".g-event", { hasText: "AUSWAHL DURCH BETREIBER" }).last()).toBeVisible();
  await card.screenshot({ path: "test-results/sp5s7-auswahl.png" });
  expect(errors).toEqual([]);
});
