import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react-swc";
import { defineConfig, type Plugin } from "vite";

const SRC = fileURLToPath(new URL("./src", import.meta.url));
const STYLESHEET = join("shared", "graphite.css");

// Ein globales Stylesheet für alle Seiten (PHASENPLAN_FRONT_V1 F1): der Build bricht ab bei
// jeder weiteren CSS-Datei, Farbwerten außerhalb der :root-Tokens oder Inline-Styles.
function oneStylesheet(): Plugin {
  return {
    name: "darkfluenzer-one-stylesheet",
    buildStart() {
      const files = readdirSync(SRC, { recursive: true }).map(String);
      const css = files.filter((f) => f.endsWith(".css"));
      if (css.length !== 1 || css[0] !== STYLESHEET) {
        this.error(`Nur src/${STYLESHEET} ist erlaubt, gefunden: ${css.join(", ") || "keine"}`);
      }
      const text = readFileSync(join(SRC, STYLESHEET), "utf8");
      const rules = text.slice(text.indexOf("}", text.indexOf(":root")) + 1);
      if (/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i.test(rules)) {
        this.error(`Farbwerte nur als Token im :root-Block von src/${STYLESHEET}`);
      }
      for (const f of files.filter((n) => n.endsWith(".tsx"))) {
        if (/\sstyle=\{/.test(readFileSync(join(SRC, f), "utf8"))) {
          this.error(`Inline-Style in src/${f}; Klassen aus src/${STYLESHEET} verwenden`);
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), oneStylesheet()],
});
