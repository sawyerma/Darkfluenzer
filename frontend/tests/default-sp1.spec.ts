import { expect, type Page, test } from "@playwright/test";

// Default-Kette (SP1 Schritte 6, 7, 11, 12): Kandidaten je Bild, Chat-Wort zum Abbrechen,
// Betriebsart je Kanalkonto und Ausgabeprofil je Befehl – übernehmen, nach Neuladen erhalten.

async function panel(page: Page) {
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  await expect(aside.getByRole("heading", { name: "Default · Steuerung" })).toBeVisible();
  return aside;
}

test("Default: Kandidaten, Chat-Wort, Betriebsart, Ausgabeprofil (nur lesend)", async ({ page }) => {
  const aside = await panel(page);
  await expect(aside.getByLabel("Kandidaten je Bild")).toHaveAttribute("placeholder", /^Vorgabe \d+$/);
  await expect(aside.getByLabel("Chat-Wort Abbrechen")).toBeVisible();
  const modes = aside.getByLabel(/^Betriebsart /);
  if ((await modes.count()) > 0) await expect(modes.first().locator("option")).toHaveText(["Produktion", "Test", "Aus"]);
  await aside.locator("details.g-fold").nth(2).locator("summary").click();
  await expect(aside.getByLabel("Dauer animate (s)")).toBeVisible();
});

test("Default: SP1-Felder übernehmen und nach Neuladen erhalten", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert den Default – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let aside = await panel(page);
  await aside.getByLabel("Kandidaten je Bild").fill("2");
  await aside.getByLabel("Chat-Wort Abbrechen").fill("stopp");
  const mode = aside.getByLabel(/^Betriebsart .*telegram-test$/);
  await mode.selectOption("test");
  await aside.locator("details.g-fold").nth(2).locator("summary").click();
  await aside.getByLabel("Dauer animate (s)").fill("6");
  await expect(aside.locator(".g-fold-changed")).toHaveCount(3);
  await aside.screenshot({ path: "test-results/sp1-default-panel.png" });
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  await page.reload();
  aside = await panel(page);
  await expect(aside.getByLabel("Kandidaten je Bild")).toHaveValue("2");
  await expect(aside.getByLabel("Chat-Wort Abbrechen")).toHaveValue("stopp");
  await expect(aside.getByLabel(/^Betriebsart .*telegram-test$/)).toHaveValue("test");
  await expect(aside.locator("details.g-fold").first().locator(".g-fold-hint")).toContainText("Test");
  await aside.locator("details.g-fold").nth(2).locator("summary").click();
  await expect(aside.getByLabel("Dauer animate (s)")).toHaveValue("6");
  // zurücksetzen
  await aside.getByLabel("Kandidaten je Bild").fill("");
  await aside.getByLabel("Chat-Wort Abbrechen").fill("");
  await aside.getByLabel(/^Betriebsart .*telegram-test$/).selectOption("production");
  await aside.getByLabel("Dauer animate (s)").fill("");
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Einstellungen übernommen." })).toBeVisible();
  expect(errors).toEqual([]);
});
