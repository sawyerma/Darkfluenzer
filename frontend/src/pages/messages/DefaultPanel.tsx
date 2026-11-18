import { APPROVAL } from "./common";
import type { ChannelStatus, DefaultContact } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { type FormEvent, type ReactNode, useState } from "react";
import { InfluencerBlock } from "../InfluencerBlock";
import { PLATFORM_LABEL } from "../../core/channels";
import { Row } from "./CustomerPanel";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { channelNote } from "./Channels";
import { useCommand } from "../../core/commands";
import { useEventTopic, useStateTopic } from "../../core/state";
import type { AiRun } from "../../core/generated/darkfluenzer/v1/ai_pb";

type Run = ReturnType<typeof useCommand>["run"];

// Kurzbefehle des Default-Nutzers (V0 §8.1, FL-6), Reihenfolge wie im Backend (cloner.COMMANDS)
const COMMANDS = ["clone", "pose", "style", "remix", "animate", "edit"] as const;

// Betriebsart je Kanalkonto (SP1 Schritt 12): Produktion = Befehle, Test = Kundentest, Aus = nur anzeigen
const MODES: [string, string][] = [
  ["production", "Produktion"],
  ["test", "Test"],
  ["off", "Aus"],
];

type Profile = { workflow: string; format: string; duration: string; finish: string };
const EMPTY: Profile = { workflow: "", format: "", duration: "", finish: "" };

// Gruppen der Default-Steuerung (F7.4 „Identität & Dialog“, „KI & Medien“; Befehle FL-6), einklappbar
type FoldId = "identity" | "media" | "commands" | "test";
type Folds = Record<FoldId, boolean>;
const FOLDS_OPEN: Folds = { identity: true, media: true, commands: false, test: false };

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
  // Workflow und Ausgabeprofil je Befehl (FL-6, SP1 Schritt 6)
  const saved: Record<string, Profile> = Object.fromEntries(
    contact.commandWorkflows.map((c) => [
      c.command,
      { workflow: c.workflow, format: c.format, duration: c.durationS ? String(c.durationS) : "", finish: c.finish },
    ]),
  );
  const [profiles, setProfiles] = useState<Record<string, Profile>>(saved);
  const commands = Object.fromEntries(COMMANDS.map((c) => [c, profiles[c]?.workflow ?? ""]));
  const setProfile = (c: string, patch: Partial<Profile>) => setProfiles((m) => ({ ...m, [c]: { ...(m[c] ?? EMPTY), ...patch } }));
  const [candidates, setCandidates] = useState(contact.clonerCandidates ? String(contact.clonerCandidates) : "");
  const [cancelWord, setCancelWord] = useState(contact.cancelWord);
  const savedModes = Object.fromEntries(contact.accountModes.map((m) => [m.key, m.mode]));
  const [modes, setModes] = useState<Record<string, string>>(savedModes);
  const [testDelay, setTestDelay] = useState(contact.testDelay);
  const reset = useCommand();
  const results = useEventTopic(Topic.AI_RESULT);
  // Messwerte je Testantwort (SP4 Schritt 8) aus ai_runs: laufende Sitzung, neueste zuerst
  const testRuns = (results?.items ?? [])
    .map((e) => e.value.run)
    .filter((r): r is AiRun => !!r && r.kind === "test" && r.session === contact.testSession)
    .slice(-5)
    .reverse();
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const influencers = useStateTopic(Topic.INFLUENCERS)?.value.influencers ?? [];
  const usable = registry.filter((w) => w.enabled && w.modelsReady && w.instance !== "ai" && !w.training);
  const media = usable.filter((w) => w.kind === "image");
  // animate: Foto -> Video, also ein Video-Workflow mit Eingangsbild
  const videos = usable.filter((w) => w.kind === "video" && w.params.some((x) => x.upload && x.name === "image"));
  // Fertigstellen: Bild-Workflows mit Eingang „image“ in der Rolle Ausgabe/Hochskalieren (z. B. Instagram-Format)
  const finishers = media.filter((w) => ["output", "upscale"].includes(w.role) && w.params.some((x) => x.upload && x.name === "image"));
  const changedIdentity =
    telegram.trim() !== contact.telegramSenderId ||
    instagram.trim() !== contact.instagramSenderId ||
    processCommands !== contact.processCommands ||
    cancelWord.trim() !== contact.cancelWord ||
    Object.entries(modes).some(([k, m]) => m !== savedModes[k]);
  const changedMedia =
    autoOrders !== contact.autoOrders ||
    approval !== contact.approvalMode ||
    influencer.trim() !== contact.influencer ||
    workflow !== contact.mediaWorkflow ||
    video !== contact.videoWorkflow ||
    (Number(candidates) || 0) !== contact.clonerCandidates ||
    testDelay !== contact.testDelay;
  const same = (a: Profile | undefined, b: Profile | undefined) => JSON.stringify(a ?? EMPTY) === JSON.stringify(b ?? EMPTY);
  const changedCommands = COMMANDS.some((c) => !same(profiles[c], saved[c]));
  const changed = changedIdentity || changedMedia || changedCommands;

  // Zustand je Gruppe aus dem aktuellen Formular; Rückfall wie im Backend (cloner: Workflow des
  // Befehls, sonst Video- bzw. Medien-Workflow)
  const senders = [telegram.trim() && "Telegram", instagram.trim() && "Instagram"].filter(Boolean);
  const modeLabel = Object.fromEntries(MODES);
  const notProduction = Object.values(modes).filter((m) => m !== "production").map((m) => modeLabel[m] ?? m);
  const identityHint = [senders.length ? senders.join(" + ") : "kein Absender", processCommands ? "" : "Befehle aus", ...new Set(notProduction)]
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
          commandWorkflows: COMMANDS.filter((c) => !same(profiles[c], undefined)).map((c) => {
            const p = profiles[c] ?? EMPTY;
            return { command: c, workflow: p.workflow, format: p.format, durationS: Number(p.duration) || 0, finish: p.finish };
          }),
          clonerCandidates: Number(candidates) || 0,
          testDelay,
          cancelWord: cancelWord.trim(),
          accountModes: Object.entries(modes)
            .filter(([k, m]) => m !== savedModes[k])
            .map(([key, mode]) => ({ key, mode })),
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
    aria?: string,
    suggest = "",
  ) {
    return (
      <div className={aria ? "g-field g-sub" : "g-field"}>
        <label htmlFor={id}>{label}</label>
        <select id={id} aria-label={aria} value={value} onChange={(e) => set(e.target.value)}>
          <option value="">{none}</option>
          {options.map((w) => (
            <option key={w.key} value={w.key}>
              {suggest && w.cloner.includes(suggest) ? `${w.title} · Vorschlag` : w.title}
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
        {contact.accountModes.map((m) => {
          const ch = channels.find((c) => c.key === m.key);
          const id = `df-mode-${m.key}`;
          return (
            <div key={m.key} className="g-field">
              <label htmlFor={id}>
                Betriebsart {PLATFORM_LABEL[ch?.platform ?? ""] ?? ""} · {m.key}
              </label>
              <select id={id} value={modes[m.key] ?? m.mode} onChange={(e) => setModes((x) => ({ ...x, [m.key]: e.target.value }))}>
                {MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
        <div className="g-field">
          <label htmlFor="df-cancel">Chat-Wort Abbrechen</label>
          <input id="df-cancel" value={cancelWord} placeholder="aus" onChange={(e) => setCancelWord(e.target.value)} />
        </div>
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
        <div className="g-field">
          <label htmlFor="df-candidates">Kandidaten je Bild</label>
          <input
            id="df-candidates"
            type="number"
            min={1}
            max={12}
            step={1}
            value={candidates}
            placeholder={`Vorgabe ${contact.clonerCandidatesDefault}`}
            onChange={(e) => setCandidates(e.target.value)}
          />
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
          const p = profiles[c] ?? EMPTY;
          // Ausgabeprofil (SP1 Schritt 6): Formate der Engine des wirksamen Workflows
          const effective = registry.find((w) => w.key === (p.workflow || base));
          return (
            <div key={c} className="g-cmd">
              {choice(
                `df-cmd-${c}`,
                c,
                p.workflow,
                (v) => setProfile(c, { workflow: v }),
                c === "animate" ? videos : media,
                base ? `wie ${label}` : `kein Workflow (${label} fehlt)`,
                undefined,
                c, // Vorschlag aus dem Manifest (SP3 Schritt 8) in der Auswahl markiert
              )}
              {effective?.formats.length ? (
                <div className="g-field g-sub">
                  <label htmlFor={`df-fmt-${c}`}>Format</label>
                  <select id={`df-fmt-${c}`} aria-label={`Format ${c}`} value={p.format} onChange={(e) => setProfile(c, { format: e.target.value })}>
                    <option value="">wie Vorlage</option>
                    {effective.formats.map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              {c === "animate" ? (
                <div className="g-field g-sub">
                  <label htmlFor="df-dur-animate">Dauer s</label>
                  <input
                    id="df-dur-animate"
                    aria-label="Dauer animate (s)"
                    type="number"
                    min={1}
                    step={1}
                    value={p.duration}
                    placeholder="Standard"
                    onChange={(e) => setProfile(c, { duration: e.target.value })}
                  />
                </div>
              ) : (
                choice(`df-fin-${c}`, "Ausgabe", p.finish, (v) => setProfile(c, { finish: v }), finishers, "ohne Fertigstellen", `Fertigstellen ${c}`)
              )}
            </div>
          );
        })}
      </Fold>
      <Fold
        id="test"
        title="Kundentest"
        hint={`Sitzung ${contact.testSession}${Object.values(modes).includes("test") ? " · aktiv" : ""}`}
        warn={false}
        changed={testDelay !== contact.testDelay}
        folds={folds}
        toggle={toggle}
      >
        <label className="g-switch">
          <input type="checkbox" checked={testDelay} onChange={(e) => setTestDelay(e.target.checked)} />
          Verzögerung wie Kunde
        </label>
        <button
          type="button"
          className="g-button"
          disabled={!live || reset.pending}
          onClick={() => void reset.run({ case: "testReset", value: {} }, { done: "Kundentest zurückgesetzt." })}
        >
          Zurücksetzen
        </button>
        {reset.notice ? <small role="status">{reset.notice}</small> : null}
        <table className="g-table" aria-label="Messwerte Kundentest">
          <thead>
            <tr>
              <th>Lauf</th>
              <th>Gesamt s</th>
              <th>Warten s</th>
              <th>Rechnen s</th>
            </tr>
          </thead>
          <tbody>
            {testRuns.length ? (
              testRuns.map((r) => (
                <tr key={String(r.runId)}>
                  <td>#{String(r.runId)}</td>
                  <td>{r.totalS.toFixed(1)}</td>
                  <td>{r.waitS.toFixed(1)}</td>
                  <td>{r.durationS.toFixed(1)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4}>Noch keine Testantwort in dieser Sitzung.</td>
              </tr>
            )}
          </tbody>
        </table>
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
