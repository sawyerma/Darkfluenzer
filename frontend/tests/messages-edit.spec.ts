import { expect, test } from "@playwright/test";

// Telegram-Eingang vollständig (SP2 Schritt 5): bearbeitete Nachricht zeigt den neuen Text mit
// „bearbeitet“ und den ersten Text aufklappbar; gelöschte Nachricht bleibt mit Löschmarke sichtbar.
// Testdaten: scratchpad/sp2s5/seed_edit.py (nur isolierter Testserver).

test("Nachrichten: bearbeitete und gelöschte Telegram-Nachricht im Verlauf", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "Testakte nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByLabel("Kunde suchen").fill("E2E Bearbeitet");
  await page.getByRole("list", { name: "Kundenakten" }).getByRole("listitem").first().click();
  const log = page.getByRole("log", { name: "Verlauf" });
  const edited = log.locator(".g-bubble", { hasText: "Zweite Fassung" }).last();
  await expect(edited.locator("small").last()).toContainText("bearbeitet");
  await expect(edited.locator(".g-orig p")).toBeHidden();
  await edited.getByText("Erster Text").click();
  await expect(edited.locator(".g-orig p")).toHaveText("Erste Fassung");
  const deleted = log.locator(".g-bubble", { hasText: "Wird gelöscht" }).last();
  await expect(deleted).toHaveAttribute("data-deleted", "true");
  await expect(deleted.locator("small").last()).toContainText("gelöscht");
  await expect(deleted.locator("p").first()).toHaveCSS("text-decoration-line", "line-through");
  await log.screenshot({ path: "test-results/sp2s5-bearbeitet-geloescht.png" });
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.getByRole("log", { name: "Verlauf" }).locator(".g-bubble[data-deleted]").last()).toContainText("Wird gelöscht");
  expect(errors).toEqual([]);
});
