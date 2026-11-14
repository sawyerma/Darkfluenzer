import { JobResult } from "../core/generated/darkfluenzer/v1/comfy_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useEventTopic, useStateTopic } from "../core/state";
import { ComfyBadge, clock } from "./ComfyUI";

export function Overview() {
  const comfy = useStateTopic(Topic.COMFY_STATUS);
  const last = useEventTopic(Topic.JOB_COMPLETED)?.items.at(-1);

  return (
    <section className="g-panel">
      <h1>Übersicht</h1>
      <div className="g-section">
        <div className="g-line">
          <span>ComfyUI</span>
          <span className="g-value">
            <ComfyBadge comfy={comfy} />
          </span>
        </div>
        {last ? (
          <div className="g-line">
            <span>Letzte Renderung</span>
            <span className="g-value">
              {last.value.workflow} · {clock(last.committedMs)} ·{" "}
              {last.value.result === JobResult.DONE ? "fertig" : "fehlgeschlagen"}
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
