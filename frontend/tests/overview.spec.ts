import { type Browser, expect, type Page, test } from "@playwright/test";

// Übersicht (FRONT §3.1, F7.1, GUI-Prüfung 18.11. Punkt 5, BUG-070): vier Kennzahlkarten aus
// echtem STATE, offene Aufträge mit Ziel, Push in ein zweites verbundenes Cockpit.

async function overview(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#uebersicht");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Übersicht");
  return errors;
}

const card = (page: Page, title: string) => page.locator(".g-kpi").filter({ has: page.locator("small:first-child", { hasText: title }) });
const orderRows = (page: Page) =>
  page.locator(".g-listpanel").filter({ has: page.getByRole("heading", { name: /^Offene Aufträge/ }) }).locator(".g-listrow");

test("Übersicht: vier Karten, Teilzahlen, offene Aufträge führen zum Ziel (nur lesend)", async ({ page }) => {
  const errors = await overview(page);
  for (const title of ["Kundenakten", "GPU-Warteschlange", "Freigaben ausstehend", "Betrieb"]) {
    await expect(card(page, title).locator("strong")).not.toHaveText("–");
  }
  // Summe = Freigabe + wartet auf Produktion + Auswahl
  const approvals = card(page, "Freigaben ausstehend");
  const parts = (await approvals.locator("small").nth(1).innerText()).match(/\d+/g)?.map(Number) ?? [];
  expect(parts).toHaveLength(3);
  await expect(approvals.locator("strong")).toHaveText(String(parts.reduce((a, b) => a + b, 0)));
  await expect(card(page, "GPU-Warteschlange").locator("small", { hasText: /^ComfyUI 1 · Medien: / })).toBeVisible();
  await expect(card(page, "Betrieb").locator("strong")).toContainText(/von \d+ bereit/);

  const rows = orderRows(page);
  const count = await rows.count();
  expect(count).toBeLessThanOrEqual(8);
  for (let i = 0; i < count; i++) await expect(rows.nth(i).locator(".g-badge")).not.toHaveText("");
  const choose = rows.filter({ has: page.locator(".g-badge", { hasText: "AUSWAHL" }) });
  expect(await choose.count()).toBe(Math.min(parts[2] ?? 0, 8 - Math.min(8, (parts[0] ?? 0) + (parts[1] ?? 0))));
  if ((await choose.count()) > 0) {
    await choose.first().click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("ComfyUI");
    await page.goBack();
  }
  await card(page, "Betrieb").getByRole("link", { name: "Einstellungen" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Einstellungen");
  expect(errors).toEqual([]);
});

async function second(browser: Browser) {
  const ctx = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await ctx.newPage();
  await overview(page);
  return { ctx, page };
}

test("Übersicht: Kundenfreigabe und bezahlter Auftrag sichtbar, Akte öffnet; Push in ein zweites Cockpit", async ({ page, browser }) => {
  test.skip(!process.env.DF_E2E_WRITE, "braucht Testdaten und hält eine Warteschlange an – nur isolierter Testserver (DF_BASE_URL)");
  const errors = await overview(page);
  const rows = orderRows(page);
  const review = rows.filter({ has: page.locator(".g-badge", { hasText: "FREIGABE" }) });
  const paid = rows.filter({ has: page.locator(".g-badge", { hasText: "BEZAHLT" }) });
  await expect(review).toHaveCount(1);
  await expect(paid).toHaveCount(1);
  await expect(review).toContainText(/DF-C-\d{6} · Foto · Ergebnis prüfen/);
  await expect(paid).toContainText("wartet auf Produktion");
  await expect(card(page, "Freigaben ausstehend").locator("small").nth(1)).toHaveText(/^Freigabe 1 · wartet auf Produktion 1 · /);
  const customer = (await review.innerText()).match(/DF-C-\d{6}/)?.[0] ?? "";
  await review.click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Nachrichten");
  await expect(page.locator(`[role="tab"][title="${customer}"]`)).toHaveAttribute("aria-selected", "true");

  // zweites Cockpit bleibt auf der Übersicht; Anhalten im ersten erscheint dort ohne Neuladen
  const other = await second(browser);
  const queue = card(other.page, "GPU-Warteschlange").locator("small", { hasText: /^ComfyUI 1 · Medien: / });
  await expect(queue).not.toContainText("angehalten");
  await page.getByRole("navigation", { name: "Bereiche" }).getByRole("link", { name: "ComfyUI" }).click();
  await page.getByRole("button", { name: "Anhalten" }).click();
  await expect(queue).toContainText("angehalten");
  await page.getByRole("button", { name: "Fortsetzen" }).click();
  await expect(queue).not.toContainText("angehalten");
  await other.ctx.close();
  expect(errors).toEqual([]);
});
