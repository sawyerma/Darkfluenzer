import { expect, test } from "@playwright/test";

test("Cockpit am echten Backend: verbunden, vier Bereiche, ComfyUI nach F7.5, keine Fehler", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.locator(".g-kpi", { hasText: "GPU-Warteschlange" }).locator("strong")).not.toHaveText("–");

  const nav = page.getByRole("navigation", { name: "Bereiche" });
  await expect(nav.getByRole("link")).toHaveText(["Übersicht", "Nachrichten", "ComfyUI", "Dateien"]);
  for (const name of ["Nachrichten", "ComfyUI", "Dateien", "Übersicht"]) {
    await nav.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
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
