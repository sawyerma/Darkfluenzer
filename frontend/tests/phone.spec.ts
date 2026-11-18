import { expect, test } from "@playwright/test";

// Ausnahmeweg Handy (SP5 Schritt 11): Gruppe „Freigabe vom Handy“ im Default-Kontakt mit Schalter
// und den drei Wörtern (Befehl 37), nach Neuladen erhalten.

test("Default: Freigabe vom Handy einschalten, Wörter ändern", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert den Default – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = () => page.getByRole("complementary", { name: "Kundensteuerung" });
  const fold = () => aside().locator("details.g-fold", { hasText: "Freigabe vom Handy" }).first();
  await fold().locator("summary").click();
  await fold().getByLabel("Vorschau wartender Aufträge an den Default (Telegram)").setChecked(true);
  await fold().getByLabel("Wort Freigeben").fill("Ja");
  await fold().getByLabel("Wort Neu").fill("Nochmal");
  await aside().getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(fold().locator(".g-fold-hint")).toHaveText("an · Ja · Nochmal · Erstatten");
  await fold().locator("summary").click();
  await expect(fold().getByLabel("Wort Freigeben")).toHaveValue("Ja");
  await fold().screenshot({ path: "test-results/sp5s11-handy.png" });
  // zurück auf die Startwerte
  await fold().getByLabel("Vorschau wartender Aufträge an den Default (Telegram)").setChecked(false);
  await fold().getByLabel("Wort Freigeben").fill("Freigeben");
  await fold().getByLabel("Wort Neu").fill("Neu");
  await aside().getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  expect(errors).toEqual([]);
});
