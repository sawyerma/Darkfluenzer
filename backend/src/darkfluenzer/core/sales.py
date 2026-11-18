"""Wallet, Angebote, Zahlungen, Gutscheine (SP0 Schritt 2, bisher ``server.py``).

Angebot (SP5 Schritt 2): ein Weg für Befehl 46 und den Dialog. Möglich, sobald das Produkt
lieferbar ist, die Lieferzeit gemessen und innerhalb der Grenze des Produkts liegt und ein
Zahlungsweg der Influencerin eingerichtet ist. Der Faktenblock (Produkt, Preis, Zahlungswege,
Frist, Lieferzeit) kommt wörtlich aus dem Backend; die Formulierung davor aus dem Sprachworkflow
bzw. vom Betreiber."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from ..media import pipeline
from ..payments.chain import SATOSHI, decimal_text
from ..store import StoreError
from ..v1 import (
    commands_pb2,
    wallet_pb2,
)
from ..v1 import stream_pb2 as spb
from . import dialog, eta
from .base import _Call, _unix_ms

# Kundenauftrag (V0 §8.4/§8.5): Zahlungswege mit eindeutigem Betrag, entschiedene Gutscheine im
# Reiter Wallet, Suche nach einem freien eindeutigen Betrag
OFFER_METHODS = ("btc", "usdt", "usdc")


VOUCHERS_DECIDED_SHOWN = 20


UNIQUE_STEPS = 9999


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


@dataclass(frozen=True)
class OfferPlan:
    """Geprüftes Angebot vor der Anlage: Produkt, Preis, Zahlungswege, Frist, Lieferzeit."""

    item: dict
    hd: bool
    price: int
    expires: datetime
    delivery_s: float
    payments: list[dict]
    amounts: dict = field(default_factory=dict)  # Krypto: eindeutige Beträge für die Zuordnung
    dropped: str = ""  # gewählte, gerade nicht nutzbare Wege (z. B. kein aktueller Kurs)
    test: bool = False  # Testangebot im Kundentest: Testfreigabe statt Zahlung (SP5 Schritt 12)

    @property
    def label(self) -> str:
        return f"{self.item['product']}{' + HD' if self.hd else ''}"


class SalesMixin:
    """Wallet, Angebote, Zahlungen, Gutscheine; Teil von ``Cockpit``."""

    def _product_problems(self, figure: dict, product: dict, *, test: bool = False) -> list[str]:
        """Lieferbar (SP5 Schritt 1, §9.1, E14)? Leer = ja, sonst die Gründe. Workflow registriert,
        aktiv, Modelle bereit, Art passend, Inhaltsstufe standard, Engine für Produktion (im
        Kundentest genügt die Evaluation), aktive LoRA der Figur, wenn der Workflow sie lädt."""
        problems = []
        steps = ((product["workflow"], "Workflow"), (product["finish_workflow"], "Animation"))
        for key, role in steps:
            if role == "Animation" and product["kind"] != "video":
                continue
            wf = self.manifest.workflows.get(key or "")
            if wf is None:
                problems.append(f"{role} fehlt" if not key else f"{role} {key} nicht registriert")
                continue
            eng = self.manifest.engines[wf.engine]
            want = "video" if role == "Animation" else "image"
            if wf.training or eng.kind != want:
                label = "Video" if want == "video" else "Bild"
                problems.append(f"{wf.title}: kein {label}-Workflow")
            if reason := self._not_startable(wf):
                problems.append(f"{wf.title}: {reason}")
            if wf.content != "standard":
                problems.append(f"{wf.title}: Inhaltsstufe nicht standard")
            if eng.usage != "production" and not test:
                problems.append(f"{wf.title}: Engine nicht für Produktion freigegeben")
            if wf.lora is not None and role == "Workflow":
                character = figure.get("character_id")
                lora = (
                    pipeline.active_lora(self.store, self.manifest, character, wf)
                    if character
                    else ""
                )
                if not lora:
                    problems.append(f"{wf.title}: keine aktive Charakter-LoRA der Figur (E14)")
        if product["kind"] == "video" and not product["max_duration_s"]:
            problems.append("Video: Höchstlänge fehlt")
        return problems

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
                amounts=[f"{p['way'].upper()} {p['amount']}" for p in o["payments"]],
                status=o["status"],
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

    def _offer_amounts(
        self, price_cents: int, chosen: tuple[str, ...] = OFFER_METHODS
    ) -> dict[str, tuple[str, str, float, int]]:
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
        if "btc" in chosen and w.w.btc_address and (rate := w.rates.get(w.w.btc_price_id)):
            sats = (eur / Decimal(str(rate)) * SATOSHI).to_integral_value(ROUND_CEILING)
            ways.append(("btc", w.w.btc_address, rate, sats / SATOSHI, 1 / SATOSHI))
        for token in w.w.tokens if w.w.bsc_address else []:
            method = token.symbol.lower()
            if method in chosen and (rate := w.rates.get(token.price_id)):
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

    # ------------------------------------------------------------------ Angebot (SP5 Schritt 2)

    def _delivery_estimate(self, item: dict) -> tuple[float | None, str]:
        """Lieferzeit eines jetzt bezahlten Auftrags aus Messwerten (``core.eta``)."""
        runs = self.cfg.production.estimate_runs
        now_ts = datetime.now(UTC).timestamp()
        pending = []
        for j in self.store.pending_jobs():
            wf = self.manifest.workflows.get(j["workflow"])
            started = datetime.fromisoformat(j["updated_at"]).timestamp()
            pending.append(
                eta.Pending(
                    j["workflow"], j["status"], j["priority"] or "",
                    elapsed_s=max(0.0, now_ts - started) if j["status"] == "running" else 0.0,
                    steps=int(j["steps"] or 0), training=bool(wf and wf.training),
                )
            )  # fmt: skip
        return eta.delivery_s(
            item,
            pending,
            lambda key: self.store.run_seconds(key, runs),
            lambda key: self.store.seconds_per_step(key, runs),
        )

    def _offer_valid_min(self, figure: dict) -> int:
        """Gültigkeit an der Influencerin, sonst Vorgabe aus [wallet] bzw. [dialog]."""
        default = (
            self.cfg.wallet.offer_valid_min if self.cfg.wallet else self.cfg.dialog.offer_valid_min
        )
        return figure.get("offer_valid_min") or default

    def _offer_plan(
        self, figure: dict, item: dict, hd: bool, *, test: bool = False
    ) -> OfferPlan | str:
        """Angebot prüfen: lieferbar, Lieferzeit gemessen und innerhalb der Grenze, mindestens
        ein eingerichteter Zahlungsweg der Influencerin. Text = Grund, warum keins entsteht."""
        if problems := self._product_problems(figure, item, test=test):
            return f"{item['product']} ist nicht lieferbar: {'; '.join(problems)}."
        delivery, why = self._delivery_estimate(item)
        if delivery is None:
            return f"Lieferzeit für {item['product']} unbekannt: {why}."
        limit = item.get("max_delivery_s") or 0
        if limit and delivery > limit:
            return (
                f"Lieferzeit für {item['product']} ca. {eta.minutes(delivery)} min über der "
                f"Grenze {eta.minutes(limit)} min (Auslastung)."
            )
        price = item["price_cents"] + (item["hd_surcharge_cents"] if hd else 0)
        expires = datetime.now(UTC) + timedelta(minutes=self._offer_valid_min(figure))
        if test:  # Kundentest: keine Zahlungswege, die Testfreigabe ersetzt die Zahlung
            return OfferPlan(item, hd, price, expires, delivery, [], test=True)
        ways = dialog.facts_for(self.cfg, figure).payment_ways
        crypto = tuple(w for w in ways if w in OFFER_METHODS)
        amounts: dict = {}
        dropped = ""
        if crypto:
            try:
                amounts = self._offer_amounts(price, crypto)
            except StoreError as exc:
                dropped = str(exc)
        payments = []
        for way in ways:
            if way == "amazon":
                payments.append({
                    "way": "amazon", "amount": f"{price / 100:.2f}", "currency": "EUR",
                    "note": "Code des Amazon-Gutscheins hier im Chat senden",
                })  # fmt: skip
            elif way in amounts:
                amount, address, _rate, _ms = amounts[way]
                payments.append(
                    {"way": way, "amount": amount, "currency": way.upper(), "target": address}
                )
        if not payments:
            return "Kein Zahlungsweg der Influencerin eingerichtet" + (
                f" ({dropped})." if dropped else "."
            )
        return OfferPlan(item, hd, price, expires, delivery, payments, amounts, dropped)

    def _fact_block(self, order_no: str, plan: OfferPlan) -> str:
        """Faktenblock wörtlich an den Kunden (Daten, keine Formulierung)."""
        until = plan.expires.astimezone().strftime("%d.%m.%Y, %H:%M Uhr")
        if plan.test:
            word = self.store.default_contact()["test_pay_word"] or "Cash"
            return "\n".join([
                f"Testangebot {order_no}: {plan.label} · {_eur(plan.price)} (TEST, keine Zahlung)",
                f"Testfreigabe: „{word}“ senden",
                f"Gültig bis {until}",
                f"Lieferzeit ca. {eta.minutes(plan.delivery_s)} Minuten nach der Testfreigabe",
            ])  # fmt: skip
        labels = {k: t[0] for k, t in self.cfg.dialog.payment_terms.items() if t}
        lines = [f"Angebot {order_no}: {plan.label} · {_eur(plan.price)}",
                 "Bitte genau diesen Betrag senden:"]  # fmt: skip
        for p in plan.payments:
            if p["way"] == "amazon":
                lines.append(f"• {labels.get('amazon', 'Amazon')} über {_eur(plan.price)}")
            elif p["way"] == "btc":
                lines.append(
                    f"• {labels.get('btc', 'Bitcoin')}: {p['amount']} BTC an {p['target']}"
                )
            else:
                lines.append(
                    f"• {p['currency']} (BNB Smart Chain, BEP-20): {p['amount']} an {p['target']}"
                )
        lines.append(f"Gültig bis {until}")
        lines.append(f"Lieferzeit ca. {eta.minutes(plan.delivery_s)} Minuten nach Zahlungseingang")
        return "\n".join(lines)

    def _place_offer(self, plan: OfferPlan, customer_id: int, conversation_id: int):
        """Auftrag mit Angebot, Zahlungswegen und Faktenblock anlegen, Karte ANGEBOT; liefert
        (Auftrag, Faktenblock). Aufrufer hält die Transaktion und reiht die Nachricht ein."""
        order = self.store.create_offer(
            customer_id, conversation_id, plan.item["product"], plan.hd, plan.price,
            plan.expires.isoformat(timespec="milliseconds"), plan.amounts,
            product_id=plan.item["id"], kind=plan.item["kind"], delivery_s=plan.delivery_s,
            payments=plan.payments, test=plan.test,
        )  # fmt: skip
        facts = self._fact_block(order.order_no, plan)
        self.store.set_offer_facts(order.id, facts)
        ways = " · ".join(f"{p['way'].upper()} {p['amount']}" for p in plan.payments)
        dropped = f" · nicht angeboten: {plan.dropped}" if plan.dropped else ""
        head = "TEST · ANGEBOT" if plan.test else "ANGEBOT"
        self.store.add_system_card(
            conversation_id,
            f"{head} · {plan.label} · {_eur(plan.price)} · Lieferzeit ca. "
            f"{eta.minutes(plan.delivery_s)} min · {ways or 'Testfreigabe statt Zahlung'}{dropped}",
            order_id=order.id,
        )
        return order, facts

    def _test_release(self, order_no: str, by: str) -> None:
        """Testfreigabe (SP5 Schritt 12): Testauftrag bezahlt ohne Zahlung, Karte."""
        self.store.release_test_order(order_no, by)
        order = self.store.order(order_no)
        offer = self.store.offer(order.id)
        if offer is not None:
            self.store.add_system_card(
                offer["conversation_id"],
                f"TESTFREIGABE · {order_no} · ohne Zahlung ({by})",
                order_id=order.id,
            )
        self._orders_changed()

    async def _end_test_orders(self, platform: str, account: str) -> None:
        """Betriebsart verlässt test (SP5 Schritt 12): offene Testaufträge dieses Kontos werden
        abgebrochen (Jobs gestoppt, Grund „Testbetrieb beendet“); keiner bleibt hängen."""
        for order_no in self.store.open_test_orders(platform, account):
            order = self.store.order(order_no)
            for stage in self.store.stages(order.id):
                for j in self.store.stage_jobs(stage.id):
                    if j["status"] in ("queued", "running"):
                        await self._cancel_job(j["id"])
            self.store.transition(order_no, "cancelled", reason="Testbetrieb beendet")
            offer = self.store.offer(order.id)
            if offer is not None:
                self.store.add_system_card(
                    offer["conversation_id"],
                    f"TESTAUFTRAG ABGEBROCHEN · {order_no} · Testbetrieb beendet",
                    order_id=order.id,
                )
        self._orders_changed()

    def _product_status(self, figure: dict, item: dict, *, test: bool = False) -> str:
        """Lieferstand für den Faktenblock des Sprachlaufs: Lieferzeit oder nicht lieferbar."""
        plan = self._offer_plan(figure, item, False, test=test)
        if isinstance(plan, str):
            return "derzeit nicht lieferbar"
        return f"Lieferzeit ca. {eta.minutes(plan.delivery_s)} Minuten"

    async def offer_expiry(self) -> None:
        """Zeitaufgabe: abgelaufene Angebote schließen (cancelled, Grund „abgelaufen“)."""
        while True:
            at = datetime.now(UTC).isoformat(timespec="milliseconds")
            if self.store.expire_offers(at):
                self._orders_changed()
                self._message_changed(0)
                self._wallet_changed()
            await asyncio.sleep(self.cfg.dialog.offer_check_s)

    async def _create_offer(self, msg: commands_pb2.CreateOffer, call: _Call) -> str:
        """Angebot aus der Produktliste (Befehl 46): persönlicher Satz des Betreibers plus
        Faktenblock (SP5 Schritt 2)."""
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
        if msg.product_id:  # feste Produkt-ID (SP5 Schritt 1)
            item = next((p for p in figure["prices"] if p["id"] == msg.product_id), None)
            if item is None:
                return "Produkt unbekannt oder entfernt."
        elif msg.position < len(figure["prices"]):
            item = figure["prices"][msg.position]
        else:
            return "Position der Preisliste unbekannt."
        plan = self._offer_plan(figure, item, msg.hd)
        if isinstance(plan, str):
            return plan
        with self.store.tx():
            order, facts = self._place_offer(plan, msg.customer_id, msg.conversation_id)
            note = msg.note.strip()
            self.store.queue_outbound(
                msg.customer_id,
                msg.conversation_id,
                f"{note}\n\n{facts}" if note else facts,
                revision=msg.revision,
                request_id=call.request_id,
            )
        call.entity = f"order:{order.order_no}"
        adapter.wake.set()
        self._message_changed(0)
        self._wallet_changed()
        self._orders_changed()
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
