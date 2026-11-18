import { type FormEvent, useEffect, useRef, useState } from "react";
import { Instances, readyUrl } from "./comfyui/Instances";
import { KiStudio } from "./comfyui/KiStudio";
import { Queue } from "./comfyui/Queue";
import { type RenderIntent, takeProductionIntent, takeRenderIntent } from "../core/intent";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { Workbench } from "./comfyui/Workbench";
import type { WorkflowInfo } from "../core/generated/darkfluenzer/v1/comfy_pb";
import { useCommand } from "../core/commands";
import { useConnection } from "../core/realtime";
import { useStateTopic } from "../core/state";

type Kind = "image" | "video" | "ai";

const KINDS: readonly [Kind, string][] = [
  ["image", "Fotos"],
  ["video", "Videos"],
  ["ai", "KI"],
];

/** Unterregister eines Workflows: KI-Instanz (ComfyUI 2) bzw. Foto/Video der Medieninstanz. */
function tabOf(w: WorkflowInfo): Kind {
  return w.instance === "ai" ? "ai" : (w.kind as Kind);
}

// Gruppen der Workflowliste (GUI-Prüfung 18.11. Punkt 6) nach Aufgabe, aus echten Registry-Feldern:
// Training, Rolle der Engine (analysis, upscale, output), Art (Video) und Eingangsbild (Upload ohne
// Vorlage = Bearbeiten). Zweiter Wert: anfangs geöffnet.
const GROUPS: readonly [string, boolean][] = [
  ["Erzeugen", true],
  ["Bearbeiten", true],
  ["Bild zu Video", true],
  ["Sprache", true],
  ["Fertigstellen", false],
  ["Analysieren & Prüfen", false],
  ["Training", false],
];

function groupOf(w: WorkflowInfo): string {
  if (w.training) return "Training";
  if (w.role === "analysis") return "Analysieren & Prüfen";
  if (w.role === "upscale" || w.role === "output") return "Fertigstellen";
  if (w.instance === "ai") return "Sprache";
  if (w.kind === "video") return "Bild zu Video";
  if (w.params.some((p) => p.upload && !p.reference)) return "Bearbeiten";
  return "Erzeugen";
}

export function ComfyUI() {
  const instances = useStateTopic(Topic.COMFY_INSTANCES);
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value;
  const workflows = registry?.workflows ?? [];
  const version = registry?.version ?? 0n;
  const connection = useConnection();
  const [kind, setKind] = useState<Kind>("image");
  const [selected, setSelected] = useState<Record<Kind, string>>({ image: "", video: "", ai: "" });
  const [draft, setDraft] = useState<{ key: string; params: Record<string, string>; n: number } | null>(null);
  const [groupsOpen, setGroupsOpen] = useState<Record<string, boolean>>({});
  const [intent] = useState<RenderIntent | null>(takeRenderIntent);
  const [orderIntent] = useState(takeProductionIntent);
  const canLoad = (key: string) => workflows.some((w) => w.key === key);

  function loadDraft(key: string, params: Record<string, string>) {
    const wf = workflows.find((w) => w.key === key);
    if (!wf) return;
    setKind(tabOf(wf));
    setSelected((s) => ({ ...s, [tabOf(wf)]: wf.key }));
    setDraft((d) => ({ key, params, n: (d?.n ?? 0) + 1 }));
  }

  const live = connection.status === "OPEN" && instances?.staleSince === null;
  const hasAi = instances?.value.instances.some((i) => i.name === "ai") ?? false;
  useEffect(() => {
    // Übergabe aus Dateien: Workflow wählen, sobald die Registry ihn meldet
    const target = intent && workflows.find((w) => w.key === intent.workflow);
    if (target) {
      setKind(tabOf(target));
      setSelected((s) => ({ ...s, [tabOf(target)]: target.key }));
    }
  }, [intent, workflows]);
  const list = workflows.filter((w) => tabOf(w) === kind);
  const current = list.find((w) => w.key === selected[kind]) ?? list[0];
  const groups = GROUPS.map(([name, initial]) => {
    const items = list.filter((w) => groupOf(w) === name);
    return [name, items, groupsOpen[name] ?? (initial || items.includes(current as WorkflowInfo))] as const;
  }).filter(([, items]) => items.length > 0);
  const item = (w: WorkflowInfo) => (
    <button
      key={w.key}
      type="button"
      role="listitem"
      className="g-wfitem"
      aria-current={w === current ? "true" : undefined}
      onClick={() => setSelected({ ...selected, [kind]: w.key })}
    >
      <strong>{w.title}</strong>
      <small>
        {w.enabled ? "" : "deaktiviert · "}
        {w.modelsReady ? "bereit" : `fehlt ${w.missingGb.toFixed(1)} GB`} · {w.status}
      </small>
    </button>
  );
  const comfyUrl = readyUrl(instances?.value.instances.find((i) => i.name === (current?.instance ?? "media")), live);
  const create = useCommand();
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [created, setCreated] = useState("");

  useEffect(() => {
    // nach dem Anlegen den neuen Workflow auswählen, sobald die Registry ihn meldet
    const fresh = workflows.find((w) => w.title === created);
    if (fresh) {
      setKind(tabOf(fresh));
      setSelected((s) => ({ ...s, [tabOf(fresh)]: fresh.key }));
      setCreated("");
    }
  }, [workflows, created]);

  function openCreate() {
    setTitle("");
    setSource(current?.key ?? "");
    dialog.current?.showModal();
  }

  async function submitCreate(e: FormEvent) {
    e.preventDefault();
    if (await create.run({ case: "createWorkflow", value: { source, title: title.trim() } }, { version })) {
      setCreated(title.trim());
      dialog.current?.close();
    }
  }

  return (
    <section className="g-panel g-flush">
      <h1 className="g-sr-only">ComfyUI</h1>
      <div className="g-subtabs" role="tablist" aria-label="Workflow-Art">
        {KINDS.filter(([k]) => k !== "ai" || hasAi).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}>
            {label} <small>{workflows.filter((w) => tabOf(w) === k).length}</small>
          </button>
        ))}
      </div>

      <div className="g-studio">
        <div className="g-wflist">
          <h2>Workflows</h2>
          <button type="button" className="g-button g-new" disabled={!live || list.length === 0} onClick={openCreate}>
            Neuer Workflow
          </button>
          {groups.length > 1
            ? groups.map(([name, items, open]) => (
                <details
                  key={name}
                  className="g-wfgroup"
                  open={open}
                  onToggle={(e) => {
                    const now = e.currentTarget.open;
                    if (now !== open) setGroupsOpen((g) => ({ ...g, [name]: now }));
                  }}
                >
                  <summary>
                    <span>{name}</span>
                    <small>{items.length}</small>
                  </summary>
                  <div role="list" aria-label={name}>
                    {items.map(item)}
                  </div>
                </details>
              ))
            : (
                <div role="list" aria-label={`${KINDS.find(([k]) => k === kind)?.[1] ?? ""}-Workflows`}>
                  {list.map(item)}
                </div>
              )}
        </div>
        {current ? (
          <Workbench
            key={`${current.key}-${draft?.key === current.key ? draft.n : 0}-${intent?.workflow === current.key ? String(intent.media.mediaId) : ""}`}
            wf={current}
            workflows={workflows}
            version={version}
            live={live}
            comfyUrl={comfyUrl}
            draft={draft?.key === current.key ? draft.params : undefined}
            start={intent?.workflow === current.key ? intent.media : undefined}
            startParam={intent?.workflow === current.key ? intent.param : undefined}
            customerOrder={orderIntent || undefined}
            onLoad={loadDraft}
            canLoad={canLoad}
          />
        ) : (
          <>
            {kind === "ai" && connection.status === "OPEN" ? (
              <KiStudio />
            ) : (
              <div className="g-workmain">
                <p className="g-note">{connection.status === "OPEN" ? "Keine registrierten Workflows." : "Keine Verbindung"}</p>
              </div>
            )}
            <aside className="g-control" aria-label="Steuerung">
              <h2>Steuerung</h2>
              <Queue instance={kind === "ai" ? "ai" : "media"} onLoad={loadDraft} canLoad={canLoad} />
              <Instances live={live} />
            </aside>
          </>
        )}
      </div>

      <dialog ref={dialog} className="g-dialog" aria-labelledby="wf-create">
        <form className="g-form" onSubmit={submitCreate}>
          <h2 id="wf-create" className="g-wide">
            Neuer Workflow
          </h2>
          <div className="g-field g-wide">
            <label htmlFor="wf-create-title">Titel</label>
            <input id="wf-create-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="g-field g-wide">
            <label htmlFor="wf-create-source">Vorlage</label>
            <select id="wf-create-source" value={source} onChange={(e) => setSource(e.target.value)}>
              {list.map((w) => (
                <option key={w.key} value={w.key}>
                  {w.title}
                </option>
              ))}
            </select>
          </div>
          {create.notice ? (
            <p className="g-note g-wide" role="alert">
              {create.notice}
            </p>
          ) : null}
          <div className="g-actions g-wide">
            <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
              Abbrechen
            </button>
            <button type="submit" className="g-button g-primary" disabled={!title.trim() || !source || create.pending}>
              Anlegen
            </button>
          </div>
        </form>
      </dialog>
    </section>
  );
}
