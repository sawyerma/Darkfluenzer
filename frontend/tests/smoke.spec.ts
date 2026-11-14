import { expect, test } from "@playwright/test";

test("Cockpit am echten Backend: verbunden, ComfyUI-Zustand, drei Bereiche, keine Fehler", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const comfy = page.locator(".g-line", { hasText: "ComfyUI" }).locator(".g-badge");
  await expect(comfy).not.toHaveText("KEINE DATEN");

  const nav = page.getByRole("navigation", { name: "Bereiche" });
  await expect(nav.getByRole("link")).toHaveText(["Übersicht", "Nachrichten", "ComfyUI"]);
  for (const name of ["Nachrichten", "ComfyUI", "Übersicht"]) {
    await nav.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
  await nav.getByRole("link", { name: "ComfyUI" }).click();
  await expect(page.getByRole("heading", { name: "Ergebnisse" })).toBeVisible();
  await expect(page.getByText("Lädt …")).toHaveCount(0); // Nachzug des Job-Journals beendet

  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  expect(errors).toEqual([]);
});
