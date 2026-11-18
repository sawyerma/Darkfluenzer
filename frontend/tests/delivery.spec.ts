import { expect, test } from "@playwright/test";

// Zustellung (SP5 Schritt 9): geparkte Zustellung („Zustellung wartet auf Kontakt“, Instagram-
// Fenster zu) und Videoauftrag in Prüfung mit „Animation neu (neuer Seed)“ (E23).
// Testdaten: scratchpad/sp5s9/seed_delivery.py (nur isolierter Testserver).

test("Zustellung: wartet auf Kontakt, Animation neu für Video", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Zustellung");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  const parked = log.locator(".g-event", { hasText: "ANGEBOT · Foto · 20,00 € (geparkt" }).last();
  await expect(parked).toContainText("Zustellung wartet auf Kontakt");
  await expect(log.locator(".g-event", { hasText: "ZUSTELLUNG WARTET AUF KONTAKT" }).last()).toBeVisible();
  const video = log.locator(".g-event", { hasText: "ANGEBOT · Clip · 60,00 € (Video" }).last();
  await expect(video).toContainText("Zur Prüfung");
  const redo = video.getByRole("button", { name: "Animation neu (neuer Seed)" });
  await expect(redo).toBeVisible();
  await video.screenshot({ path: "test-results/sp5s9-video-pruefung.png" });
  const before = await video.locator(".g-cand, img").count();
  await redo.click();
  // Wirkung: neuer Versuch der Animationsstufe (das Kandidatenbild bleibt, keine neue Bildstufe);
  // im Testserver ohne ComfyUI scheitert der Job sofort und das bisherige Ergebnis bleibt
  await expect(video).toContainText("Animation wird mit neuem Seed neu erzeugt.");
  await expect(video).toContainText(/Versuch [2-9]/);
  expect(await video.locator(".g-cand, img").count()).toBeGreaterThanOrEqual(before);
  expect(errors).toEqual([]);
});
