import { expect, type Page, test } from "@playwright/test";

// Default-Steuerung (FRONT §2 Nachrichten, F7.4, GUI-Prüfung 18.11. Punkt 4): drei einklappbare
// Gruppen, Zustand im Kopf auch geschlossen, Befehle als Zeilen, „geändert“ je Gruppe.

async function openDefault(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#nachrichten");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  const aside = page.getByRole("complementary", { name: "Kundensteuerung" });
  await expect(aside.getByRole("heading", { name: "Default · Steuerung" })).toBeVisible();
  return { aside, errors };
}

const fold = (aside: ReturnType<Page["locator"]>, title: string) =>
  aside.locator("details.g-fold").filter({ has: aside.page().locator("summary > span:first-child").getByText(title, { exact: true }) });

test("Default-Steuerung: Gruppen, Zustand im Kopf, Befehle einklappbar, Änderungsmarke (nur lesend)", async ({ page }) => {
  const { aside, errors } = await openDefault(page);
  const identity = fold(aside, "Identität & Dialog");
  const media = fold(aside, "KI & Medien");
  const commands = fold(aside, "Befehle");
  await expect(identity).toHaveAttribute("open", "");
  await expect(media).toHaveAttribute("open", "");
  await expect(commands).not.toHaveAttribute("open");
  // Zustand im Kopf aus den echten Feldern (Rückfall wie im Backend)
  const workflow = await aside.locator("#df-workflow").inputValue();
  const hint = media.locator(".g-fold-hint");
  if (workflow) await expect(hint).not.toHaveAttribute("data-tone", "warn");
  else {
    await expect(hint).toHaveAttribute("data-tone", "warn");
    await expect(hint).toHaveText("Medien-Workflow fehlt");
  }
  await expect(commands.locator(".g-fold-hint")).not.toHaveText("");

  await commands.locator("summary").click();
  await expect(commands).toHaveAttribute("open", "");
  // je Befehl die Zeile mit dem Befehlsnamen, darunter das Ausgabeprofil (SP1 Schritt 6)
  await expect(commands.locator(".g-cmd > .g-field:not(.g-sub) > label")).toHaveText(["clone", "pose", "style", "remix", "animate", "edit"]);
  await expect(commands.getByLabel("Dauer animate (s)")).toBeVisible();

  // Änderung markiert nur die betroffene Gruppe und gibt den Knopf frei; Rücknahme hebt beides auf
  const save = aside.getByRole("button", { name: "Einstellungen übernehmen" });
  const approval = aside.locator("#df-approval");
  const before = await approval.inputValue();
  const other = before === "direct" ? "cockpit_only" : "direct";
  await approval.selectOption(other);
  await expect(media.locator(".g-fold-changed")).toHaveText("geändert");
  await expect(identity.locator(".g-fold-changed")).toHaveCount(0);
  await expect(save).toBeEnabled();
  await approval.selectOption(before);
  await expect(media.locator(".g-fold-changed")).toHaveCount(0);
  await expect(save).toBeDisabled();

  await media.locator("summary").click();
  await expect(media).not.toHaveAttribute("open");
  await expect(aside.locator("#df-approval")).toBeHidden();
  expect(errors).toEqual([]);
});

test("Default-Steuerung: Speichern über das Backend, Auf/Zu bleibt nach der neuen Revision", async ({ page }) => {
  test.skip(!process.env.DF_E2E_WRITE, "schreibt den Default-Kontakt – nur gegen einen isolierten Testserver (DF_BASE_URL)");
  const { aside, errors } = await openDefault(page);
  const commands = fold(aside, "Befehle");
  const media = fold(aside, "KI & Medien");
  await commands.locator("summary").click();
  const approval = aside.locator("#df-approval");
  const before = await approval.inputValue();
  const other = before === "direct" ? "cockpit_only" : "direct";
  await approval.selectOption(other);
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(aside.getByRole("alert")).toHaveText("Einstellungen übernommen.");
  // neue Revision: Formular zeigt den gespeicherten Stand, Gruppen bleiben wie gewählt
  await expect(approval).toHaveValue(other);
  await expect(media.locator(".g-fold-changed")).toHaveCount(0);
  await expect(commands).toHaveAttribute("open", "");
  await page.reload();
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(aside.locator("#df-approval")).toHaveValue(other);
  await aside.locator("#df-approval").selectOption(before); // Ausgangszustand wiederherstellen
  await aside.getByRole("button", { name: "Einstellungen übernehmen" }).click();
  await expect(aside.locator("#df-approval")).toHaveValue(before);
  expect(errors).toEqual([]);
});
