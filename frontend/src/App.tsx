import { useEffect, useState } from "react";
import { connect, useConnection, type ConnectionStatus } from "./core/realtime";
import { ComfyUI } from "./pages/ComfyUI";
import { Files } from "./pages/Files";
import { Messages } from "./pages/Messages";
import { Overview } from "./pages/Overview";

// Vier Hauptansichten (PHASENPLAN_FRONT_V1 F0). Navigation über den URL-Hash: Neuladen und
// Zurück funktionieren ohne Router-Bibliothek und ohne Server-Fallback.
const VIEWS = [
  { id: "uebersicht", label: "Übersicht", Page: Overview },
  { id: "nachrichten", label: "Nachrichten", Page: Messages },
  { id: "comfyui", label: "ComfyUI", Page: ComfyUI },
  { id: "dateien", label: "Dateien", Page: Files },
] as const;

type View = (typeof VIEWS)[number];

function viewFromHash(): View {
  return VIEWS.find((v) => `#${v.id}` === window.location.hash) ?? VIEWS[0];
}

const CONNECTION_LABEL: Record<ConnectionStatus, [string, string]> = {
  CONNECTING: ["VERBINDE", "warn"],
  OPEN: ["VERBUNDEN", "ok"],
  STALE: ["GETRENNT", "warn"],
  BLOCKED: ["BLOCKIERT", "bad"],
};

export function App() {
  const [view, setView] = useState(viewFromHash);
  const connection = useConnection();
  const [label, tone] = CONNECTION_LABEL[connection.status];

  useEffect(connect, []);
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
        <span className="g-badge g-nav-end" data-tone={tone} title={connection.reason || undefined}>
          {label}
        </span>
      </header>
      {connection.status === "BLOCKED" ? (
        <p className="g-note g-banner" role="alert">
          {connection.reason}
        </p>
      ) : null}
      <main className="g-main">
        <view.Page />
      </main>
    </div>
  );
}
