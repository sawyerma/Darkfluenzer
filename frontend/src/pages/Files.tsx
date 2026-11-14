import { useEffect, useMemo, useRef, useState } from "react";
import { fetchMediaPage } from "../core/commands";
import { MediaKind, MediaOrigin, type MediaItem } from "../core/generated/darkfluenzer/v1/media_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useConnection } from "../core/realtime";
import { useEventTopic } from "../core/state";
import { mediaUrl, useCommand } from "./ComfyUI";

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
const PAGE_SIZE = 48;

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

export function Files() {
  const live = useEventTopic(Topic.MEDIA_ADDED);
  const removed = useEventTopic(Topic.MEDIA_REMOVED);
  const connection = useConnection();
  const cmd = useCommand();
  const [pages, setPages] = useState<MediaItem[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<MediaItem | null>(null);
  const [marked, setMarked] = useState<ReadonlySet<bigint>>(new Set());
  const [deleted, setDeleted] = useState<ReadonlySet<bigint>>(new Set());
  const dialog = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLDialogElement>(null);

  // Seiten und Live-Ereignisse zusammengeführt: je media_id genau ein Eintrag, neueste zuerst;
  // gelöschte (EVENT media.removed bzw. eigener angenommener Löschbefehl) fallen heraus.
  const items = useMemo(() => {
    const byId = new Map<bigint, MediaItem>();
    for (const m of pages) byId.set(m.mediaId, m);
    for (const e of live?.items ?? []) byId.set(e.value.mediaId, e.value);
    for (const e of removed?.items ?? []) byId.delete(e.value.mediaId);
    for (const id of deleted) byId.delete(id);
    return [...byId.values()].sort((a, b) => (b.mediaId > a.mediaId ? 1 : b.mediaId < a.mediaId ? -1 : 0));
  }, [pages, live, removed, deleted]);
  const shown = items.filter((m) => matches(m, filter));
  const deletable = shown.filter((m) => !m.orderNo); // Kundenmedien sind nicht löschbar
  const chosen = deletable.filter((m) => marked.has(m.mediaId));
  const allMarked = deletable.length > 0 && chosen.length === deletable.length;

  async function load(before: bigint) {
    setLoading(true);
    setError("");
    try {
      const page = await fetchMediaPage(before, PAGE_SIZE);
      setPages((p) => [...p, ...page.items]);
      setMore(page.more);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // erste Seite beim Aufruf, sobald verbunden; ältere nur auf Wunsch
    if (connection.status === "OPEN" && !loaded && !loading) void load(0n);
  }, [connection.status, loaded]);

  useEffect(() => {
    // Mehr Löschungen als der Nachzug liefert: Galerie neu laden statt veraltete Kacheln zeigen
    if (removed?.gap) {
      setPages([]);
      setMore(false);
      setLoaded(false);
    }
  }, [removed?.gap]);

  useEffect(() => {
    if (open && !items.some((m) => m.mediaId === open.mediaId)) dialog.current?.close();
  }, [items, open]);

  function show(item: MediaItem) {
    setOpen(item);
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
      setDeleted((s) => new Set([...s, ...ids]));
    }
  }

  return (
    <section className="g-panel">
      <h1>Dateien</h1>
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
        <p className="g-note">{loaded || live?.live ? EMPTY[filter] : connection.status === "OPEN" ? "Lädt …" : "Keine Verbindung"}</p>
      )}
      {error || cmd.notice ? (
        <p className="g-note" role="alert">
          {error || cmd.notice}
        </p>
      ) : null}
      {more ? (
        <div className="g-actions">
          <button type="button" className="g-button" disabled={loading} onClick={() => load(items.at(-1)?.mediaId ?? 0n)}>
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
          <div className="g-media-body">
            <Medium item={open} controls />
            <div>
              <h2>{open.caption}</h2>
              <dl className="g-params">
                {open.workflow ? (
                  <div>
                    <dt>Workflow</dt>
                    <dd>{open.workflow}</dd>
                  </div>
                ) : null}
                {open.params.seed ? (
                  <div>
                    <dt>Seed</dt>
                    <dd>{open.params.seed}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>Zeit</dt>
                  <dd>{new Date(Number(open.createdUnixMs)).toLocaleString("de-DE")}</dd>
                </div>
                <div>
                  <dt>Herkunft</dt>
                  <dd>{ORIGIN[open.origin]}</dd>
                </div>
                {open.orderNo ? (
                  <div>
                    <dt>Auftrag</dt>
                    <dd>
                      {open.orderNo} · {open.customerNo}
                    </dd>
                  </div>
                ) : null}
                <div>
                  <dt>Datei</dt>
                  <dd>
                    {open.path.split("/").pop()} · {(Number(open.size) / 1e6).toFixed(1)} MB
                  </dd>
                </div>
              </dl>
              <div className="g-actions">
                <a className="g-button" href={mediaUrl(open.path)} target="_blank" rel="noreferrer">
                  Öffnen
                </a>
                <a className="g-button" href={`${mediaUrl(open.path)}?download=1`}>
                  Herunterladen
                </a>
                <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
                  Schließen
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </dialog>
    </section>
  );
}
