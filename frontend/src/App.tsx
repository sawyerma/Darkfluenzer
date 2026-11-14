import { useEffect, useState } from "react";
import { ComfyUI } from "./pages/ComfyUI";
import { Messages } from "./pages/Messages";
import { Overview } from "./pages/Overview";

// Drei Hauptansichten (PHASENPLAN_FRONT_V1 F0). Navigation über den URL-Hash: Neuladen und
// Zurück funktionieren ohne Router-Bibliothek und ohne Server-Fallback.
const VIEWS = [
  { id: "uebersicht", label: "Übersicht", Page: Overview },
  { id: "nachrichten", label: "Nachrichten", Page: Messages },
  { id: "comfyui", label: "ComfyUI", Page: ComfyUI },
] as const;

type View = (typeof VIEWS)[number];

function viewFromHash(): View {
  return VIEWS.find((v) => `#${v.id}` === window.location.hash) ?? VIEWS[0];
}

export function App() {
  const [view, setView] = useState(viewFromHash);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="g-app">
      <header className="g-nav">
        <span className="g-brand" aria-hidden="true">
          C
        </span>
        <strong>Darkfluenzer</strong>
        <nav className="g-tabs" aria-label="Bereiche">
          {VIEWS.map((v) => (
            <a key={v.id} href={`#${v.id}`} aria-current={v === view ? "page" : undefined}>
              {v.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="g-main">
        <view.Page />
      </main>
    </div>
  );
}
