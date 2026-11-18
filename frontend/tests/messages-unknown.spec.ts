import { expect, test } from "@playwright/test";

// Ungeklärter Versand (SP2 Schritt 6, SPEC-009): Sendung „Ergebnis unbekannt“ zeigt „Als gesendet
// markieren“ und „Erneut senden“ (mit zweiter Bestätigung); KI-Hinweis nach „fehlgeschlagen“
// erneut sendbar (Schritt 7). Testdaten: scratchpad/sp2s6/seed_unknown.py (nur isolierter Server).

test("Nachrichten: unbekannte Sendung entscheiden, KI-Hinweis erneut", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Unbekannt");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  const open = log.locator(".g-bubble", { hasText: "Ergebnis unbekannt" }).last();
  await expect(open).toContainText(/Offen \d+/);
  await expect(log.locator(".g-event", { hasText: "VERSAND UNGEKLÄRT" }).last()).toBeVisible();
  // erneut senden: erst Warnung, dann Bestätigung; ohne verbundenes Konto abgewiesen, nichts geändert
  await open.getByRole("button", { name: "Erneut senden" }).click();
  await expect(open.locator(".g-warn")).toHaveText("Kann doppelt ankommen");
  await open.getByRole("button", { name: "Trotzdem erneut senden" }).click();
  await expect(open.getByRole("status")).toContainText("nicht verbunden");
  await expect(open).toContainText("Ergebnis unbekannt");
  await open.getByRole("button", { name: "Abbrechen" }).click();
  await log.screenshot({ path: "test-results/sp2s6-unbekannt.png" });
  // als gesendet markieren: Status per Push, Knöpfe weg, Karte
  const text = (await open.locator("p").first().innerText()).trim();
  await open.getByRole("button", { name: "Als gesendet markieren" }).click();
  const done = log.locator(".g-bubble", { hasText: text }).last();
  await expect(done.locator("small").last()).toContainText("gesendet");
  await expect(done.getByRole("button", { name: "Als gesendet markieren" })).toHaveCount(0);
  await expect(log.locator(".g-event", { hasText: "Betreiber: als gesendet markiert" }).last()).toBeVisible();
  // KI-Hinweis fehlgeschlagen: erneut sendbar
  await expect(page.getByText("KI-Hinweis: fehlgeschlagen").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "KI-Hinweis erneut senden" }).first()).toBeVisible();
  expect(errors).toEqual([]);
});
