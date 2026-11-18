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
  await expect(select.locator("option").nth(1)).toBeAttached(); // STATE mit Influencerinnen da
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

test("Einstellungen: zwei Telegram-Konten mit je eigenem Zustand (SP2 Schritt 4)", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "zweites Telegram-Konto nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#einstellungen");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const card = page.locator(".g-card", { hasText: "Kanäle" });
  // zwei konfigurierte Konten; Seeds anderer Tests (SP4 Figuren) legen weitere Telegram-Konten an
  const telegram = card.locator(".g-stack").filter({ has: page.locator('.g-ptag[data-platform="telegram"]') });
  await expect(telegram.nth(1)).toBeVisible();
  const count = await telegram.count();
  // je Konto ein eigener Adapter: eigener Zustand statt „weiteres Konto“
  for (let i = 0; i < count; i++) {
    await expect(telegram.nth(i).locator(".g-account-line small")).toHaveText(/^Konto \S+ · /);
    await expect(telegram.nth(i)).toContainText("TDLib fehlt");
  }
  await expect(card).not.toContainText("weiteres Konto");
  const keys = await telegram.locator(".g-account-line small").allTextContents();
  expect(new Set(keys.map((k) => k.split(" · ")[0])).size).toBe(count);
  await card.screenshot({ path: "test-results/sp2s4-zwei-telegram-konten.png" });
  expect(errors).toEqual([]);
});
