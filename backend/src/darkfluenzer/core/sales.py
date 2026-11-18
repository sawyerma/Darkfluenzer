"""Wallet, Angebote, Zahlungen, Gutscheine (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from ..payments.chain import SATOSHI, decimal_text
from ..store import StoreError
from ..v1 import (
    commands_pb2,
    wallet_pb2,
)
from ..v1 import stream_pb2 as spb
from .base import _Call, _unix_ms

# Kundenauftrag (V0 §8.4/§8.5): Zahlungswege mit eindeutigem Betrag, entschiedene Gutscheine im
# Reiter Wallet, Suche nach einem freien eindeutigen Betrag
OFFER_METHODS = ("btc", "usdt", "usdc")


VOUCHERS_DECIDED_SHOWN = 20


UNIQUE_STEPS = 9999


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


class SalesMixin:
    """Wallet, Angebote, Zahlungen, Gutscheine; Teil von ``Cockpit``."""

    def _wallet_state(self) -> bytes:
        """STATE wallet: Konten mit Guthaben, Euro-Wert, Kurszeit, letzter Prüfung, Quellen."""
        msg = wallet_pb2.Wallet(version=self.store.domain_version("payments"))
        for v in self.store.vouchers(VOUCHERS_DECIDED_SHOWN):
            msg.vouchers.add(
                voucher_id=v["id"],
                customer_id=v["customer_id"],
                customer_no=v["customer_no"],
                display_name=v["display_name"] or "",
                code=v["code"],
                status=v["status"],
                amount_cents=v["amount_cents"] or 0,
                at_ms=_unix_ms(v["created_at"]),
                decided_ms=_unix_ms(v["decided_at"]) if v["decided_at"] else 0,
            )
        for o in self.store.open_offers():
            msg.open_offers.add(
                order_no=o["order_no"],
                customer_id=o["customer_id"],
                customer_no=o["customer_no"],
                display_name=o["display_name"] or "",
                product=o["product"] + (" + HD" if o["hd"] else ""),
                price_cents=o["price_cents"],
                expires_ms=_unix_ms(o["expires_at"]),
                amounts=[f"{m.upper()} {a}" for m, a in o["amounts"].items()],
            )
        if self.wallet is None:
            for key, title, network in (("btc", "Bitcoin", "bitcoin"), ("bsc", "BSC", "bsc")):
                msg.accounts.add(
                    key=key, title=title, network=network, state="MISSING",
                    missing="Abschnitt [wallet] in config.toml",
                )  # fmt: skip
            return msg.SerializeToString()
        for acc in self.wallet.accounts():
            balances = acc.pop("balances")
            item = msg.accounts.add(**acc)
            for b in balances:
                item.balances.add(**b)
        for src in self.wallet.sources():
            msg.sources.add(**src)
        return msg.SerializeToString()

    def _wallet_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_WALLET, self._wallet_state())

    def _payments_changed(self) -> None:
        """Eingang neu/geändert; eine automatische Zuordnung ändert auch Auftrag und Verlauf."""
        self.hub.push_events(spb.TOPIC_PAYMENT_UPDATED)
        self._wallet_changed()
        self._orders_changed()
        self._message_changed(0)

    def _offer_amounts(self, price_cents: int) -> dict[str, tuple[str, str, float, int]]:
        """Je eingerichtetem Zahlungsweg ein noch nie vergebener, exakter Betrag zum aktuellen Kurs
        (V0 §8.5 Punkte 2–3): BTC in Satoshi aufgerundet plus eindeutige Endung, Stablecoins auf
        Cent aufgerundet plus eindeutige vierte Nachkommastelle."""
        w = self.wallet
        if w is None:
            raise StoreError("Keine Zahlungswege eingerichtet (Abschnitt [wallet] in config.toml).")
        fresh_ms = int(w.w.poll_s * 3 * 1000)
        if not w.rate_ms or int(time.time() * 1000) - w.rate_ms > fresh_ms:
            raise StoreError("Kein aktueller Kurs – Angebot gerade nicht möglich.")
        eur = Decimal(price_cents) / 100
        ways: list[
            tuple[str, str, float, Decimal, Decimal]
        ] = []  # Weg, Adresse, Kurs, Basis, Schritt
        if w.w.btc_address and (rate := w.rates.get(w.w.btc_price_id)):
            sats = (eur / Decimal(str(rate)) * SATOSHI).to_integral_value(ROUND_CEILING)
            ways.append(("btc", w.w.btc_address, rate, sats / SATOSHI, 1 / SATOSHI))
        for token in w.w.tokens if w.w.bsc_address else []:
            method = token.symbol.lower()
            if method in OFFER_METHODS and (rate := w.rates.get(token.price_id)):
                cents = (eur / Decimal(str(rate)) * 100).to_integral_value(ROUND_CEILING)
                ways.append((method, w.w.bsc_address, rate, cents / 100, Decimal("0.0001")))
        if not ways:
            raise StoreError("Kein Zahlungsweg mit Adresse und Kurs eingerichtet.")
        out = {}
        for method, address, rate, base, step in ways:
            for k in range(1, UNIQUE_STEPS + 1):
                amount = decimal_text(base + k * step)
                if not self.store.amount_taken(method, amount):
                    out[method] = (amount, address, rate, w.rate_ms)
                    break
            else:
                raise StoreError(f"{method.upper()}: kein freier eindeutiger Betrag.")
        return out

    def _offer_text(self, order, product: str, hd: bool, price_cents: int, amounts, expires,
                    note: str) -> str:  # fmt: skip
        """Nachricht an den Kunden: Betrag und Zahlungswege (Tatsachen, kein Persona-Text)."""
        until = expires.astimezone().strftime("%d.%m.%Y, %H:%M Uhr")
        lines = [note.strip(), ""] if note.strip() else []
        lines.append(
            f"Angebot {order.order_no}: {product}{' + HD' if hd else ''} · {_eur(price_cents)}"
        )
        lines.append(f"Bitte genau diesen Betrag senden, gültig bis {until}:")
        for method, (amount, address, _rate, _ms) in amounts.items():
            if method == "btc":
                lines.append(f"• Bitcoin: {amount} BTC an {address}")
            else:
                lines.append(f"• {method.upper()} (BNB Smart Chain, BEP-20): {amount} an {address}")
        return "\n".join(lines)

    async def _create_offer(self, msg: commands_pb2.CreateOffer, call: _Call) -> str:
        """Angebot aus der Preisliste (Befehl 46, V0 §8.4 Punkt 3)."""
        call.entity = f"customer:{msg.customer_id}"
        summary = self.store.customers_overview(msg.customer_id)
        if not summary or summary[0]["kind"] == "internal":
            return "Angebote nur an Kundenakten."
        if summary[0]["age_mark"] == "under_18":  # nur die Sperre zählt (BUG-077, kein Altersblock)
            return "Akte gesperrt (minderjährig vermutet) – kein Angebot."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None or ident["conversation_id"] != msg.conversation_id:
            return "Kanal passt nicht zu dieser Kundenakte."
        if ident["ai_notice_status"] != "sent":
            return "Erst den KI-Hinweis über diesen Kanal senden (Regel 12 b)."
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is None or adapter.state != "READY":
            return f"{ident['platform']} ist nicht verbunden."
        figure = next((f for f in self.store.influencers() if f["id"] == msg.influencer_id), None)
        if figure is None:
            return "Influencerin-Profil unbekannt."
        if msg.position >= len(figure["prices"]):
            return "Position der Preisliste unbekannt."
        item = figure["prices"][msg.position]
        price = item["price_cents"] + (item["hd_surcharge_cents"] if msg.hd else 0)
        assert self.cfg.wallet is not None  # sonst lehnt _offer_amounts ab
        amounts = self._offer_amounts(price)
        expires = datetime.now(UTC) + timedelta(minutes=self.cfg.wallet.offer_valid_min)
        with self.store.tx():
            order = self.store.create_offer(
                msg.customer_id,
                msg.conversation_id,
                item["product"],
                msg.hd,
                price,
                expires.isoformat(timespec="milliseconds"),
                amounts,
            )
            text = self._offer_text(
                order, item["product"], msg.hd, price, amounts, expires, msg.note
            )
            self.store.queue_outbound(
                msg.customer_id,
                msg.conversation_id,
                text,
                revision=msg.revision,
                request_id=call.request_id,
            )
            ways = " · ".join(f"{m.upper()} {a[0]}" for m, a in amounts.items())
            self.store.add_system_card(
                msg.conversation_id,
                f"ANGEBOT · {item['product']}{' + HD' if msg.hd else ''} · {_eur(price)} · {ways}",
                order_id=order.id,
            )
        call.entity = f"order:{order.order_no}"
        adapter.wake.set()
        self._message_changed(0)
        self._wallet_changed()
        return ""

    async def _payment_assign(self, msg: commands_pb2.PaymentAssign, call: _Call) -> str:
        """Nicht zugeordneten Eingang einem offenen Angebot zuordnen (Befehl 41)."""
        call.entity = f"payment:{msg.payment_id}"
        self.store.assign_inflow(msg.payment_id, msg.order_no, "Betreiber")
        self._payments_changed()
        return ""

    async def _gift_card_confirm(self, msg: commands_pb2.GiftCardConfirm, call: _Call) -> str:
        """Amazon-Gutschein entscheiden (Befehl 42): eingelöster Betrag oder abgelehnt."""
        call.entity = f"voucher:{msg.voucher_id}"
        if msg.reject:
            self.store.reject_voucher(msg.voucher_id)
        elif msg.amount_cents <= 0:
            return "Eingelösten Betrag angeben."
        else:
            self.store.redeem_voucher(msg.voucher_id, msg.amount_cents)
        self._payments_changed()
        return ""
