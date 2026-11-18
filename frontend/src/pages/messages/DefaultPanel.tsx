import { APPROVAL } from "./common";
import type { ChannelStatus, DefaultContact } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { type FormEvent, type ReactNode, useState } from "react";
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

// Gruppen der Default-Steuerung (F7.4 „Identität & Dialog“, „KI & Medien“; Befehle FL-6), einklappbar
type FoldId = "identity" | "media" | "commands";
type Folds = Record<FoldId, boolean>;
const FOLDS_OPEN: Folds = { identity: true, media: true, commands: false };

/** Einklappbare Gruppe (F7 details): Kopf mit Zustand, damit auch geschlossen sichtbar ist, was
 *  fehlt (SP1: ausgeschaltete Schalter und fehlende Workflows sichtbar). */
function Fold({
  id,
  title,
  hint,
  warn,
  changed,
  folds,
  toggle,
  children,
}: {
  id: FoldId;
  title: string;
  hint: string;
  warn: boolean;
  changed: boolean;
  folds: Folds;
  toggle: (id: FoldId, open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <details className="g-fold g-wide" open={folds[id]} onToggle={(e) => toggle(id, e.currentTarget.open)}>
      <summary>
        <span>{title}</span>
        {changed ? <span className="g-fold-changed">geändert</span> : null}
        <span className="g-fold-hint" data-tone={warn ? "warn" : undefined}>
          {hint}
        </span>
      </summary>
      <div className="g-fold-body">{children}</div>
    </details>
  );
}

/** Operator-Felder des Default-Kontakts (F7.4, V0 §8.1); CAS über die gelesene Revision. */
function DefaultForm({
  contact,
  run,
  pending,
  channels,
  live,
  folds,
  toggle,
}: {
  contact: DefaultContact;
  run: Run;
  pending: boolean;
  channels: readonly ChannelStatus[];
  live: boolean;
  folds: Folds;
  toggle: (id: FoldId, open: boolean) => void;
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
  const changedIdentity =
    telegram.trim() !== contact.telegramSenderId ||
    instagram.trim() !== contact.instagramSenderId ||
    processCommands !== contact.processCommands;
  const changedMedia =
    autoOrders !== contact.autoOrders ||
    approval !== contact.approvalMode ||
    influencer.trim() !== contact.influencer ||
    workflow !== contact.mediaWorkflow ||
    video !== contact.videoWorkflow;
  const changedCommands = COMMANDS.some((c) => (commands[c] ?? "") !== (saved[c] ?? ""));
  const changed = changedIdentity || changedMedia || changedCommands;

  // Zustand je Gruppe aus dem aktuellen Formular; Rückfall wie im Backend (cloner: Workflow des
  // Befehls, sonst Video- bzw. Medien-Workflow)
  const senders = [telegram.trim() && "Telegram", instagram.trim() && "Instagram"].filter(Boolean);
  const identityHint = [senders.length ? senders.join(" + ") : "kein Absender", processCommands ? "" : "Befehle aus"]
    .filter(Boolean)
    .join(" · ");
  const titleOf = (key: string) => registry.find((w) => w.key === key)?.title ?? key;
  const mediaHint = workflow
    ? [titleOf(workflow), autoOrders ? "" : "Start im Cockpit"].filter(Boolean).join(" · ")
    : "Medien-Workflow fehlt";
  const own = COMMANDS.filter((c) => commands[c]).length;
  const missing = COMMANDS.filter((c) => !commands[c] && !(c === "animate" ? video : workflow));
  const commandsHint = missing.length
    ? `${missing.length} ohne Workflow`
    : own
      ? `${own} eigene · ${COMMANDS.length - own} Standard`
      : "alle Standard";

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
      <Fold
        id="identity"
        title="Identität & Dialog"
        hint={identityHint}
        warn={!senders.length || !processCommands}
        changed={changedIdentity}
        folds={folds}
        toggle={toggle}
      >
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
      </Fold>
      <Fold
        id="media"
        title="KI & Medien"
        hint={mediaHint}
        warn={!workflow}
        changed={changedMedia}
        folds={folds}
        toggle={toggle}
      >
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
      </Fold>
      <Fold
        id="commands"
        title="Befehle"
        hint={commandsHint}
        warn={missing.length > 0}
        changed={changedCommands}
        folds={folds}
        toggle={toggle}
      >
        {COMMANDS.map((c) => {
          const base = c === "animate" ? video : workflow;
          const label = c === "animate" ? "Video-Workflow" : "Medien-Workflow";
          return (
            <div key={c} className="g-cmd">
              {choice(
                `df-cmd-${c}`,
                c,
                commands[c] ?? "",
                (v) => setCommands((m) => ({ ...m, [c]: v })),
                c === "animate" ? videos : media,
                base ? `wie ${label}` : `kein Workflow (${label} fehlt)`,
              )}
            </div>
          );
        })}
      </Fold>
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
  // Auf-/Zu-Zustand überlebt das Neuladen des Formulars bei neuer Revision (key)
  const [folds, setFolds] = useState<Folds>(FOLDS_OPEN);
  const toggle = (id: FoldId, open: boolean) => setFolds((f) => (f[id] === open ? f : { ...f, [id]: open }));
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
          <DefaultForm
            key={String(contact.revision)}
            contact={contact}
            run={cmd.run}
            pending={cmd.pending}
            channels={channels}
            live={live}
            folds={folds}
            toggle={toggle}
          />
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
