import { ChannelAccounts } from "./messages/Channels";
import { Instances } from "./comfyui/Instances";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useConnection } from "../core/realtime";
import { useStateTopic } from "../core/state";

// Einstellungen (FRONTEND §3.7, sechster Hauptreiter): eine Karte je Gruppe. Bedienbar ist, was das
// Backend heute kann (Kanäle: Befehle 39/40, Instanzen); Zugangsdaten, Konfiguration und Betrieb
// kommen mit SP2/SP6 (Befehle 60–62) und sind bis dahin als nicht umgesetzt gekennzeichnet.

function Missing({ what }: { what: string }) {
  return (
    <span className="g-between">
      <small>{what}</small>
      <span className="g-badge">NICHT UMGESETZT</span>
    </span>
  );
}

export function Settings() {
  const channels = useStateTopic(Topic.CHANNELS);
  const wallet = useStateTopic(Topic.WALLET);
  const instances = useStateTopic(Topic.COMFY_INSTANCES);
  const connection = useConnection();
  const live = connection.status === "OPEN" && instances?.staleSince === null;
  const crypto = (wallet?.value.accounts ?? []).filter((a) => (a.key === "btc" || a.key === "bsc") && a.state !== "MISSING");
  return (
    <section className="g-panel">
      <h1>Einstellungen</h1>
      <p className="g-lead">Kanäle, KI und Render, Zahlung</p>
      <div className="g-cards g-settings">
        <div className="g-card">
          <h2>Kanäle</h2>
          <ChannelAccounts channels={channels?.value.channels} stale={connection.status !== "OPEN" || (channels?.staleSince ?? null) !== null} />
        </div>
        <div className="g-card">
          <h2>KI und Render</h2>
          <Instances live={live} />
        </div>
        <div className="g-card">
          <h2>Zahlung</h2>
          <span className="g-between">
            <small>Amazon-Gutscheine</small>
            <span className="g-badge">MANUELL</span>
          </span>
          <span className="g-between">
            <small>PayPal</small>
            <span className="g-badge">NICHT ANGESCHLOSSEN</span>
          </span>
          <span className="g-between">
            <small>Krypto (Bitcoin, BSC)</small>
            <span className="g-badge">{crypto.length ? `${crypto.length} ZUGESCHALTET` : "AUS"}</span>
          </span>
        </div>
        <div className="g-card">
          <h2>Zugangsdaten und Betrieb</h2>
          <Missing what="Zugangsdaten im Cockpit (SP2) · bis dahin darkfluenzer secret set" />
          <Missing what="Admin und Test, Betriebsanzeige (SP2, SP6)" />
        </div>
      </div>
    </section>
  );
}
