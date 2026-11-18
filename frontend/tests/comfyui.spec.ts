import { expect, type Page, test } from "@playwright/test";

// Reiter ComfyUI (GUI-Prüfung 18.11. Punkt 6): Workflowliste nach Aufgabe gruppiert und
// einklappbar, Kandidatenaufträge einzeln einklappbar, Prüfwerte eingeklappt; Funktionen erhalten.

async function comfy(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#comfyui");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.getByRole("heading", { name: "Workflows", exact: true })).toBeVisible();
  return errors;
}

const group = (page: Page, name: string) =>
  page.locator("details.g-wfgroup").filter({ has: page.locator("summary > span").getByText(name, { exact: true }) });

test("ComfyUI: Gruppen, einklappbare Aufträge und Prüfwerte, Bedienelemente vorhanden (nur lesend)", async ({ page }) => {
  const errors = await comfy(page);
  const tab = page.getByRole("tab", { name: /^Fotos/ });
  await tab.click();
  await expect(page.locator('.g-wfitem[aria-current="true"]')).toBeVisible(); // Gruppe des gewählten Workflows offen

  // Kandidaten: erster Auftrag offen, weitere zu (Miniaturen im Kopf); Prüfwerte eingeklappt
  const orders = page.locator("details.g-order");
  if ((await orders.count()) > 0) {
    await expect(orders.first()).toHaveAttribute("open", "");
    await expect(orders.first().getByRole("button", { name: "Auswählen" }).first()).toBeEnabled();
    if ((await orders.count()) > 1) {
      await expect(orders.nth(1)).not.toHaveAttribute("open");
      await orders.nth(1).locator("summary").click();
      await expect(orders.nth(1)).toHaveAttribute("open", "");
      await expect(orders.nth(1).locator(".g-order-thumbs")).toHaveCount(0);
    }
  }
  const checks = page.locator("details.g-checks");
  if ((await checks.count()) > 0) {
    await expect(checks.first()).not.toHaveAttribute("open");
    await checks.first().locator("summary").click();
    await expect(checks.first().locator(".g-line").first()).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Generieren" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^(Anhalten|Fortsetzen)$/ })).toBeVisible();

  // jeder Fotos-Workflow steht in genau einer Gruppe; Zahl im Kopf stimmt; geschlossene Gruppe öffnen und wählen
  const total = Number(await tab.locator("small").innerText());
  const groups = page.locator("details.g-wfgroup");
  if ((await groups.count()) > 1) {
    let sum = 0;
    for (const g of await groups.all()) {
      const n = Number(await g.locator("summary > small").innerText());
      await expect(g.locator(".g-wfitem")).toHaveCount(n);
      sum += n;
    }
    expect(sum).toBe(total);
    const closedName = (await page.locator("details.g-wfgroup:not([open]) > summary > span").first().textContent().catch(() => "")) ?? "";
    if (closedName) {
      const g = group(page, closedName);
      await g.locator("summary").click();
      await expect(g).toHaveAttribute("open", "");
      const pick = g.locator(".g-wfitem").first();
      const title = await pick.locator("strong").innerText();
      await pick.click();
      await expect(page.locator(".g-workmain > h2").first()).toHaveText(title);
      await expect(g).toHaveAttribute("open", "");
      await expect(pick).toHaveAttribute("aria-current", "true");
    }
  }
  expect(errors).toEqual([]);
});

test("ComfyUI: Kandidat im eingeklappten Auftrag auswählen – Auftrag verlässt die Auswahl", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "wählt einen Kandidaten – nur isolierter Testserver mit Testaufträgen (DF_BASE_URL)");
  const errors = await comfy(page);
  await page.getByRole("tab", { name: /^Fotos/ }).click();
  await page.locator(".g-wfitem").filter({ hasText: "Krea 2 Turbo · Text zu Bild" }).click();
  const orders = page.locator("details.g-order");
  await expect(orders).toHaveCount(2);
  const second = orders.nth(1);
  const no = (await second.locator("summary .g-ellipsis").innerText()).split(" · ")[0] ?? "";
  await expect(second.locator(".g-order-thumbs img")).toHaveCount(3);
  await second.locator("summary").click();
  await second.getByRole("button", { name: "Auswählen" }).first().click();
  // ohne Fertigstellen geht der Auftrag zur Prüfung und verschwindet aus den Kandidaten (Push)
  await expect(page.locator("details.g-order summary", { hasText: no })).toHaveCount(0);
  await expect(orders).toHaveCount(1);
  expect(errors).toEqual([]);
});
