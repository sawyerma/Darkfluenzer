import { expect, test } from "@playwright/test";

// Einstellungen → Kanäle (SP2 Schritt 9a): je Kanalkonto Kürzel, Betriebsart, Transport und die
// Influencerin des Kontos (Befehl 40 additiv); bleibt nach dem Neuladen.

test("Einstellungen: Kanalkonten mit Kürzel, Betriebsart und Influencerin (nur lesend)", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#einstellungen");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const card = page.locator(".g-card", { hasText: "Kanäle" });
  const accounts = card.locator(".g-account-line");
  if ((await accounts.count()) > 0) {
    await expect(accounts.first().locator("small").first()).toHaveText(/^Konto \S+ · (Produktion|Kundentest|Aus) · (tdlib|graph|business_bot)$/);
    await expect(accounts.first().locator("select option").first()).toHaveText("Keine Influencerin");
  }
  expect(errors).toEqual([]);
});

test("Einstellungen: Influencerin einem Kanalkonto zuordnen, nach Neuladen erhalten", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ordnet zu – nur isolierter Testserver mit Testkonto (DF_BASE_URL)");
  await page.goto("/#einstellungen");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const select = page.getByLabel(/^Influencerin des Kontos /).first();
  const options = await select.locator("option").allTextContents();
  expect(options.length).toBeGreaterThan(1); // Testinfluencerin vorhanden
  const target = options[options.length - 1] ?? "";
  await select.selectOption({ label: target });
  await expect(page.getByRole("status").filter({ hasText: "Influencerin zugeordnet." })).toBeVisible();
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.getByLabel(/^Influencerin des Kontos /).first().locator("option:checked")).toHaveText(target);
  await page.getByLabel(/^Influencerin des Kontos /).first().selectOption({ value: "0" });
  await expect(page.getByLabel(/^Influencerin des Kontos /).first()).toHaveValue("0");
});
