import { expect, test } from "@playwright/test";

// Gestaltung aller sechs Reiter gegen F7 (GUI-Prüfung 18.11. Punkt 7): Knöpfe, Abzeichen, Karten,
// Eingabefelder, Seitentitel mit den F7-Werten; Nachweisstatus statt bloßem PASS/OFFEN.

const TABS = ["Übersicht", "Nachrichten", "ComfyUI", "Dateien", "Wallet", "Einstellungen"];

test("Design: F7-Werte in allen sechs Reitern, kein bloßes PASS (nur lesend)", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator(".g-nav-end")).toHaveText("VERBUNDEN");
  await expect(page.locator(".g-brand")).toHaveCSS("border-radius", "12px");
  const nav = page.getByRole("navigation", { name: "Bereiche" });
  for (const name of TABS) {
    await nav.getByRole("link", { name }).click();
    await page.waitForTimeout(300);
    const found = await page.evaluate(() => {
      const css = (el: Element, p: string) => getComputedStyle(el).getPropertyValue(p);
      const all = (sel: string) => [...document.querySelectorAll(sel)].filter((e) => (e as HTMLElement).offsetParent !== null);
      const bad: string[] = [];
      for (const b of all(".g-button")) {
        const want = b.classList.contains("g-block") ? "10px" : "7px";
        if (css(b, "border-radius") !== want) bad.push(`Knopf ${b.textContent?.trim()}: ${css(b, "border-radius")}`);
      }
      for (const b of all(".g-badge")) {
        if (css(b, "border-radius") !== "6px") bad.push(`Abzeichen ${b.textContent}: ${css(b, "border-radius")}`);
        if (/^(PASS|OFFEN|FAIL)$/.test(b.textContent?.trim() ?? "")) bad.push(`bloßer Status: ${b.textContent}`);
      }
      for (const c of all(".g-card")) {
        const inner = c.parentElement?.closest(".g-card, .g-control");
        const [bg, radius] = inner ? ["rgb(48, 48, 55)", "10px"] : ["rgb(40, 40, 45)", "12px"];
        if (css(c, "background-color") !== bg || css(c, "border-radius") !== radius)
          bad.push(`Karte ${c.textContent?.slice(0, 20)}: ${css(c, "background-color")} ${css(c, "border-radius")}`);
      }
      for (const i of all(".g-form input:not([type=checkbox]):not([type=file]), .g-form select, .g-form textarea, .g-input")) {
        if (css(i, "background-color") !== "rgb(41, 41, 47)" || css(i, "border-top-color") !== "rgb(85, 85, 95)")
          bad.push(`Feld ${(i as HTMLInputElement).id || i.tagName}: ${css(i, "background-color")} ${css(i, "border-top-color")}`);
      }
      const h1 = document.querySelector(".g-panel h1");
      if (h1 && !h1.classList.contains("g-sr-only") && (css(h1, "font-size") !== "22px" || css(h1, "font-weight") !== "650"))
        bad.push(`Titel ${css(h1, "font-size")} ${css(h1, "font-weight")}`);
      return bad;
    });
    expect(found, name).toEqual([]);
  }
  // Nachweisstatus mit Erklärung am gewählten Workflow
  await nav.getByRole("link", { name: "ComfyUI" }).click();
  const badge = page.locator(".g-control .g-line", { hasText: "Workflow" }).locator(".g-badge");
  await expect(badge).toHaveText(/^(RENDER GEPRÜFT|UNGEPRÜFT|RENDER FEHLGESCHLAGEN|GESPERRT)$/);
  await expect(badge).toHaveAttribute("title", /Manifest/);
  // WhatsApp (C7) nur als Unterregister, wenn verknüpft
  await nav.getByRole("link", { name: "Nachrichten" }).click();
  await expect(page.locator('.g-channels [data-platform="whatsapp"]:disabled')).toHaveCount(0);
  expect(errors).toEqual([]);
});
