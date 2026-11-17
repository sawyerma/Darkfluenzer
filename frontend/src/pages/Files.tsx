import { useEffect, useRef, useState } from "react";
import { useCommand } from "../core/commands";
import type { WorkflowParam } from "../core/generated/darkfluenzer/v1/comfy_pb";
import { MediaKind, MediaOrigin, type MediaItem, type MediaProvenance } from "../core/generated/darkfluenzer/v1/media_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { setRenderIntent } from "../core/intent";
import { fetchProvenance, mediaUrl, useGallery, type GalleryStatus } from "../core/media";
import { useStateTopic } from "../core/state";

type Filter = "all" | "image" | "video";

const FILTERS: readonly [Filter, string][] = [
  ["all", "Alle"],
  ["image", "Fotos"],
  ["video", "Videos"],
];
const EMPTY: Record<Filter, string> = { all: "Noch keine Dateien.", image: "Keine Fotos.", video: "Keine Videos." };
const ORIGIN: Record<MediaOrigin, string> = {
  [MediaOrigin.UNSPECIFIED]: "–",
  [MediaOrigin.RENDER]: "Renderjob",
  [MediaOrigin.EVALUATION]: "Evaluation",
  [MediaOrigin.COMFYUI]: "ComfyUI",
  [MediaOrigin.ORDER]: "Kundenauftrag",
};
const STATUS_NOTE: Record<Exclude<GalleryStatus, "ready">, string> = { loading: "Lädt …", offline: "Keine Verbindung" };

function matches(m: MediaItem, filter: Filter): boolean {
  if (filter === "all") return true;
  return m.kind === (filter === "image" ? MediaKind.IMAGE : MediaKind.VIDEO);
}

function Medium({ item, controls }: { item: MediaItem; controls?: boolean }) {
  return item.kind === MediaKind.VIDEO ? (
    <video src={mediaUrl(item.path)} controls={controls} muted={!controls} preload="metadata" />
  ) : (
    <img src={mediaUrl(item.path)} alt={item.caption} loading="lazy" />
  );
}

/** Galerie-Auswahl eines Bildes (z. B. Start-/Quellbild im Renderformular). */
export function MediaPicker({ title, onPick, onClose }: { title: string; onPick: (item: MediaItem) => void; onClose: () => void }) {
  const gallery = useGallery();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => dialog.current?.showModal(), []);
  const images = gallery.items.filter((m) => m.kind === MediaKind.IMAGE);
  return (
    <dialog ref={dialog} className="g-dialog g-media" aria-labelledby="media-pick" onClose={onClose}>
      <div className="g-line g-head">
        <h2 id="media-pick">{title}</h2>
        <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
          Schließen
        </button>
      </div>
      {images.length > 0 ? (
        <div className="g-gallery">
          {images.map((m) => (
            <div key={String(m.mediaId)} className="g-tile">
              <button
                type="button"
                className="g-tile-open"
                title={`local/${m.path}`}
                onClick={() => {
                  onPick(m);
                  dialog.current?.close();
                }}
              >
                <Medium item={m} />
                <span>{m.caption}</span>
                <small>{m.path.split("/").pop()}</small>
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="g-note">{gallery.status === "ready" ? EMPTY.image : STATUS_NOTE[gallery.status]}</p>
      )}
      {gallery.error ? (
        <p className="g-note" role="alert">
          {gallery.error}
        </p>
      ) : null}
      {gallery.more ? (
        <div className="g-actions">
          <button type="button" className="g-button" disabled={gallery.loading} onClick={() => void gallery.loadOlder()}>
            Ältere laden
          </button>
        </div>
      ) : null}
    </dialog>
  );
}

const SEED_MAX = 4294967295n;
const short = (sha: string) => sha.slice(0, 16);

/** Neuer Seed im erlaubten Bereich des Workflow-Parameters (Variieren). */
function randomSeed(p: WorkflowParam): bigint {
  const max = p.max !== undefined ? BigInt(Math.floor(p.max)) : SEED_MAX;
  return BigInt(crypto.getRandomValues(new Uint32Array(1))[0]!) % (max + 1n);
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Detailansicht (F7.6): Herkunft aus dem Job-Journal und Graph-Snapshot, Weiterverarbeiten. */
function MediaDetail({
  item,
  choose,
  known,
  onOpen,
  onClose,
}: {
  item: MediaItem;
  /** Workflow-Auswahl „Weiterverarbeiten“ gleich geöffnet (Kachel-Schaltfläche, F7.6) */
  choose: boolean;
  known: (id: bigint) => MediaItem | undefined;
  onOpen: (item: MediaItem) => void;
  onClose: () => void;
}) {
  const [prov, setProv] = useState<MediaProvenance | null>(null);
  const [error, setError] = useState("");
  const [choosing, setChoosing] = useState(choose);
  useEffect(() => setChoosing(choose), [item.mediaId, choose]);
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value;
  const workflows = registry?.workflows ?? [];
  const cmd = useCommand();
  useEffect(() => {
    let alive = true;
    setProv(null);
    setError("");
    fetchProvenance(item.mediaId)
      .then((p) => alive && setProv(p))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [item.mediaId]);

  const isImage = item.kind === MediaKind.IMAGE;
  const takes = isImage ? workflows.filter((w) => w.enabled && w.params.some((p) => p.upload && p.name === "image")) : [];
  const toVideo = takes.find((w) => w.kind === "video");
  const toUpscale = takes.find((w) => w.role === "upscale");
  // „Als Vorlage“ (F7.6, C1): erster bereite Workflow mit Vorlagen-Parameter
  const asTemplate = isImage
    ? workflows.find((w) => w.enabled && w.modelsReady && w.params.some((p) => p.reference))
    : undefined;
  const source = prov?.jobId ? workflows.find((w) => w.key === prov.workflow && w.enabled) : undefined;
  const seed = source?.params.find((p) => p.name === "seed");
  const parent = prov?.parentMediaId ? known(prov.parentMediaId) : undefined;
  const m = prov?.memory;

  async function repeat(vary: boolean) {
    if (!prov || !source || !registry) return;
    const values = vary && seed ? [{ name: "seed", value: { case: "integer" as const, value: randomSeed(seed) } }] : [];
    const done = await cmd.run(
      { case: "render", value: { workflow: source.key, values, files: [], parentMediaId: item.mediaId, repeatJobId: prov.jobId } },
      { version: registry.version, acceptedOnly: true, done: vary ? "Variante eingereiht." : "Wiederholung eingereiht." },
    );
    if (done) onClose();
  }

  return (
    <div className="g-media-body">
      <Medium item={item} controls />
      <div>
        <h2>{item.caption}</h2>
        <dl className="g-params">
          <Row label="Zeit">{new Date(Number(item.createdUnixMs)).toLocaleString("de-DE")}</Row>
          <Row label="Herkunft">{ORIGIN[item.origin]}</Row>
          {item.orderNo ? (
            <Row label="Kundenauftrag">
              {item.orderNo} · {item.customerNo}
            </Row>
          ) : null}
          <Row label="Datei">
            local/{item.path} · {(Number(item.size) / 1e6).toFixed(1)} MB
          </Row>
          <Row label="SHA-256">{short(item.sha256)}</Row>
          {item.width ? (
            <Row label="Abmessungen">
              {item.width} × {item.height}
              {item.nativeWidth && (item.nativeWidth !== item.width || item.nativeHeight !== item.height)
                ? ` · nativ ${item.nativeWidth} × ${item.nativeHeight} (hochskaliert/Ausgabeformat)`
                : item.nativeWidth
                  ? " · nativ"
                  : " · native Größe unbekannt"}
            </Row>
          ) : null}
          <Row label="Inhaltsstufe">
            {item.contentTier === "standard" ? "standard" : item.contentTier === "explizit" ? "explizit" : "unbekannt – gilt als explizit"}
          </Row>
          {prov?.jobId ? (
            <>
              <Row label="Auftrag">
                {String(prov.jobId)} · {prov.workflowTitle || prov.workflow}
              </Row>
              <Row label="Engine">{prov.engine}</Row>
              {prov.durationS ? <Row label="Dauer">{prov.durationS.toFixed(1)} s</Row> : null}
              {prov.workflowSha256 ? <Row label="Workflow-Datei">{short(prov.workflowSha256)}</Row> : null}
              {prov.parentMediaId ? (
                <Row label="Aus Medium">
                  {parent ? (
                    <button type="button" className="g-row" onClick={() => onOpen(parent)}>
                      {parent.caption}
                    </button>
                  ) : (
                    `${String(prov.parentMediaId)} (nicht geladen oder gelöscht)`
                  )}
                </Row>
              ) : null}
              {Object.entries(prov.params).map(([k, v]) => (
                <Row key={k} label={k}>
                  {v}
                </Row>
              ))}
              {prov.inputs.map((i) => (
                <Row key={i.param} label={`Eingabe ${i.param}`}>
                  {i.path.split("/").pop()} · {short(i.sha256)}
                </Row>
              ))}
              {prov.models.map((md) => (
                <Row key={md.file} label="Modell">
                  {md.file} · {md.repo}@{md.revision.slice(0, 7)} · {short(md.sha256)}
                </Row>
              ))}
              {m && m.ramTotalGb ? (
                <Row label="Speicher">
                  frei {m.ramFreeStartGb} → min {m.ramFreeMinGb} → {m.ramFreeEndGb} GB · Swap {m.swapStartMb} / max {m.swapMaxMb} MB
                </Row>
              ) : null}
            </>
          ) : null}
          {prov && prov.childMediaIds.length > 0 ? (
            <Row label="Abgeleitete Versionen">
              {prov.childMediaIds.map((id) => {
                const child = known(id);
                return child ? (
                  <button key={String(id)} type="button" className="g-row" onClick={() => onOpen(child)}>
                    {child.caption}
                  </button>
                ) : (
                  <span key={String(id)}>{String(id)} (nicht geladen)</span>
                );
              })}
            </Row>
          ) : null}
        </dl>
        {prov && prov.graph.length > 0 ? (
          <details className="g-expert">
            <summary>Graph-Snapshot ({prov.graph.length} Nodes)</summary>
            <dl className="g-params">
              {prov.graph.map((n) => (
                <Row key={n.id} label={`${n.id} ${n.classType}`}>
                  {n.inputs.map((i) => `${i.name}=${i.value}`).join(" · ")}
                </Row>
              ))}
            </dl>
          </details>
        ) : null}
        {error ? (
          <p className="g-note" role="alert">
            {error}
          </p>
        ) : null}
        <div className="g-actions">
          {takes.length > 0 ? (
            <button type="button" className="g-button" onClick={() => setChoosing(!choosing)}>
              Weiterverarbeiten
            </button>
          ) : null}
          {source ? (
            <>
              <button type="button" className="g-button" disabled={cmd.pending} onClick={() => void repeat(false)}>
                Wiederholen
              </button>
              {seed ? (
                <button type="button" className="g-button" disabled={cmd.pending} onClick={() => void repeat(true)}>
                  Variieren
                </button>
              ) : null}
            </>
          ) : null}
          {asTemplate ? (
            <button
              type="button"
              className="g-button"
              onClick={() =>
                setRenderIntent({ workflow: asTemplate.key, media: item, param: asTemplate.params.find((p) => p.reference)?.name })
              }
            >
              Als Vorlage
            </button>
          ) : null}
          {toUpscale ? (
            <button type="button" className="g-button" onClick={() => setRenderIntent({ workflow: toUpscale.key, media: item })}>
              Hochskalieren
            </button>
          ) : null}
          {toVideo ? (
            <button type="button" className="g-button" onClick={() => setRenderIntent({ workflow: toVideo.key, media: item })}>
              Video erstellen
            </button>
          ) : null}
          {item.contentTier !== "explizit" ? (
            <button
              type="button"
              className="g-button"
              disabled={cmd.pending}
              onClick={() => void cmd.run({ case: "mediaContentTier", value: { mediaId: item.mediaId } }, { done: "Als explizit markiert." })}
            >
              Als explizit markieren
            </button>
          ) : null}
          <a className="g-button" href={mediaUrl(item.path)} target="_blank" rel="noreferrer">
            Öffnen
          </a>
          <a className="g-button" href={`${mediaUrl(item.path)}?download=1`}>
            Herunterladen
          </a>
          <button type="button" className="g-button" onClick={onClose}>
            Schließen
          </button>
        </div>
        {choosing ? (
          <div className="g-actions">
            {takes.map((w) => (
              <button key={w.key} type="button" className="g-button" onClick={() => setRenderIntent({ workflow: w.key, media: item })}>
                {w.title}
              </button>
            ))}
          </div>
        ) : null}
        {cmd.notice ? (
          <p className="g-note" role="alert">
            {cmd.notice}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function Files() {
  const gallery = useGallery();
  const items = gallery.items;
  const cmd = useCommand();
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<MediaItem | null>(null);
  const [choose, setChoose] = useState(false);
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const processable = workflows.some((w) => w.enabled && w.params.some((p) => p.upload && p.name === "image"));
  const [marked, setMarked] = useState<ReadonlySet<bigint>>(new Set());
  const dialog = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLDialogElement>(null);
  const shown = items.filter((m) => matches(m, filter));
  const deletable = shown.filter((m) => !m.orderNo); // Kundenmedien sind nicht löschbar
  const chosen = deletable.filter((m) => marked.has(m.mediaId));
  const allMarked = deletable.length > 0 && chosen.length === deletable.length;

  useEffect(() => {
    if (open && !items.some((m) => m.mediaId === open.mediaId)) dialog.current?.close();
  }, [items, open]);

  function show(item: MediaItem, next = false) {
    setOpen(item);
    setChoose(next);
    dialog.current?.showModal();
  }

  function toggle(id: bigint) {
    setMarked((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  async function remove(ids: bigint[]) {
    // Das Backend löscht vor der Antwort: angenommen = gelöscht.
    if (await cmd.run({ case: "deleteMedia", value: { mediaIds: ids } })) {
      gallery.drop(ids);
    }
  }

  return (
    <section className="g-panel">
      <h1>Dateien</h1>
      <p className="g-lead">Mediengalerie</p>
      <div className="g-toolbar">
        <div className="g-subtabs" role="tablist" aria-label="Medienart">
          {FILTERS.map(([f, label]) => (
            <button
              key={f}
              type="button"
              role="tab"
              aria-selected={filter === f}
              onClick={() => {
                setFilter(f);
                setMarked(new Set());
              }}
            >
              {label} <small>{items.filter((m) => matches(m, f)).length}</small>
            </button>
          ))}
        </div>
        {deletable.length > 0 ? (
          <span className="g-value">
            <button
              type="button"
              className="g-button"
              onClick={() => setMarked(allMarked ? new Set() : new Set(deletable.map((m) => m.mediaId)))}
            >
              {allMarked ? "Markierung aufheben" : "Alle markieren"}
            </button>
            <button
              type="button"
              className="g-button g-danger"
              disabled={chosen.length === 0 || cmd.pending}
              onClick={() => confirm.current?.showModal()}
            >
              {chosen.length > 0 ? `Löschen (${chosen.length})` : "Löschen"}
            </button>
          </span>
        ) : null}
      </div>

      {shown.length > 0 ? (
        <div className="g-gallery" data-marking={chosen.length > 0 || undefined}>
          {shown.map((m) => {
            const isMarked = !m.orderNo && marked.has(m.mediaId);
            return (
              <div key={String(m.mediaId)} className="g-tile" data-marked={isMarked || undefined}>
                <button
                  type="button"
                  className="g-tile-open"
                  onClick={() => (chosen.length > 0 && !m.orderNo ? toggle(m.mediaId) : show(m))}
                >
                  <Medium item={m} />
                  <span>{m.caption}</span>
                </button>
                {processable && m.kind === MediaKind.IMAGE ? (
                  <button type="button" className="g-button g-tile-next" onClick={() => show(m, true)}>
                    Weiterverarbeiten
                  </button>
                ) : null}
                {m.orderNo ? null : (
                  <>
                    <input
                      type="checkbox"
                      className="g-tile-mark"
                      aria-label={`${m.caption} markieren`}
                      checked={isMarked}
                      onChange={() => toggle(m.mediaId)}
                    />
                    <button
                      type="button"
                      className="g-tile-x"
                      aria-label={`${m.caption} löschen`}
                      title="Löschen"
                      disabled={cmd.pending}
                      onClick={() => void remove([m.mediaId])}
                    >
                      ×
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="g-note">{gallery.status === "ready" ? EMPTY[filter] : STATUS_NOTE[gallery.status]}</p>
      )}
      {gallery.error || cmd.notice ? (
        <p className="g-note" role="alert">
          {gallery.error || cmd.notice}
        </p>
      ) : null}
      {gallery.more ? (
        <div className="g-actions">
          <button type="button" className="g-button" disabled={gallery.loading} onClick={() => void gallery.loadOlder()}>
            Ältere laden
          </button>
        </div>
      ) : null}

      <dialog ref={confirm} className="g-dialog" aria-labelledby="files-delete">
        <h2 id="files-delete">{chosen.length === 1 ? "1 Datei löschen" : `${chosen.length} Dateien löschen`}</h2>
        <p>Die markierten Dateien werden endgültig vom Mac entfernt.</p>
        <div className="g-actions">
          <button type="button" className="g-button" onClick={() => confirm.current?.close()}>
            Abbrechen
          </button>
          <button
            type="button"
            className="g-button g-danger"
            onClick={() => {
              confirm.current?.close();
              void remove(chosen.map((m) => m.mediaId)).then(() => setMarked(new Set()));
            }}
          >
            Löschen
          </button>
        </div>
      </dialog>

      <dialog ref={dialog} className="g-dialog g-media" aria-label={open?.caption} onClose={() => setOpen(null)}>
        {open ? (
          <MediaDetail
            item={open}
            choose={choose}
            known={(id) => items.find((x) => x.mediaId === id)}
            onOpen={(m) => show(m)}
            onClose={() => dialog.current?.close()}
          />
        ) : null}
      </dialog>
    </section>
  );
}
