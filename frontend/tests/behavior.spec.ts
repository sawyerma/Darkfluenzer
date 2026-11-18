import { expect, test } from "@playwright/test";

// Verhalten (SP4 Schritt 7): Verhaltensprofil der Influencerin (nur Zahlen) im Influencerin-Block,
// neue Version per Befehl 53, nach Neuladen erhalten.

test("Influencerin: Verhaltensprofil übernehmen, Version steigt", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert die Testinfluencerin – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  const block = aside.locator("details.g-fold", { hasText: "Influencerin" }).last();
  await block.locator("summary").click();
  const heading = block.locator("h3", { hasText: "Verhalten" });
  await expect(heading).toBeVisible();
  await expect(block.getByLabel("Bündeln s")).not.toHaveValue("");
  const before = ((await heading.textContent()) ?? "").match(/Version (\d+)/i)?.[1] ?? "0";
  const bundle = block.getByLabel("Bündeln s");
  const value = (await bundle.inputValue()) === "9" ? "11" : "9";
  await bundle.fill(value);
  await block.getByLabel("Lesen min s").fill("99");
  await block.getByRole("button", { name: "Verhalten übernehmen" }).click();
  await expect(block.getByRole("status")).toContainText("read_min_s > read_max_s");
  await block.getByLabel("Lesen min s").fill("2");
  await block.getByRole("button", { name: "Verhalten übernehmen" }).click();
  await expect(heading).toHaveText(`Verhalten · Version ${Number(before) + 1}`);
  await block.screenshot({ path: "test-results/sp4-verhalten.png" });
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const again = page.getByRole("complementary", { name: "Kundensteuerung" }).locator("details.g-fold", { hasText: "Influencerin" }).last();
  await again.locator("summary").click();
  await expect(again.getByLabel("Bündeln s")).toHaveValue(value);
  expect(errors).toEqual([]);
});
