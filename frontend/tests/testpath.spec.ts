import { expect, test } from "@playwright/test";

// Kundentest mit Bild (SP5 Schritt 12): Testauftrag im Default-Chat mit TEST-Kennzeichen,
// Testfreigabe statt Zahlung (Karte TESTFREIGABE, Status bezahlt), gesperrter Faktenblock;
// Einstellungen „Testfreigabe-Wort“ und „Testfreigabe automatisch“ nach Neuladen erhalten.
// Testdaten: scratchpad/sp5s12/seed_test_order.py (nur isolierter Testserver).

test("Kundentest: Testauftrag mit Testfreigabe, Einstellungen Testfreigabe", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert den Default – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const log = page.getByRole("log", { name: "Verlauf" });
  const card = log.locator(".g-event", { hasText: "TEST · ANGEBOT · Foto" }).last();
  await expect(card).toContainText("TEST (Testfreigabe statt Zahlung)");
  await expect(card).toContainText("Bezahlt · wartet auf Produktion");
  await expect(card).toContainText("min nach Testfreigabe");
  await card.getByText("Faktenblock").click();
  await expect(card.getByLabel("Faktenblock")).toContainText("Testfreigabe: „Cash“ senden");
  await expect(log.locator(".g-event", { hasText: /TESTFREIGABE · DF-O-\d+ · ohne Zahlung/ }).last()).toBeVisible();
  await card.screenshot({ path: "test-results/sp5s12-testauftrag.png" });
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  const fold = () => page.getByRole("complementary", { name: "Kundensteuerung" }).locator("details.g-fold", { hasText: "Kundentest" }).first();
  await fold().locator("summary").click();
  await fold().getByLabel("Testfreigabe-Wort (statt Zahlung)").fill("Kasse");
  await fold().getByLabel("Testfreigabe automatisch").setChecked(true);
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await fold().locator("summary").click();
  await expect(fold().getByLabel("Testfreigabe-Wort (statt Zahlung)")).toHaveValue("Kasse");
  await expect(fold().getByLabel("Testfreigabe automatisch")).toBeChecked();
  // zurück auf die Startwerte
  await fold().getByLabel("Testfreigabe-Wort (statt Zahlung)").fill("Cash");
  await fold().getByLabel("Testfreigabe automatisch").setChecked(false);
  await page.getByRole("complementary", { name: "Kundensteuerung" }).getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  expect(errors).toEqual([]);
});
