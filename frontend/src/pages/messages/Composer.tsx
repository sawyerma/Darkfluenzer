import { AI_MISSING, drafts } from "./common";
import type { ChannelIdentity, ChannelStatus, CustomerSummary } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { type FormEvent, useState } from "react";
import { PLATFORM_LABEL, type Platform, handleLabel, replyTarget, shortTime } from "../../core/channels";
import { channelNote } from "./Channels";
import { useCommand } from "../../core/commands";

/** Kanalgebundene Antwort (F4-Korrektur): nur an die eine verknüpfte Konversation dieses Kanals,
 *  auf der gesehenen Gesprächsrevision. KI-Antwort erst mit angeschlossener Text-KI. */
export function Composer({
  customer,
  platform,
  identities,
  channel,
  loaded,
  live,
}: {
  customer: CustomerSummary;
  platform: Platform;
  identities: readonly ChannelIdentity[];
  channel: ChannelStatus | undefined;
  loaded: boolean;
  live: boolean;
}) {
  const key = `${customer.customerId}:${platform}`;
  const [text, setText] = useState(() => drafts.get(key) ?? "");
  const [humanAgent, setHumanAgent] = useState(false);
  const cmd = useCommand();
  const label = PLATFORM_LABEL[platform] ?? platform;
  const target = loaded ? replyTarget(identities, platform) : "Lädt …";
  // Instagram (FRONT F4 Punkt 10): 24-h-Fenster; danach nur manuell mit Human-Agent-Kennzeichnung
  const now = Date.now();
  const ig = platform === "instagram" && typeof target !== "string";
  const windowOpen = ig && Number(target.windowUntilMs) > now;
  const humanOpen = ig && !windowOpen && Number(target.humanUntilMs) > now;
  const windowNote = !ig
    ? ""
    : windowOpen
      ? `Antwortfenster offen bis ${shortTime(target.windowUntilMs)}`
      : humanOpen
        ? `Antwortfenster abgelaufen · Human-Agent möglich bis ${shortTime(target.humanUntilMs)}`
        : "Instagram-Antwortfenster abgelaufen";
  const blocked =
    typeof target === "string"
      ? target
      : !live
        ? "Keine Verbindung"
        : channelNote(channel, platform) || (ig && !windowOpen && !(humanOpen && humanAgent) ? windowNote : "");
  const handle = typeof target === "string" ? "" : handleLabel(target.handle) || target.platformUserId;

  function edit(value: string) {
    setText(value);
    if (value) drafts.set(key, value);
    else drafts.delete(key);
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (typeof target === "string" || blocked || !body) return;
    const done = await cmd.run({
      case: "sendReply",
      value: {
        customerId: customer.customerId,
        identityId: target.identityId,
        conversationId: target.conversationId,
        platform,
        revision: target.revision,
        text: body,
        humanAgent: humanOpen && humanAgent,
      },
    });
    if (done) {
      drafts.delete(key);
      setText("");
    }
  }

  return (
    <form className="g-compose" data-platform={platform} onSubmit={(e) => void send(e)}>
      <textarea
        className="g-input"
        aria-label={`Antwort über ${label}`}
        placeholder={`Nachricht über ${label} …`}
        value={text}
        disabled={typeof target === "string" || cmd.pending}
        onChange={(e) => edit(e.target.value)}
      />
      <div className="g-between">
        <small>{blocked || [label, handle].filter(Boolean).join(" · ")}</small>
        <span className="g-value">
          <button type="button" className="g-button g-ai" disabled title={AI_MISSING}>
            KI antworten
          </button>
          <button type="submit" className="g-button g-send" disabled={Boolean(blocked) || !text.trim() || cmd.pending}>
            Antwort senden
          </button>
        </span>
      </div>
      {windowNote && windowNote !== blocked ? <small>{windowNote}</small> : null}
      {humanOpen ? (
        <label className="g-switch">
          <input type="checkbox" checked={humanAgent} onChange={(e) => setHumanAgent(e.target.checked)} />
          Als manuelle Antwort mit Human-Agent-Kennzeichnung senden
        </label>
      ) : null}
      <small>KI antworten: {AI_MISSING}</small>
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </form>
  );
}
