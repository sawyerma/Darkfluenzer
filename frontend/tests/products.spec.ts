import { expect, test } from "@playwright/test";

// Produkte (SP5 Schritt 1): Art, Workflow, Animation (Video), Kandidaten, Höchstlänge,
// Zusatzleistungen, Lieferbarkeit mit Grund; Zahlungswege und Gültigkeit je Influencerin.

test("Influencerin: Video-Produkt anlegen, Lieferbarkeit und Zahlungswege nach Neuladen", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "ändert die Testinfluencerin – nur isolierter Testserver (DF_BASE_URL)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const open = async () => {
    const block = page.getByRole("complementary", { name: "Kundensteuerung" }).locator("details.g-fold", { hasText: "Influencerin" }).last();
    await block.locator("summary").click();
    return block;
  };
  let block = await open();
  const name = `Clip ${Date.now() % 100000}`;
  await block.getByRole("button", { name: "Position hinzufügen" }).click();
  const product = block.getByLabel("Produkt").last();
  await product.fill(name);
  await block.getByLabel("Preis in €").last().fill("60");
  await block.getByLabel(`Art ${name}`).selectOption("video");
  await expect(block.getByLabel(`Animation ${name}`)).toBeVisible();
  await block.getByLabel(`Höchstlänge s ${name}`).fill("8");
  await block.getByLabel(`Kandidaten ${name}`).fill("2");
  await block.getByLabel(`Lieferzeit max. min ${name}`).fill("30");
  await block.getByLabel("Sperrzeit nach Ablehnung (Minuten, leer = keine)").fill("20");
  const auto = block.getByLabel("Bildautomatik (Produktion nach Zahlung)");
  const wasAuto = await auto.isChecked();
  await auto.setChecked(!wasAuto);
  const btc = block.getByLabel(/^Bitcoin/);
  await btc.setChecked(true);
  await block.getByLabel("Angebot gültig (Minuten, leer = Vorgabe)").fill("45");
  await block.getByRole("button", { name: "Profil speichern" }).click();
  await block.getByRole("button", { name: /speichern$/ }).click();
  await expect(block.getByRole("alert")).toHaveText(/Profil gespeichert/);
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  block = await open();
  const row = block.locator(".g-product").filter({ has: page.locator(`input[value="${name}"]`) });
  await expect(row.getByLabel(`Art ${name}`)).toHaveValue("video");
  await expect(row.locator("small")).toContainText("nicht lieferbar");
  await expect(row.locator("small")).toContainText("Workflow fehlt");
  await expect(block.getByLabel(/^Bitcoin/)).toBeChecked();
  await expect(block.getByLabel("Angebot gültig (Minuten, leer = Vorgabe)")).toHaveValue("45");
  await expect(row.getByLabel(`Lieferzeit max. min ${name}`)).toHaveValue("30");
  await expect(block.getByLabel("Sperrzeit nach Ablehnung (Minuten, leer = keine)")).toHaveValue("20");
  await expect(block.getByLabel("Bildautomatik (Produktion nach Zahlung)")).toBeChecked({ checked: !wasAuto });
  await row.screenshot({ path: "test-results/sp5-produkt.png" });
  expect(errors).toEqual([]);
});
