import type { Platform } from "../../core/channels";

// Nachrichten (FRONT F4, F7.2–F7.4): links Kundenliste mit Kanalstatus, Mitte Register,
// Unterregister und Verlauf, rechts die Kundensteuerung. „Gesamter Verlauf“ ist nur lesbar;
// geantwortet wird ausschließlich im gewählten, verknüpften Kanal-Unterregister.

export type Tone = "ok" | "warn" | "bad" | "neutral";

export type View = "all" | Platform;

export const CHANNEL_STATE: Record<string, [string, Tone]> = {
  OFF: ["NICHT EINGERICHTET", "neutral"],
  CONNECTING: ["VERBINDET", "warn"],
  READY: ["ANGEMELDET", "ok"],
  ERROR: ["FEHLER", "bad"],
};

// Kontoanmeldung (Telegram über TDLib, FRONT F4 V1.12 Punkt 1): Schritt -> Anzeige, Feld
// Altersangabe (Regel 13): nur Betreiber; keine Verifikation – „Angabe ≥ 18“ ist Selbstauskunft
export const AGE_MARK: [string, string][] = [
  ["unclear", "Alter unklar"],
  ["under_18", "Unter 18"],
  ["self_declared_adult", "Angabe ≥ 18 (Selbstauskunft)"],
];

export const NOTICE: Record<string, string> = {
  queued: "wartet auf Versand",
  sending: "wird gesendet",
  sent: "gesendet",
  failed: "fehlgeschlagen",
  unknown: "Versand unbekannt",
};

export const LOGIN_STEP: Record<string, [string, string, string]> = {
  phone: ["NICHT ANGEMELDET", "Telefonnummer (+49…)", "tel"],
  code: ["CODE ERWARTET", "Code aus Telegram", "text"],
  password: ["PASSWORT ERWARTET", "Zwei-Faktor-Passwort", "password"],
};

/** Ausgänge der Default-Kette (SP1 Schritt 5) im Kopf der Karte „INTERNER AUFTRAG“ → Ton. */
export const CLONER_STATE: Record<string, Tone> = {
  GESTARTET: "ok",
  "WARTET AUF START": "warn",
  ABGELEHNT: "bad",
  ZURÜCKGESENDET: "ok",
  "RÜCKVERSAND GESPERRT": "warn",
  FEHLGESCHLAGEN: "bad",
  ABGEBROCHEN: "neutral",
};

/** Kopf einer Kloner-Karte in Text und Zustand zerlegen (ohne Zustand: wie bisher). */
export function clonerHead(head: string): [string, string, Tone] | null {
  const parts = head.split(" · ");
  const state = parts.at(-1) ?? "";
  if (!head.startsWith("INTERNER AUFTRAG") || !(state in CLONER_STATE)) return null;
  return [parts.slice(0, -1).join(" · "), state, CLONER_STATE[state] ?? "neutral"];
}

export const ITEM_STATUS: Record<string, string> = {
  queued: "wartet",
  sending: "wird gesendet",
  sent: "gesendet",
  failed: "fehlgeschlagen",
  unknown: "Ergebnis unbekannt",
};

export const ATTACHMENT_KIND: Record<string, string> = {
  photo: "Foto",
  video: "Video",
  voice: "Sprachnachricht",
  audio: "Audio",
  document: "Dokument",
  sticker: "Sticker",
  share: "Geteilter Beitrag",
  reel: "Reel",
  post: "Beitrag",
  other: "Anhang",
};

export const ATTACHMENT_STATUS: Record<string, string> = {
  saved: "gesichert",
  pending: "wird gesichert",
  too_large: "zu groß",
  not_importable: "nicht importierbar",
  failed: "fehlgeschlagen",
};

export const ATTACHMENT_TYPE: Record<string, string> = { photo: "image", video: "video", reel: "video", voice: "audio", audio: "audio" };

export const APPROVAL: readonly [string, string][] = [
  ["direct", "Direkt zurücksenden"],
  ["cockpit", "Nach Auswahl im Cockpit"],
  ["cockpit_only", "Nur Cockpit"],
];

export const AI_MISSING = "Text-KI nicht angeschlossen";

export const STICK_PX = 48;

 // so nah am Ende folgt der Verlauf neuen Nachrichten

// Entwürfe je Kunde und Kanal; ein Unterregisterwechsel nimmt keinen Text in einen anderen Kanal mit.
export const drafts = new Map<string, string>();

export const ORDER_STATUS: Record<string, string> = {
  offered: "Angeboten · wartet auf Zahlung",
  accepted: "Angenommen · wartet auf Zahlung",
  paid: "Bezahlt · wartet auf Produktion",
  producing: "In Produktion",
  review: "Zur Prüfung",
  approved: "Freigegeben",
  delivered: "Ausgeliefert",
  cancelled: "Abgebrochen",
  refunded: "Erstattet",
};

export const DELIVERY_STATUS: Record<string, [string, Tone]> = {
  pending: ["im Postausgang", "warn"],
  sent: ["versendet", "ok"],
  failed: ["fehlgeschlagen", "bad"],
  unknown: ["Versand ungeklärt", "bad"],
};

export const METHOD_LABEL: Record<string, string> = { btc: "Bitcoin", usdt: "USDT · BSC", usdc: "USDC · BSC" };
