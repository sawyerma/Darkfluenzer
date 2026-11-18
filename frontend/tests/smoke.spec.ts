import { expect, test } from "@playwright/test";

test("Cockpit am echten Backend: verbunden, sechs Reiter, ComfyUI nach F7.5, Einstellungen, keine Fehler", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.locator(".g-kpi", { hasText: "GPU-Warteschlange" }).locator("strong")).not.toHaveText("–");

  const nav = page.getByRole("navigation", { name: "Bereiche" });
  await expect(nav.getByRole("link")).toHaveText(["Übersicht", "Nachrichten", "ComfyUI", "Dateien", "Wallet", "Einstellungen"]);
  for (const name of ["Nachrichten", "ComfyUI", "Dateien", "Wallet", "Einstellungen", "Übersicht"]) {
    await nav.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
  // Einstellungen (§3.7): Kanalverwaltung dort, in der Kundenliste nur der kompakte Status
  await nav.getByRole("link", { name: "Einstellungen" }).click();
  await expect(page.locator(".g-card", { hasText: "Kanäle" }).locator(".g-ptag", { hasText: "Telegram" }).first()).toBeVisible(); // je Konto eine Karte
  await expect(page.getByText("NICHT UMGESETZT").first()).toBeVisible();
  await nav.getByRole("link", { name: "Nachrichten" }).click();
  await expect(page.getByRole("link", { name: /Kanäle verwalten|Anmeldung nötig/ })).toHaveAttribute("href", "#einstellungen");
  await expect(page.locator(".g-clist").getByText("WhatsApp", { exact: true })).toHaveCount(0);
  await nav.getByRole("link", { name: "ComfyUI" }).click();
  for (const heading of ["Workflows", "Ergebnis", "Steuerung", "Warteschlange", "Instanzen"]) {
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  await expect(page.locator(".g-card", { hasText: "ComfyUI 1" }).locator(".g-badge")).not.toHaveText("KEINE DATEN");
  await expect(page.locator("details.g-expert")).not.toHaveAttribute("open"); // anfangs geschlossen

  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  expect(errors).toEqual([]);
});
