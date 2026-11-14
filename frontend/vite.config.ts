import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react-swc";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const SRC = fileURLToPath(new URL("./src", import.meta.url));
const SCHEMAS = fileURLToPath(new URL("../protocol/schemas", import.meta.url));
const STYLESHEET = join("shared", "graphite.css");

// Schema-Fingerabdruck wie im Backend (backend/src/darkfluenzer/stream.py schema_id): SHA-256
// über alle .proto-Dateien, sortiert nach relativem Pfad, je Pfad und Inhalt mit Längenpräfix.
function schemaId(): string {
  const digest = createHash("sha256");
  const names = readdirSync(SCHEMAS, { recursive: true })
    .map((n) => String(n).split(sep).join("/"))
    .filter((n) => n.endsWith(".proto"))
    .sort();
  for (const name of names) {
    const rel = Buffer.from(name, "utf8");
    const data = readFileSync(join(SCHEMAS, name));
    const relLen = Buffer.alloc(4);
    relLen.writeUInt32BE(rel.length);
    const dataLen = Buffer.alloc(8);
    dataLen.writeBigUInt64BE(BigInt(data.length));
    digest.update(Buffer.concat([relLen, rel, dataLen, data]));
  }
  return digest.digest("hex");
}

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
  define: { __DF_SCHEMA_ID__: JSON.stringify(schemaId()) },
  test: { include: ["tests/**/*.test.ts"] },
});
