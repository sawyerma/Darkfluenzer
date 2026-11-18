import type { ActiveOrder, OrderStage } from "../../core/generated/darkfluenzer/v1/order_pb";
import { IMAGE, STAGE_LABEL, VIDEO } from "./common";
import { Progress } from "./Queue";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { mediaUrl } from "../../core/media";
import { useCommand } from "../../core/commands";
import { useState } from "react";
import { useStateTopic } from "../../core/state";

/** Kandidatenvergleich (Mitte, V0 §9.6): je Kandidat ein echtes Ergebnis, synchroner Zoom,
 * Auswahl durch den Betreiber; danach Fertigstellen. */
export function Candidates({
  orders,
  titles,
  heading = true,
}: {
  orders: ActiveOrder[];
  titles: Record<string, string>;
  heading?: boolean;
}) {
  const cmd = useCommand();
  const jobs = useStateTopic(Topic.JOBS_ACTIVE)?.value.jobs ?? [];
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const slotted = new Set(workflows.filter((w) => w.loraSlot).map((w) => w.key));
  const [zoom, setZoom] = useState<{ x: number; y: number } | null>(null);
  const stageText = (stage: OrderStage) =>
    (stage.kind === "finish" ? `Fertigstellen · ${titles[stage.workflow] ?? stage.workflow}` : "Kandidaten") +
    (stage.lora ? ` · LoRA ${stage.lora}` : slotted.has(stage.workflow) ? " · ohne Charakter-LoRA" : "");
  // je Auftrag einklappbar (GUI-Prüfung 18.11. Punkt 6): anfangs nur der erste geöffnet
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  if (orders.length === 0) return null;
  return (
    <div className="g-result">
      {heading ? (
        <div className="g-line g-head">
          <h2>Kandidaten</h2>
          <small>{orders.length === 1 ? "1 Auftrag" : `${orders.length} Aufträge`}</small>
        </div>
      ) : null}
      {orders.map((order, index) => {
        const open = opened[order.orderNo] ?? index === 0;
        const last = order.stages[order.stages.length - 1];
        const [label, tone] = STAGE_LABEL[last?.status ?? ""] ?? [last?.status ?? "", "neutral"];
        const thumbs = (last?.jobs ?? []).filter((j) => j.mediaId && IMAGE.test(j.path));
        return (
        <details
          key={order.orderNo}
          className="g-order"
          open={open}
          onToggle={(e) => {
            const now = e.currentTarget.open;
            if (now !== open) setOpened((o) => ({ ...o, [order.orderNo]: now }));
          }}
        >
          <summary>
            <span className="g-ellipsis">
              {order.orderNo} · {last ? stageText(last) : "Kandidaten"}
            </span>
            {last && last.attempts > 1 ? <small>Versuch {last.attempts}</small> : null}
            {open ? null : (
              <span className="g-order-thumbs">
                {thumbs.map((j) => (
                  <img key={String(j.jobId)} src={mediaUrl(j.path)} alt="" loading="lazy" />
                ))}
              </span>
            )}
            <span className="g-badge" data-tone={tone}>
              {label}
            </span>
          </summary>
          {order.stages.some((st) => st.jobs.some((j) => j.status === "queued" || j.status === "running")) ? (
            <div className="g-actions">
              <button
                type="button"
                className="g-button g-danger"
                disabled={cmd.pending}
                onClick={() => cmd.run({ case: "orderCancel", value: { orderNo: order.orderNo } })}
              >
                Auftrag abbrechen
              </button>
            </div>
          ) : null}
          {order.stages.map((stage) => {
            const [label, tone] = STAGE_LABEL[stage.status] ?? [stage.status, "neutral"];
            const failed = stage.jobs.some((j) => j.status === "failed");
            return (
              <div key={stage.seq} className="g-stage">
                {order.stages.length > 1 ? (
                  // mehrere Stufen: je Stufe eine Zeile; bei einer Stufe steht alles im Kopf
                  <div className="g-line">
                    <span className="g-ellipsis">{stageText(stage)}</span>
                    <span className="g-value">
                      {stage.attempts > 1 ? <small>Versuch {stage.attempts}</small> : null}
                      <span className="g-badge" data-tone={tone}>
                        {label}
                      </span>
                    </span>
                  </div>
                ) : null}
                {stage.error && stage.status === "failed" ? <p className="g-note g-error">{stage.error}</p> : null}
                <div
                  className="g-candidates"
                  data-zoom={zoom ? "" : undefined}
                  data-zx={zoom ? zoom.x : undefined}
                  data-zy={zoom ? zoom.y : undefined}
                >
                  {stage.jobs.map((j) => {
                    const active = jobs.find((a) => a.jobId === j.jobId);
                    const chosen = stage.selectedMediaId !== 0n && stage.selectedMediaId === j.mediaId;
                    return (
                      <div key={String(j.jobId)} className="g-candidate" data-chosen={chosen ? "" : undefined}>
                        {j.mediaId && IMAGE.test(j.path) ? (
                          <div
                            className="g-zoom"
                            onMouseMove={(e) => {
                              const r = e.currentTarget.getBoundingClientRect();
                              // Zoompunkt in Zehnerschritten (Stufen im Stylesheet)
                              const step = (v: number) => Math.min(10, Math.max(0, Math.round(v * 10)));
                              setZoom({ x: step((e.clientX - r.left) / r.width), y: step((e.clientY - r.top) / r.height) });
                            }}
                            onMouseLeave={() => setZoom(null)}
                          >
                            <img src={mediaUrl(j.path)} alt={`Kandidat Seed ${j.seed}`} />
                          </div>
                        ) : j.mediaId && VIDEO.test(j.path) ? (
                          <video src={mediaUrl(j.path)} controls muted preload="metadata" />
                        ) : (
                          <div className="g-placeholder">
                            {j.status === "failed" ? "Fehler" : active?.running ? <Progress job={active} /> : "wartet"}
                          </div>
                        )}
                        <div className="g-line">
                          <small>
                            Seed {String(j.seed)}
                            {j.mediaId ? ` · ${j.contentTier === "standard" ? "standard" : "explizit"}` : ""}
                          </small>
                          {stage.status === "waiting" && j.mediaId ? (
                            <button
                              type="button"
                              className="g-button g-primary"
                              disabled={cmd.pending}
                              onClick={() => cmd.run({ case: "selectCandidate", value: { orderNo: order.orderNo, mediaId: j.mediaId } })}
                            >
                              Auswählen
                            </button>
                          ) : chosen ? (
                            <span className="g-badge" data-tone="ok">
                              AUSGEWÄHLT
                            </span>
                          ) : null}
                        </div>
                        {j.status === "failed" && j.error ? <small className="g-error">{j.error}</small> : null}
                      </div>
                    );
                  })}
                </div>
                {failed && (stage.status === "failed" || stage.status === "waiting") ? (
                  <div className="g-actions">
                    <button
                      type="button"
                      className="g-button"
                      disabled={cmd.pending}
                      onClick={() => cmd.run({ case: "retryStage", value: { orderNo: order.orderNo, seq: stage.seq } })}
                    >
                      Fehlgeschlagene wiederholen
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </details>
        );
      })}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}
