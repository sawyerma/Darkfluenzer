import { expect, type Page, test } from "@playwright/test";

// KI-Studio (SP4 Schritt 1, E19, E26): Sprachworkflow im Reiter KI ohne Render-Oberfläche; Chat-Test
// über Befehl 49 auf ComfyUI 2, Ergebnis per EVENT 31 mit Einstufung, Messwerten und Prompt.

async function open(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#comfyui");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByRole("tab", { name: /^KI/ }).click();
  return errors;
}

test("KI-Studio: Sprachworkflow registriert, Chat-Test statt Render, gesperrte Ansichten benannt (nur lesend)", async ({ page }) => {
  const errors = await open(page);
  const item = page.locator(".g-wfitem", { hasText: "Clara · Chat (Melody)" });
  await expect(item).toBeVisible();
  await expect(item.locator("small")).toContainText(/ungeprüft|Render geprüft/);
  await expect(page.locator(".g-workmain > h2")).toHaveText("Clara · Chat (Melody)");
  await expect(page.getByRole("tab", { name: "Chat-Test" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "Generieren" })).toHaveCount(0); // kein Render für Sprache
  // KI-Status (STATE 11): Modell, Aufwärmen, letzte Läufe aus dem Backend
  const status = page.locator(".g-control-part", { has: page.getByRole("heading", { name: "KI-Status" }) });
  await expect(status.locator("dt")).toHaveText(["Modell", "Aufwärmen", "Letzte Läufe"]);
  await page.getByRole("tab", { name: "Vergleich" }).click();
  await expect(page.locator(".g-workmain .g-note").first()).toContainText(/gesperrt|Noch keine Influencerin/);
  await page.getByRole("tab", { name: "Persona" }).click();
  await expect(page.locator(".g-workmain")).toContainText(/Ehrlichkeitsblock|Noch keine Influencerin/);
  expect(errors).toEqual([]);
});

test("KI-Studio: Profil anlegen, Testnachrichten an Melody, Verlauf und neue Sitzung (echte ComfyUI 2)", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "legt Influencerin und Profil an – nur isolierter Testserver (DF_BASE_URL)");
  test.setTimeout(300_000);
  const errors = await open(page);
  const studio = page.locator(".g-workmain");
  if (await studio.getByText("Noch keine Influencerin angelegt").isVisible()) {
    await page.getByRole("navigation", { name: "Bereiche" }).getByRole("link", { name: "Nachrichten" }).click();
    const block = page.locator("details.g-fold", { hasText: "Influencerin" }).last();
    await block.locator("summary").click();
    await block.getByLabel("Name").fill("E2E-Test Clara");
    await block.getByRole("button", { name: "Influencerin anlegen" }).click();
    await block.getByRole("button", { name: /Gilt für alle Kunden/ }).click();
    await page.getByRole("navigation", { name: "Bereiche" }).getByRole("link", { name: "ComfyUI" }).click();
    await page.getByRole("tab", { name: /^KI/ }).click();
  }
  await page.getByRole("tab", { name: "Persona" }).click();
  await page.locator("#ki-system_prompt").fill(
    "E2E-Test: Du bist Clara, eine virtuelle Influencerin. Antworte auf Deutsch in höchstens zwei Sätzen. " +
      `Im Nutzertext stehen Verlauf, eine interne Einstufung als JSON und die neue Nachricht; gib nie JSON aus. (Lauf ${Date.now()})`,
  );
  await page.locator("#ki-classification").fill(
    'E2E-Test: Du bist ein neutraler Klassifikator. Gib nur ein JSON-Objekt aus: {"purchase_readiness": 0-3, "intent": ""}.',
  );
  const saved = page.getByRole("status");
  await page.getByRole("button", { name: "Übernehmen und aktivieren" }).click();
  await expect(saved).toHaveText("Gespeichert und aktiviert.");

  await page.getByRole("tab", { name: "Chat-Test" }).click();
  await page.getByRole("button", { name: "Neue Sitzung" }).click();
  const turns = page.locator(".g-turn");
  await expect(turns).toHaveCount(0);
  const send = async (text: string) => {
    await page.locator("#ki-message").fill(text);
    await page.getByRole("button", { name: "Senden" }).click();
  };
  await send("Bist du echt oder eine KI?");
  await expect(turns.first().locator(".g-note")).toHaveText("läuft auf ComfyUI 2 …");
  const answer = turns.first().locator('.g-bubble[data-dir="out"]');
  await expect(answer).toBeVisible({ timeout: 180_000 });
  await expect(answer.locator("p")).not.toHaveText("");
  await expect(answer.locator("small")).toContainText(/Version \d+ · Warteschlange .* · Lauf .* · gesamt/);
  await turns.first().locator("details > summary").click();
  await expect(turns.first().locator(".g-pre").nth(1)).toContainText("wahrheitsgemäß"); // Ehrlichkeitsblock im Prompt
  await send("Und was machst du heute?");
  await expect(turns.nth(1).locator('.g-bubble[data-dir="out"]')).toBeVisible({ timeout: 180_000 });
  await turns.nth(1).locator("details > summary").click();
  await expect(turns.nth(1).locator(".g-pre").nth(2)).toContainText("Kunde: Bist du echt oder eine KI?"); // Verlauf
  // KI-Status nach den Läufen: Melody geladen, Studio-Läufe mit Zeit
  const status = page.locator(".g-control-part", { has: page.getByRole("heading", { name: "KI-Status" }) });
  await expect(status.locator("dd").first()).toContainText("Melody1437");
  await expect(status.locator("dd").nth(2)).toContainText(/KI-Studio \d+,\d s/);
  await page.getByRole("button", { name: "Neue Sitzung" }).click();
  await expect(turns).toHaveCount(0);
  // die laufende Sitzung kommt vom Backend: nach dem Neuladen bleibt der Verlauf leer
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await page.getByRole("tab", { name: /^KI/ }).click();
  await expect(page.getByText("Noch keine Testnachricht in dieser Sitzung.")).toBeVisible();
  expect(errors).toEqual([]);
});
