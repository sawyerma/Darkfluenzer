import { expect, test } from "@playwright/test";

// Angebot (SP5 Schritt 2): Karte ANGEBOT mit Lieferzeit, angebotenen Zahlungswegen, gesperrtem
// Faktenblock (wörtlich gesendet) und Status „Zahlung in Prüfung · Frist ruht“ nach Gutscheincode.
// Testdaten: scratchpad/sp5s2/seed_offer.py (nur isolierter Testserver).

test("Angebot: Faktenblock, Lieferzeit, Zahlungswege, Zahlung in Prüfung", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Angebot");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  const card = log.locator(".g-event", { hasText: "ANGEBOT · Foto" }).last();
  await expect(card).toContainText("Zahlung in Prüfung · Frist ruht");
  await expect(card).toContainText("ruht seit");
  await expect(card).toContainText("ca. 15 min nach Zahlung");
  await expect(card).toContainText("Amazon-Gutschein");
  await expect(card).toContainText("20.00 EUR");
  await expect(card).toContainText("Strandfoto bei Sonnenuntergang"); // Wunsch = Prompt (SP5 Schritt 6)
  await card.getByText("Faktenblock").click();
  const facts = card.getByLabel("Faktenblock");
  await expect(facts).toContainText(/Angebot DF-O-\d+: Foto · 20,00 €/);
  await expect(facts).toContainText("Lieferzeit ca. 15 Minuten nach Zahlungseingang");
  await expect(log.locator(".g-event", { hasText: "ZAHLUNG IN PRÜFUNG · Gutschein erhalten" }).last()).toBeVisible();
  await card.screenshot({ path: "test-results/sp5s2-angebot.png" });
  expect(errors).toEqual([]);
});
