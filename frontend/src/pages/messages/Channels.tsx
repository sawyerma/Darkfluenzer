import { CHANNEL_STATE, LOGIN_STEP, Tone } from "./common";
import type { ChannelStatus } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { type FormEvent, useState } from "react";
import { PLATFORM_LABEL, shortTime } from "../../core/channels";
import { useCommand } from "../../core/commands";

/** Warum ein Kanal gerade nicht sendet: nicht eingerichtet (mit dem, was fehlt) oder nicht verbunden. */
export function channelNote(ch: ChannelStatus | undefined, platform: string): string {
  const label = PLATFORM_LABEL[platform] ?? platform;
  if (!ch || ch.state === "OFF") return [`${label} nicht eingerichtet`, ch?.missing].filter(Boolean).join(" · ");
  if (ch.state === "READY") return "";
  return [`${label} nicht verbunden`, ch.error || ch.missing].filter(Boolean).join(" · ");
}

/** Anmeldung, Automatik und Abmelden eines Kanalkontos (Befehle 39/40). Eingaben werden nach
 *  jedem Schritt verworfen und nie angezeigt. */
function AccountControls({ ch }: { ch: ChannelStatus }) {
  const cmd = useCommand();
  const [value, setValue] = useState("");
  const [confirmLogout, setConfirmLogout] = useState(false);
  const step = LOGIN_STEP[ch.loginState];

  async function submit(e: FormEvent) {
    e.preventDefault();
    const entered = value.trim();
    setValue(""); // nie stehen lassen
    if (!entered) return;
    await cmd.run({ case: "channelAccountLogin", value: { platform: ch.platform, step: ch.loginState, value: entered } });
  }

  function update(action: string) {
    setConfirmLogout(false);
    void cmd.run({ case: "channelAccountUpdate", value: { platform: ch.platform, action } });
  }

  return (
    <>
      {ch.platform === "instagram" && ch.loginState === "oauth" ? (
        <div className="g-actions">
          <a className="g-button g-primary" href="/api/v1/instagram/login" target="_blank" rel="noopener">
            Mit Instagram anmelden
          </a>
        </div>
      ) : null}
      {ch.state === "LOGIN" && step ? (
        <form className="g-actions" onSubmit={submit}>
          <input
            className="g-input"
            type={step[2]}
            autoComplete="off"
            aria-label={step[1]}
            placeholder={ch.loginState === "password" && ch.loginHint ? `${step[1]} (Hinweis: ${ch.loginHint})` : step[1]}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button type="submit" className="g-button g-primary" disabled={cmd.pending || !value.trim()}>
            {ch.loginState === "phone" ? "Anmelden" : "Weiter"}
          </button>
        </form>
      ) : null}
      {ch.state === "READY" ? (
        <div className="g-actions">
          <button
            type="button"
            className="g-button"
            disabled={cmd.pending}
            onClick={() => update(ch.automation ? "disable_automation" : "enable_automation")}
          >
            {ch.automation ? "Automatik sperren" : "Automatik freigeben"}
          </button>
          {confirmLogout ? (
            <>
              <button type="button" className="g-button g-danger" disabled={cmd.pending} onClick={() => update("logout")}>
                Wirklich abmelden
              </button>
              <button type="button" className="g-button" onClick={() => setConfirmLogout(false)}>
                Abbrechen
              </button>
            </>
          ) : (
            <button type="button" className="g-button" onClick={() => setConfirmLogout(true)}>
              Abmelden
            </button>
          )}
        </div>
      ) : null}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </>
  );
}

/** Kanalstatus (STATE channels) kompakt in der linken Spalte. */
export function ChannelLines({ channels, stale }: { channels: readonly ChannelStatus[] | undefined; stale: boolean }) {
  if (!channels) return <small>Kanalstatus: keine Daten</small>;
  return (
    <div>
      {channels.map((ch) => {
        const step = ch.state === "LOGIN" ? LOGIN_STEP[ch.loginState] : undefined;
        const [label, tone] = step
          ? [step[0], "warn" as Tone]
          : ch.state === "READY" && ch.testMode
              ? ["TESTBETRIEB", "warn" as Tone]
              : (CHANNEL_STATE[ch.state] ?? [ch.state || "UNBEKANNT", "neutral" as Tone]);
        const detail = ch.state === "READY" || ch.state === "LOGIN" ? "" : ch.error || ch.missing;
        const flood = Number(ch.floodUntilMs) > Date.now() ? `Telegram bremst bis ${shortTime(ch.floodUntilMs)}` : "";
        return (
          <div key={ch.platform} className="g-stack">
            <span className="g-between">
              <span className="g-ellipsis">
                <span className="g-ptag" data-platform={ch.platform}>
                  {PLATFORM_LABEL[ch.platform] ?? ch.platform}
                </span>{" "}
                {ch.account}
              </span>
              <span className="g-badge" data-tone={stale ? "stale" : tone}>
                {label}
              </span>
            </span>
            {detail ? ch.state === "ERROR" ? <span className="g-error">{detail}</span> : <small>{detail}</small> : null}
            {ch.testMode && ch.state !== "OFF" ? <small>TESTBETRIEB · nur freigegebene Test-Chats</small> : null}
            {ch.testMode && ch.rejectedChats.length ? (
              <small className="g-mono">
                Verworfen (für test_chat_ids):{" "}
                {ch.rejectedChats.map((r) => `${String(r.chatId)} · ${shortTime(r.atMs)}`).join(", ")}
              </small>
            ) : null}
            {flood ? <small className="g-error">{flood}</small> : null}
            {ch.state === "READY" && ch.automation ? <small>Automatik freigegeben</small> : null}
            <AccountControls ch={ch} />
          </div>
        );
      })}
    </div>
  );
}
