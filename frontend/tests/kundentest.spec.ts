import { expect, test } from "@playwright/test";

// Kundentest im Default-Chat (SP4 Schritt 8): Gruppe „Kundentest“ mit Sitzung, Schalter
// „Verzögerung wie Kunde“ (Befehl 37), „Zurücksetzen“ (Befehl 63) und Messwerten je Testantwort.

test("Default: Kundentest zurücksetzen, Verzögerung wie Kunde", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert den Default – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  const fold = aside.locator("details.g-fold", { hasText: "Kundentest" }).first();
  const hint = fold.locator(".g-fold-hint");
  await expect(hint).toHaveText(/^Sitzung \d+/);
  const before = Number(((await hint.textContent()) ?? "").match(/Sitzung (\d+)/)?.[1] ?? "0");
  await fold.locator("summary").click();
  await expect(fold.getByRole("table", { name: "Messwerte Kundentest" })).toBeVisible();
  await fold.getByRole("button", { name: "Zurücksetzen" }).click();
  // Wirkung statt Meldung: neue Revision baut das Formular neu auf
  await expect(hint).toHaveText(new RegExp(`^Sitzung ${before + 1}`));
  await expect(page.getByRole("log", { name: "Verlauf" }).locator(".g-event", { hasText: `KUNDENTEST ZURÜCKGESETZT · Sitzung ${before + 1}` })).toBeVisible();
  const delay = fold.getByLabel("Verzögerung wie Kunde");
  const was = await delay.isChecked();
  await delay.setChecked(!was);
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const again = page.getByRole("complementary", { name: "Kundensteuerung" }).locator("details.g-fold", { hasText: "Kundentest" }).first();
  await again.locator("summary").click();
  await expect(again.getByLabel("Verzögerung wie Kunde")).toBeChecked({ checked: !was });
  await again.screenshot({ path: "test-results/sp4-kundentest.png" });
  expect(errors).toEqual([]);
});
