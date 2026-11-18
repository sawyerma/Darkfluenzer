import { APPROVAL } from "./common";
import type { ChannelStatus, DefaultContact } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { type FormEvent, useState } from "react";
import { InfluencerBlock } from "../InfluencerBlock";
import { PLATFORM_LABEL } from "../../core/channels";
import { Row } from "./CustomerPanel";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { channelNote } from "./Channels";
import { useCommand } from "../../core/commands";
import { useStateTopic } from "../../core/state";

type Run = ReturnType<typeof useCommand>["run"];

// Kurzbefehle des Default-Nutzers (V0 §8.1, FL-6), Reihenfolge wie im Backend (cloner.COMMANDS)
const COMMANDS = ["clone", "pose", "style", "remix", "animate", "edit"] as const;

/** Operator-Felder des Default-Kontakts (F7.4, V0 §8.1); CAS über die gelesene Revision. */
function DefaultForm({
  contact,
  run,
  pending,
  channels,
  live,
}: {
  contact: DefaultContact;
  run: Run;
  pending: boolean;
  channels: readonly ChannelStatus[];
  live: boolean;
}) {
  const [telegram, setTelegram] = useState(contact.telegramSenderId);
  const [instagram, setInstagram] = useState(contact.instagramSenderId);
  const [processCommands, setProcessCommands] = useState(contact.processCommands);
  const [autoOrders, setAutoOrders] = useState(contact.autoOrders);
  const [approval, setApproval] = useState(contact.approvalMode || "cockpit");
  const [influencer, setInfluencer] = useState(contact.influencer);
  const [workflow, setWorkflow] = useState(contact.mediaWorkflow);
  const [video, setVideo] = useState(contact.videoWorkflow);
  const saved = Object.fromEntries(contact.commandWorkflows.map((c) => [c.command, c.workflow]));
  const [commands, setCommands] = useState<Record<string, string>>(saved);
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const influencers = useStateTopic(Topic.INFLUENCERS)?.value.influencers ?? [];
  const usable = registry.filter((w) => w.enabled && w.modelsReady && w.instance !== "ai" && !w.training);
  const media = usable.filter((w) => w.kind === "image");
  // animate: Foto -> Video, also ein Video-Workflow mit Eingangsbild
  const videos = usable.filter((w) => w.kind === "video" && w.params.some((x) => x.upload && x.name === "image"));
  const changed =
    telegram.trim() !== contact.telegramSenderId ||
    instagram.trim() !== contact.instagramSenderId ||
    processCommands !== contact.processCommands ||
    autoOrders !== contact.autoOrders ||
    approval !== contact.approvalMode ||
    influencer.trim() !== contact.influencer ||
    workflow !== contact.mediaWorkflow ||
    video !== contact.videoWorkflow ||
    COMMANDS.some((c) => (commands[c] ?? "") !== (saved[c] ?? ""));

  function submit(e: FormEvent) {
    e.preventDefault();
    void run(
      {
        case: "defaultContactUpdate",
        value: {
          revision: contact.revision,
          telegramSenderId: telegram.trim(),
          instagramSenderId: instagram.trim(),
          processCommands,
          autoOrders,
          approvalMode: approval,
          influencer: influencer.trim(),
          mediaWorkflow: workflow,
          videoWorkflow: video,
          commandWorkflows: COMMANDS.filter((c) => commands[c]).map((c) => ({ command: c, workflow: commands[c] })),
        },
      },
      { done: "Einstellungen übernommen." },
    );
  }

  // Absender-IDs gehören zum Konto der Influencerin: nur bei verbundenem Kanal (Konto bekannt) änderbar
  function sender(platform: string, value: string, set: (v: string) => void) {
    const ch = channels.find((c) => c.platform === platform);
    const id = `df-${platform}`;
    return (
      <div className="g-field g-wide">
        <label htmlFor={id}>{PLATFORM_LABEL[platform]}-Absender-ID</label>
        <input
          id={id}
          className="g-mono"
          value={value}
          placeholder={`${PLATFORM_LABEL[platform]}-ID zuordnen`}
          disabled={!ch?.account}
          onChange={(e) => set(e.target.value)}
        />
        {ch?.account ? null : (
          // kurz: nur der Zustand; was fehlt, steht im Tooltip (keine Konfigurationsprosa, F7.4)
          <small title={channelNote(ch, platform) || undefined}>
            {channelNote(ch, platform).split(" · ")[0] || `${PLATFORM_LABEL[platform]}-Konto unbekannt`}
          </small>
        )}
      </div>
    );
  }

  function choice(
    id: string,
    label: string,
    value: string,
    set: (v: string) => void,
    options: typeof usable,
    none = "Nicht festgelegt",
  ) {
    return (
      <div className="g-field">
        <label htmlFor={id}>{label}</label>
        <select id={id} value={value} onChange={(e) => set(e.target.value)}>
          <option value="">{none}</option>
          {options.map((w) => (
            <option key={w.key} value={w.key}>
              {w.title}
            </option>
          ))}
          {value && !options.some((w) => w.key === value) ? <option value={value}>{value} (nicht verfügbar)</option> : null}
        </select>
      </div>
    );
  }

  return (
    <form className="g-form" onSubmit={submit}>
      <div className="g-control-part g-wide">
        <h3>Identität &amp; Dialog</h3>
        <dl className="g-params">
          <Row label="Kontakt">Default</Row>
          <Row label="Aufgabe">Eigener Absender</Row>
        </dl>
        {sender("telegram", telegram, setTelegram)}
        {sender("instagram", instagram, setInstagram)}
        <label className="g-switch">
          <input type="checkbox" checked={processCommands} onChange={(e) => setProcessCommands(e.target.checked)} />
          Interne Befehle verarbeiten
        </label>
      </div>
      <div className="g-control-part g-wide">
        <h3>KI &amp; Medien</h3>
        <div className="g-field">
          <label htmlFor="df-influencer">Influencerin</label>
          <select id="df-influencer" value={influencer} onChange={(e) => setInfluencer(e.target.value)}>
            <option value="">Nicht festgelegt</option>
            {influencers.map((i) => (
              <option key={String(i.influencerId)} value={String(i.influencerId)}>
                {i.name}
              </option>
            ))}
            {influencer && !influencers.some((i) => String(i.influencerId) === influencer) ? (
              <option value={influencer}>{influencer} (unbekannt)</option>
            ) : null}
          </select>
        </div>
        {choice("df-workflow", "Medien-Workflow", workflow, setWorkflow, media)}
        {choice("df-video", "Video-Workflow (animate)", video, setVideo, videos)}
        <div className="g-field">
          <label htmlFor="df-approval">Freigabemodus</label>
          <select id="df-approval" value={approval} onChange={(e) => setApproval(e.target.value)}>
            {APPROVAL.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <label className="g-switch">
          <input type="checkbox" checked={autoOrders} onChange={(e) => setAutoOrders(e.target.checked)} />
          Automatische Produktionsaufträge
        </label>
      </div>
      <div className="g-control-part g-wide">
        <h3>Befehle</h3>
        {COMMANDS.map((c) =>
          choice(
            `df-cmd-${c}`,
            c,
            commands[c] ?? "",
            (v) => setCommands((m) => ({ ...m, [c]: v })),
            c === "animate" ? videos : media,
            c === "animate" ? "wie Video-Workflow" : "wie Medien-Workflow",
          ),
        )}
      </div>
      <div className="g-control-part g-wide">
        <h3>Einstellungen</h3>
      </div>
      <button type="submit" className="g-button g-primary g-block g-wide" disabled={!live || pending || !changed}>
        Einstellungen übernehmen
      </button>
    </form>
  );
}

export function DefaultPanel({
  contact,
  loaded,
  channels,
  live,
}: {
  contact: DefaultContact | undefined;
  loaded: boolean;
  channels: readonly ChannelStatus[];
  live: boolean;
}) {
  const cmd = useCommand();
  const influencers = useStateTopic(Topic.INFLUENCERS)?.value.influencers ?? [];
  const current = influencers.find((x) => String(x.influencerId) === contact?.influencer);
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const titles: Record<string, string> = Object.fromEntries(workflows.map((w) => [w.key, w.title]));
  return (
    <>
      <div className="g-line g-head">
        <h2>Default · Steuerung</h2>
        <span className="g-badge">INTERN</span>
      </div>
      {contact ? (
        <>
          {/* neue Revision (eigene oder fremde Änderung): Formular zeigt den gespeicherten Stand */}
          <DefaultForm key={String(contact.revision)} contact={contact} run={cmd.run} pending={cmd.pending} channels={channels} live={live} />
          <InfluencerBlock
            key={`${current?.influencerId ?? "neu"}-${current?.revision ?? 0}`}
            influencer={current}
            mediaTitle={titles[contact.mediaWorkflow]}
            videoTitle={titles[contact.videoWorkflow]}
          />
        </>
      ) : (
        <p className="g-note">{loaded ? "Keine Default-Einstellungen vom Backend." : "Lädt …"}</p>
      )}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </>
  );
}
