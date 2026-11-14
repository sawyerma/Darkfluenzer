import { expect, test } from "@playwright/test";

test("drei Bereiche, Wechsel über die Navigation, keine Browserfehler", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Bereiche" });
  await expect(nav.getByRole("link")).toHaveText(["Übersicht", "Nachrichten", "ComfyUI"]);

  for (const name of ["Nachrichten", "ComfyUI", "Übersicht"]) {
    await nav.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }

  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Übersicht");
  expect(errors).toEqual([]);
});
