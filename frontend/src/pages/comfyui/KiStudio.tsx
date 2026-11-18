import { type FormEvent, useEffect, useState } from "react";
import { useCommand } from "../../core/commands";
import type { AiRun } from "../../core/generated/darkfluenzer/v1/ai_pb";
import type { WorkflowInfo } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import type { Influencer, PersonaVersion } from "../../core/generated/darkfluenzer/v1/influencer_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useEventTopic, useStateTopic } from "../../core/state";

// KI-Studio (FRONTEND §3.4, F7.9, Backend SP4): innere Ansichten ändern nur die Mitte. Persona ist
// das versionierte Promptprofil je Influencerin (SP4 Schritt 2, Befehle 35/68). Chat-Test läuft mit
// dem registrierten Sprachworkflow auf ComfyUI 2 (SP4 Schritt 1, Befehle 49/50, EVENT 31) und zeigt
// je Lauf Antwort, Einstufung (E26), Messwerte und den tatsächlich verwendeten Prompt. Gedächtnis
// (Schritt 5) und Vergleich (neue Modellfreigabe) bleiben gesperrt – keine fingierten Ergebnisse.

type View = "chat" | "persona" | "memory" | "compare";

const VIEWS: readonly [View, string, string][] = [
  ["chat", "Chat-Test", "Sprachworkflow noch nicht eingerichtet (SP4 Schritt 1)."],
  ["persona", "Persona", ""],
  ["memory", "Gedächtnis", "Gedächtnis folgt mit SP4 Schritt 5."],
  ["compare", "Vergleich", "Vergleich ist bis zu einer weiteren Modellfreigabe gesperrt (B5)."],
];

const seconds = (s: number) => `${s.toFixed(1).replace(".", ",")} s`;

// Folgen der Einstufung (SP4 Schritt 4); im Studio nur angezeigt, ausgeführt ab der Kundenkette
const CONSEQUENCE: Record<string, [string, "ok" | "warn" | "bad"]> = {
  lock_minor: ["SPERRE", "bad"],
  no_order_explicit: ["KEIN AUFTRAG (EXPLIZIT)", "warn"],
  offer_ready: ["ANGEBOT BEREIT", "ok"],
};

const GATE_LABEL: Record<string, string> = {
  schema: "Einstufung",
  minor: "Alter",
  amounts: "Beträge",
  payment_ways: "Zahlungswege",
  ai_notice: "KI-Hinweis",
  locked: "Sperre",
  operator: "Betreiber",
  automation: "Automatik",
  window: "Antwortfenster",
  text_limit: "Textlänge",
};

function versionDate(v: PersonaVersion): string {
  return new Date(Number(v.createdMs)).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

export function KiStudio({ workflow, live }: { workflow?: WorkflowInfo; live: boolean }) {
  const [view, setView] = useState<View>(workflow ? "chat" : "persona");
  const [testVersion, setTestVersion] = useState(0);
  // Befehlszustand über dem Editor: die Rückmeldung bleibt, wenn der Editor nach dem Aktivieren neu startet
  const profileCmd = useCommand();
  const state = useStateTopic(Topic.INFLUENCERS)?.value;
  const influencers = state?.influencers ?? [];
  const [chosen, setChosen] = useState<bigint | null>(null);
  const current = influencers.find((i) => i.influencerId === chosen) ?? influencers[0];
  const blocked = view === "chat" && workflow ? "" : (VIEWS.find(([v]) => v === view)?.[2] ?? "");
  return (
    <div className="g-workmain">
      {workflow ? <h2>{workflow.title}</h2> : null}
      {workflow ? <small>{workflow.engineTitle}</small> : null}
      <div className="g-subtabs" role="tablist" aria-label="KI-Studio">
        {VIEWS.map(([v, label]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}>
            {label}
          </button>
        ))}
      </div>
      {!state ? (
        <p className="g-note">Lädt …</p>
      ) : !current ? (
        <p className="g-note">Noch keine Influencerin angelegt (Nachrichten → Influencerin-Block).</p>
      ) : blocked ? (
        <p className="g-note">{blocked}</p>
      ) : (
        <>
          {influencers.length > 1 ? (
            <div className="g-field">
              <label htmlFor="ki-figure">Influencerin</label>
              <select id="ki-figure" value={String(current.influencerId)} onChange={(e) => setChosen(BigInt(e.target.value))}>
                {influencers.map((i) => (
                  <option key={String(i.influencerId)} value={String(i.influencerId)}>
                    {i.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {view === "chat" && workflow ? (
            <ChatTest key={String(current.influencerId)} influencer={current} workflow={workflow} live={live} version={testVersion} setVersion={setTestVersion} />
          ) : (
            <ProfileEditor
              key={`${current.influencerId}-${current.personaActive}`}
              influencer={current}
              blocks={state.profileBlocks}
              honesty={state.honestyRule}
              schema={state.assessmentSchema}
              cmd={profileCmd}
              onTest={
                workflow
                  ? (v) => {
                      setTestVersion(v);
                      setView("chat");
                    }
                  : undefined
              }
            />
          )}
        </>
      )}
    </div>
  );
}

/** Chat-Test (SP4 Schritt 1): Nachricht an den Sprachworkflow mit gewählter Profilversion; der
 *  Verlauf ist die Studio-Sitzung im Backend. Ergebnisse kommen als EVENT 31 (kein Polling). */
function ChatTest({
  influencer,
  workflow,
  live,
  version,
  setVersion,
}: {
  influencer: Influencer;
  workflow: WorkflowInfo;
  live: boolean;
  version: number;
  setVersion: (v: number) => void;
}) {
  const cmd = useCommand();
  const reset = useCommand();
  const results = useEventTopic(Topic.AI_RESULT);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Record<string, string>>({});
  const runs = (results?.items ?? []).map((e) => e.value.run).filter((r): r is AiRun => !!r && r.kind === "studio" && r.influencerId === influencer.influencerId);
  const session = influencer.studioSession; // laufende Sitzung laut Backend (STATE 9)
  const shown = runs.filter((r) => r.session === session);
  const done = new Set(runs.map((r) => r.requestId));
  const waiting = Object.entries(pending).filter(([id]) => !done.has(id));
  const versions = influencer.personaVersions;
  const usable = influencer.personaActive > 0 || versions.length > 0;

  async function send(e: FormEvent) {
    e.preventDefault();
    const message = text.trim();
    const res = await cmd.run(
      { case: "studioChat", value: { influencerId: influencer.influencerId, version, text: message, workflow: workflow.key } },
      { acceptedOnly: true },
    );
    if (res) {
      setPending((p) => ({ ...p, [res.requestId]: message }));
      setText("");
    }
  }

  async function newSession() {
    if (await reset.run({ case: "studioSessionReset", value: { influencerId: influencer.influencerId } }, { done: "Neue Sitzung." })) {
      setPending({});
    }
  }

  return (
    <div className="g-form">
      <div className="g-field">
        <label htmlFor="ki-version">Profilversion</label>
        <select id="ki-version" value={version} onChange={(e) => setVersion(Number(e.target.value))}>
          <option value={0}>Aktive Version{influencer.personaActive ? ` (${influencer.personaActive})` : ""}</option>
          {[...versions].reverse().map((v) => (
            <option key={v.version} value={v.version}>
              Version {v.version}
              {v.note ? ` · ${v.note}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="g-field">
        <span>Sitzung {session}</span>
        <button type="button" className="g-button" disabled={!live || reset.pending} onClick={() => void newSession()}>
          Neue Sitzung
        </button>
      </div>
      <div className="g-stream g-wide" aria-label="Chat-Test">
        {shown.map((r) => (
          <div key={String(r.runId)} className="g-turn">
            <div className="g-bubble" data-dir="in">
              <p>{r.message}</p>
            </div>
            {r.error ? (
              <p className="g-note g-error">{r.error}</p>
            ) : (
              <div className="g-bubble" data-dir="out">
                <p>{r.answer}</p>
                <small>
                  Version {r.personaVersion} · Warteschlange {seconds(r.waitS)} · Lauf {seconds(r.durationS)} · gesamt {seconds(r.totalS)}
                  {r.attempts > 1 ? ` · ${r.attempts} Läufe (Einstufung ungültig)` : ""}
                </small>
              </div>
            )}
            {r.assessment ? (
              // strukturierte Einstufung (SP4 Schritt 4) und autorisierte Folgen
              <p className="g-gates">
                {r.consequences.map((c) => (
                  <span key={c} className="g-badge" data-tone={CONSEQUENCE[c]?.[1] ?? "neutral"}>
                    {CONSEQUENCE[c]?.[0] ?? c}
                  </span>
                ))}
                <small>
                  Kaufbereitschaft {r.assessment.purchaseReadiness}/3
                  {r.assessment.wishDescription ? ` · Wunsch: ${r.assessment.wishDescription}` : ""}
                  {r.assessment.explicitWish ? " · expliziter Wunsch" : ""}
                  {r.assessment.minorHint ? ` · Hinweis minderjährig${r.assessment.minorEvidence ? `: ${r.assessment.minorEvidence}` : ""}` : ""}
                  {r.assessment.intent ? ` · ${r.assessment.intent}` : ""}
                </small>
              </p>
            ) : null}
            {r.gates.length ? (
              // Gates vor dem Versand (SP4 Schritt 3): im Studio wird nie gesendet, nur bewertet
              <p className="g-gates">
                <span className="g-badge" data-tone={r.sendable ? "ok" : "warn"}>
                  {r.sendable ? "WÜRDE GESENDET" : "ENTWURF"}
                </span>
                <small>
                  {r.sendable
                    ? `Gates bestanden: ${r.gates.map((g) => GATE_LABEL[g.name] ?? g.name).join(", ")}`
                    : r.gates
                        .filter((g) => !g.ok)
                        .map((g) => g.reason)
                        .join(" · ")}
                </small>
              </p>
            ) : null}
            <details className="g-checks">
              <summary>
                Einstufung {r.classificationValid ? "gültig" : "ungültig"} · Prompt
              </summary>
              <small className="g-line">
                <span>Einstufung (E26)</span>
              </small>
              <pre className="g-pre">{r.classification || "–"}</pre>
              <small className="g-line">
                <span>Systemprompt</span>
              </small>
              <pre className="g-pre">{r.systemPrompt || "–"}</pre>
              <small className="g-line">
                <span>Nutzertext</span>
              </small>
              <pre className="g-pre">{r.userText || "–"}</pre>
              <small title={`Workflow ${r.workflowSha} · Modell ${r.modelSha}`}>
                {r.workflow} · Graph {r.workflowSha.slice(0, 12)}
              </small>
            </details>
          </div>
        ))}
        {waiting.map(([id, message]) => (
          <div key={id} className="g-turn">
            <div className="g-bubble" data-dir="in">
              <p>{message}</p>
            </div>
            <p className="g-note">läuft auf ComfyUI 2 …</p>
          </div>
        ))}
        {shown.length === 0 && waiting.length === 0 ? <p className="g-note">Noch keine Testnachricht in dieser Sitzung.</p> : null}
      </div>
      <form className="g-compose g-wide" onSubmit={(e) => void send(e)}>
        <label htmlFor="ki-message" className="g-sr-only">
          Testnachricht
        </label>
        <textarea id="ki-message" rows={2} value={text} placeholder="Testnachricht als Kunde" onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="g-button g-primary g-block" disabled={!live || cmd.pending || !text.trim() || !usable}>
          Senden
        </button>
      </form>
      {!usable ? <p className="g-note g-wide">Erst ein Promptprofil speichern (Ansicht Persona).</p> : null}
      {cmd.notice || reset.notice ? (
        <p className="g-note g-wide" role="status">
          {cmd.notice || reset.notice}
        </p>
      ) : null}
    </div>
  );
}

function ProfileEditor({
  influencer,
  blocks,
  honesty,
  schema,
  cmd,
  onTest,
}: {
  influencer: Influencer;
  blocks: readonly { key: string; label: string }[];
  honesty: string;
  schema: string;
  cmd: ReturnType<typeof useCommand>;
  onTest?: (version: number) => void;
}) {
  const versions = influencer.personaVersions;
  const active = versions.find((v) => v.version === influencer.personaActive);
  const [base, setBase] = useState<PersonaVersion | undefined>(active);
  const [text, setText] = useState<Record<string, string>>(() => ({ ...(active?.blocks ?? {}) }));
  const [note, setNote] = useState("");
  const [compare, setCompare] = useState<PersonaVersion | null>(null);
  useEffect(() => setCompare(null), [influencer.personaActive]);
  const changed = blocks.some((b) => (text[b.key] ?? "").trim() !== (base?.blocks[b.key] ?? "").trim());

  function load(v: PersonaVersion) {
    setBase(v);
    setText({ ...v.blocks });
  }

  async function save(activate: boolean) {
    const done = await cmd.run(
      {
        case: "influencerUpdate",
        value: {
          influencerId: influencer.influencerId,
          revision: influencer.revision,
          name: influencer.name,
          characterId: influencer.characterId,
          persona: influencer.persona,
          aiNotice: influencer.aiNotice,
          prices: influencer.prices,
          profile: { blocks: Object.fromEntries(Object.entries(text).filter(([, v]) => v.trim())), params: active?.params ?? {}, note, activate },
        },
      },
      { done: activate ? "Gespeichert und aktiviert." : "Als neue Version gespeichert." },
    );
    if (done) setNote("");
  }

  async function activate(v: PersonaVersion) {
    await cmd.run(
      { case: "promptProfileActivate", value: { influencerId: influencer.influencerId, version: v.version } },
      { done: `Version ${v.version} aktiv.` },
    );
  }

  return (
    <div className="g-form">
      <p className="g-note g-wide">
        {active ? `Aktiv: Version ${active.version}` : "Noch keine aktive Version"}
        {base && base.version !== active?.version ? ` · im Editor: Version ${base.version}` : ""}
      </p>
      {blocks.map((b) => (
        <div key={b.key} className="g-field g-wide">
          <label htmlFor={`ki-${b.key}`}>{b.label}</label>
          <textarea id={`ki-${b.key}`} rows={b.key === "persona" || b.key === "system_prompt" ? 5 : 3} value={text[b.key] ?? ""} onChange={(e) => setText({ ...text, [b.key]: e.target.value })} />
          {b.key === "classification" && schema ? (
            <small>
              Schema-Vertrag: <code className="g-schema">{schema}</code>
            </small>
          ) : null}
        </div>
      ))}
      <div className="g-field g-wide">
        <label>Ehrlichkeitsblock (fest im Sprachworkflow)</label>
        <small>{honesty || "kein registrierter Sprachworkflow"}</small>
      </div>
      <div className="g-field g-wide">
        <label htmlFor="ki-note">Notiz zur Version</label>
        <input id="ki-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <div className="g-actions g-wide">
        <button type="button" className="g-button" disabled={cmd.pending || !changed} onClick={() => void save(false)}>
          Persona übernehmen
        </button>
        <button type="button" className="g-button g-primary" disabled={cmd.pending || !changed} onClick={() => void save(true)}>
          Übernehmen und aktivieren
        </button>
        <button
          type="button"
          className="g-button"
          disabled={!onTest || !base}
          title={onTest ? "Gespeicherte Version im Chat-Test ausführen" : "Chat-Test braucht den Sprachworkflow (SP4 Schritt 1)"}
          onClick={() => base && onTest?.(base.version)}
        >
          Im Test ausführen
        </button>
      </div>
      {cmd.notice ? (
        <p className="g-note g-wide" role="status">
          {cmd.notice}
        </p>
      ) : null}
      <div className="g-field g-wide">
        <label>Versionen</label>
        {[...versions].reverse().map((v) => (
          <span key={v.version} className="g-version-row">
            <span className="g-ellipsis">
              Version {v.version} · {versionDate(v)}
              {v.note ? ` · ${v.note}` : ""}
            </span>
            {v.version === influencer.personaActive ? (
              <span className="g-badge" data-tone="ok">
                AKTIV
              </span>
            ) : (
              <span />
            )}
            <button type="button" className="g-button" onClick={() => load(v)}>
              Laden
            </button>
            <button type="button" className="g-button" disabled={!active || v.version === active.version} onClick={() => setCompare(compare?.version === v.version ? null : v)}>
              Vergleichen
            </button>
            <button type="button" className="g-button" disabled={cmd.pending || v.version === influencer.personaActive} onClick={() => void activate(v)}>
              {active && v.version < active.version ? "Zurücksetzen" : "Aktivieren"}
            </button>
          </span>
        ))}
        {versions.length === 0 ? <small>Noch keine Version gespeichert.</small> : null}
      </div>
      {compare && active ? (
        <div className="g-field g-wide">
          <label>
            Version {compare.version} gegen aktive Version {active.version}
          </label>
          {blocks
            .filter((b) => (compare.blocks[b.key] ?? "") !== (active.blocks[b.key] ?? ""))
            .map((b) => (
              <details key={b.key} className="g-details" open>
                <summary>{b.label}</summary>
                <p className="g-diff">
                  <small>Version {compare.version}</small> {compare.blocks[b.key] || "(leer)"}
                </p>
                <p className="g-diff">
                  <small>Version {active.version}</small> {active.blocks[b.key] || "(leer)"}
                </p>
              </details>
            ))}
        </div>
      ) : null}
    </div>
  );
}
