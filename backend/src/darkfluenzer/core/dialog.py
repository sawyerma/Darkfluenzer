"""Gates vor dem Versand einer KI-Antwort (SP4 Schritt 3, SPEC-017).

Keine sprachliche Regelprüfung in Python: Verhalten, Verbote und Formulierungen stehen im
Promptprofil (E19). Hier bleiben nur technische und fachliche Gates, die Zahlen und Zustände
abgleichen:

- Schema: die Einstufung des neutralen Laufs (E26) erfüllt den Schema-Vertrag (``assessment``);
  sonst ein neuer Lauf, danach Entwurf an den Betreiber.
- Minderjährigkeit: meldet die Einstufung einen Hinweis, wird nichts gesendet (Folgen Schritt 4).
- Beträge: jeder Euro-Betrag im Antworttext steht in den Geschäftsfakten (Preis, HD-Aufschlag,
  Summe) – Zahlenabgleich.
- Zahlungswege: jeder im Antworttext genannte Zahlungsweg (Begriffskatalog aus der Konfiguration)
  ist freigegeben.
- Kundenantworten zusätzlich: KI-Hinweis für diese Kanalidentität gesendet (Regel 12 b), Akte
  nicht gesperrt, kein Betreiber-Eingriff aktiv, Automatik an, Antwortfenster offen, Textgrenze.

Verletztes Gate: kein Versand, Entwurf mit Grund (Kundenkette ab SP4 Schritt 6)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import Config
from . import assessment

# Betrag mit Währung: „20,00 €“, „20 €“, „€ 20,50“, „20 Euro“, „20.50 EUR“
_AMOUNT = re.compile(
    r"(?:€|eur(?:o)?)\s*(\d{1,6}(?:[.,]\d{1,2})?)\b|\b(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:€|eur(?:o)?\b)",
    re.IGNORECASE,
)
# Zahlungswege aus dem Wallet-Teil (Angebot mit eindeutigem Betrag, C5a)
CRYPTO_WAYS = ("btc", "usdt", "usdc")


@dataclass(frozen=True)
class Gate:
    name: str
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class Facts:
    """Geschäftsfakten aus SQLite und Konfiguration: Preisliste und freigegebene Zahlungswege."""

    prices: tuple[dict, ...] = ()
    payment_ways: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)  # Zahlungsweg -> Anzeigename

    def amounts(self) -> set[int]:
        """Erlaubte Beträge in Cent: Preis, HD-Aufschlag, Preis mit Aufschlag."""
        out: set[int] = set()
        for p in self.prices:
            out |= {p["price_cents"], p["price_cents"] + p["hd_surcharge_cents"]}
            if p["hd_surcharge_cents"]:
                out.add(p["hd_surcharge_cents"])
        return out

    def text(self) -> str:
        """Faktenblock für den Eingang ``facts`` des Sprachworkflows (Daten, keine Formulierung)."""
        lines = []
        for p in self.prices:
            hd = (
                f", HD-Aufschlag {euro(p['hd_surcharge_cents'])}" if p["hd_surcharge_cents"] else ""
            )
            lines.append(f"{p['product']}: {euro(p['price_cents'])}{hd}")
        ways = [self.labels.get(w, w) for w in self.payment_ways]
        lines.append(f"Zahlungswege: {', '.join(ways) if ways else 'keine freigegeben'}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ReplyContext:
    """Zustand einer Kundenantwort (Kundenkette ab SP4 Schritt 6): vom Aufrufer aus Akte, Kanal und
    Konversation ermittelt."""

    ai_notice_sent: bool
    age_mark: str
    operator_active: bool  # Betreiber hat übernommen (Human-Agent, Modus der Konversation)
    automation: bool  # Automatik des Kanalkontos bzw. der Influencerin an
    window_open: bool = True  # Plattform-Antwortfenster (Instagram 24 h)
    max_text_bytes: int | None = None


def euro(cents: int) -> str:
    return f"{cents / 100:.2f}".replace(".", ",") + " €"


def facts_for(cfg: Config, influencer: dict) -> Facts:
    """Fakten einer Influencerin: Preisliste aus SQLite, Zahlungswege aus der Konfiguration –
    Amazon-Gutschein immer (E6), Krypto nur mit Wallet, PayPal erst mit Anschluss (SP5 3)."""
    ways = ["amazon"]
    if cfg.wallet is not None:
        if cfg.wallet.btc_address:
            ways.append("btc")
        if cfg.wallet.bsc_address:
            symbols = {t.symbol.lower() for t in cfg.wallet.tokens}
            ways += [w for w in CRYPTO_WAYS[1:] if w in symbols]
    labels = {key: terms[0] for key, terms in cfg.dialog.payment_terms.items() if terms}
    return Facts(tuple(influencer.get("prices") or ()), tuple(ways), labels)


def _cents(raw: str) -> int:
    value = raw.replace(",", ".")
    whole, _, frac = value.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def mentioned_amounts(text: str) -> list[int]:
    return [_cents(a or b) for a, b in _AMOUNT.findall(text)]


def mentioned_ways(text: str, terms: dict[str, tuple[str, ...]]) -> list[str]:
    """Zahlungswege, deren Begriff (ganzes Wort, ohne Groß-/Kleinschreibung) im Text steht."""
    found = []
    for way, words in terms.items():
        if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in words):
            found.append(way)
    return found


def _gate(name: str, failure: str) -> Gate:
    """Gate bestanden, wenn kein Grund vorliegt."""
    return Gate(name, not failure, failure)


def check(
    answer: str,
    classification: dict | None,
    facts: Facts,
    terms: dict[str, tuple[str, ...]],
    context: ReplyContext | None = None,
) -> list[Gate]:
    """Alle anwendbaren Gates; ohne Kundenkontext (KI-Studio) nur Schema, Minderjährigkeit, Beträge
    und Zahlungswege."""
    typed, why = assessment.parse(classification)  # Schema-Vertrag (SP4 Schritt 4)
    minor = typed.minor_hint if typed else bool((classification or {}).get("minor_hint"))
    allowed = facts.amounts()
    wrong = [a for a in mentioned_amounts(answer) if a not in allowed]
    foreign = [w for w in mentioned_ways(answer, terms) if w not in facts.payment_ways]
    gates = [
        _gate("schema", why),
        _gate("minor", "Einstufung meldet Minderjährigkeit." if minor else ""),
        _gate("amounts", ", ".join(f"{euro(a)} steht nicht in den Fakten" for a in wrong)),
        _gate(
            "payment_ways",
            ", ".join(f"Zahlungsweg {facts.labels.get(w, w)} nicht freigegeben" for w in foreign),
        ),
    ]
    if context is None:
        return gates
    size, limit = len(answer.encode("utf-8")), context.max_text_bytes
    too_long = limit is not None and size > limit
    return gates + [
        _gate("ai_notice", "" if context.ai_notice_sent else "KI-Hinweis noch nicht gesendet."),
        _gate(
            "locked",
            "Akte gesperrt (minderjährig vermutet)." if context.age_mark == "under_18" else "",
        ),  # fmt: skip
        _gate("operator", "Betreiber hat übernommen." if context.operator_active else ""),
        _gate("automation", "" if context.automation else "Automatik ist aus."),
        _gate("window", "" if context.window_open else "Antwortfenster ist geschlossen."),
        _gate("text_limit", f"Text zu lang ({size} > {limit} Byte)." if too_long else ""),
    ]


def sendable(gates: list[Gate]) -> bool:
    return all(g.ok for g in gates)
