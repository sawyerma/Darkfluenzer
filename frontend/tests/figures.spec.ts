import { expect, test } from "@playwright/test";

// C5.1: jede Akte zeigt ihre Influencerin (Farbplatz je Figur) und ihr Konto; die Kundenliste lässt
// sich nach Influencerin filtern, der Default bleibt sichtbar. Testdaten: scratchpad/sp4/seed_figures.py.

test("Kundenliste: Figur je Akte und Filter nach Influencerin", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "zwei Figuren nur im isolierten Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const list = page.getByRole("list", { name: "Kundenakten" });
  const lucy = list.getByRole("listitem").filter({ hasText: "E2E Lucy" });
  await expect(lucy.locator(".g-ftag")).toHaveText("Lucy");
  await expect(lucy.locator(".g-ftag")).toHaveAttribute("title", "Konto e2e-lucy");
  const other = list.getByRole("listitem").filter({ hasText: "E2E Dialog" });
  await expect(other.locator(".g-ftag")).not.toHaveText("Lucy");
  const filter = page.getByLabel("Influencerin filtern");
  await filter.selectOption({ label: "Lucy" });
  await expect(lucy).toBeVisible();
  await expect(other).toHaveCount(0);
  await expect(list.getByRole("listitem").first()).toContainText("Default"); // Default bleibt
  await page.locator(".g-clist").screenshot({ path: "test-results/c51-figuren.png" });
  await filter.selectOption({ label: "Alle Influencerinnen" });
  await expect(other).toBeVisible();
  expect(errors).toEqual([]);
});
