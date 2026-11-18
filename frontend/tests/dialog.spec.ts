import { expect, test } from "@playwright/test";

// Dialogbetrieb (SP4 Schritt 6): Modus je Konversation, KI-Entwurf bearbeitbar mit Senden und
// Verwerfen, geplante Antwort mit Sendezeit, „Jetzt senden“ und „Zurückhalten“, stornierte bleibt
// sichtbar; Schalter Text-KI und Automatische Antworten im Influencerin-Block.
// Testdaten: scratchpad/sp4/seed_dialog.py (nur isolierter Testserver).

test("Dialog: Entwurf, geplante und stornierte KI-Antwort, Modus", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Dialog");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  // jüngster Seed: Entwurf, geplante und stornierte Antwort mit derselben Kennung
  const planned = log.locator(".g-bubble:not([data-status])", { hasText: /Geplant \d+/ }).last();
  const tag = ((await planned.locator("p").first().textContent()) ?? "").replace("Geplant ", "").trim();
  const draft = log.locator('.g-bubble[data-status="draft"]', { hasText: `Entwurf ${tag}` });
  await expect(draft).toContainText("Automatische Antworten der Influencerin sind aus.");
  await expect(draft.getByRole("button", { name: "Senden" })).toBeVisible();
  await expect(planned.locator("small").last()).toContainText(/geplant \d\d:\d\d/);
  await expect(log.locator('.g-bubble[data-status="cancelled"]', { hasText: `Storniert ${tag}` })).toContainText("storniert");
  await log.screenshot({ path: "test-results/sp4-dialog.png" });
  // Zurückhalten: geplante wird Entwurf
  await planned.getByRole("button", { name: "Zurückhalten" }).click();
  await expect(log.locator('.g-bubble[data-status="draft"]', { hasText: `Geplant ${tag}` })).toBeVisible();
  // Entwurf bearbeiten und senden: wartet im Postausgang (Konto nicht verbunden)
  const text = `Ein Foto kostet 20 € (${tag}).`;
  await draft.getByLabel("Entwurf bearbeiten").fill(text);
  await draft.getByRole("button", { name: "Senden" }).click();
  await expect(log.locator(".g-bubble", { hasText: text }).locator("small").last()).toContainText("wartet");
  // Modus „Betreiber“, nach Neuladen erhalten
  const panel = page.getByRole("complementary", { name: "Kundensteuerung" });
  await panel.getByLabel("Modus").first().selectOption("manual");
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Dialog");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  await expect(page.getByRole("complementary", { name: "Kundensteuerung" }).getByLabel("Modus").first()).toHaveValue("manual");
  expect(errors).toEqual([]);
});

test("Influencerin: Schalter Text-KI und Automatische Antworten (nur lesend)", async ({ page }) => {
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  const block = aside.locator("details.g-fold", { hasText: "Influencerin" }).last();
  await block.locator("summary").click();
  await expect(block.getByLabel("Text-KI")).toBeVisible();
  await expect(block.getByLabel("Automatische Antworten")).toBeVisible();
});
