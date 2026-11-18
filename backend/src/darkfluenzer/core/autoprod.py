"""Produktion nach Zahlung (SP5 Schritt 6).

Ist ein Auftrag bezahlt (bzw. ein Testauftrag freigegeben) und die Bildautomatik der
Influencerin an, startet das Backend die Produktion aus dem Produkt: Workflow, Kandidatenzahl,
Prompt aus dem Wunsch am Angebot, aktive LoRA der Figur; bei Video die Animation als
Fertigstellen-Stufe mit eigenem Prompt und der Höchstlänge des Produkts (BUG-090).
Kundenproduktion nur auf Engines mit Nutzung ``production`` und allen Gates (§9.1); Testaufträge
dürfen Erprobungs-Engines nutzen und laufen als Klasse Default. Nach dem Start schreibt Clara
Dank (Profilblock „delivery“, ohne Ziffern) und das Backend hängt die gemessene Lieferzeit an;
bei Verzug geht genau ein vorab erzeugter Vertröst-Text raus.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ..media import models, pipeline
from ..media.pipeline import PipelineError
from ..nodes.comfy import ComfyError
from ..store import StoreError
from . import eta
from .base import log
from .chat import OFFER_TEXT
from .orders import create_order


class AutoProductionMixin:
    """Produktion nach Zahlung; Teil von ``Cockpit``."""

    def _order_figure(self, offer: dict) -> tuple[dict | None, dict | None]:
        """Produkt und Influencerin eines Angebots (über die feste Produkt-ID)."""
        if not offer.get("product_id"):
            return None, None
        try:
            product = self.store.product(offer["product_id"])
        except StoreError:
            return None, None
        figure = next(
            (f for f in self.store.influencers() if f["id"] == product["influencer_id"]), None
        )
        return product, figure

    def _production_notice(self, order, text: str) -> None:
        """Karte genau einmal je Auftrag und Grund (Wiederholung bei jedem Takt vermeiden)."""
        seen = self.__dict__.setdefault("_production_notices", set())
        if (order.id, text) in seen:
            return
        seen.add((order.id, text))
        self._card(order, text)
        self._message_changed(0)

    def _start_paid_orders(self) -> None:
        """Alle bezahlten Aufträge mit Produkt prüfen und, wo möglich, starten."""
        for order in self.store.active_orders("paid"):
            if order.source != "customer":
                continue
            offer = self.store.offer(order.id)
            if offer is not None and not offer.get("production_started_at"):
                self._start_production(order, offer)

    def _start_production(self, order, offer: dict) -> bool:
        product, figure = self._order_figure(offer)
        if product is None or figure is None:
            self._production_notice(
                order, f"PRODUKTION WARTET · {order.order_no} · kein Produkt – im Cockpit starten"
            )
            return False
        if not figure.get("image_auto"):
            return False  # Bildautomatik aus: der Betreiber startet von Hand
        wish = (offer.get("wish") or "").strip()
        if not wish:
            self._production_notice(
                order, f"PRODUKTION WARTET · {order.order_no} · Wunsch fehlt – im Cockpit starten"
            )
            return False
        if problems := self._product_problems(figure, product, test=order.test):
            self._production_notice(
                order, f"PRODUKTION NICHT GESTARTET · {order.order_no} · {'; '.join(problems)}"
            )
            return False
        wf = self.manifest.workflows[product["workflow"]]
        values = {"prompt": wish} if "prompt" in wf.params else {}
        finish, finish_values = "", {}
        if product["kind"] == "video":
            fw = self.manifest.workflows[product["finish_workflow"]]
            finish = fw.key
            if "prompt" in fw.params:
                finish_values["prompt"] = wish
            if fw.video is not None:  # Höchstlänge des Produkts in ganzen Sekunden
                finish_values["duration_s"] = float(max(1, int(product["max_duration_s"])))
        character = figure.get("character_id")
        lora = pipeline.active_lora(self.store, self.manifest, character, wf) if character else ""
        count = product["candidates"] if "seed" in wf.params else 1
        try:
            _no, jobs = create_order(
                self.store, self.manifest, wf.key, values, {}, count=count,
                finish_workflow=finish, finish_values=finish_values,
                customer_order_no=order.order_no, lora=lora,
                character_id=character if lora else None,
                video_max_s=self.cfg.production.video_max_s,
                extra={"influencer_id": figure["id"], "product_id": product["id"]},
            )  # fmt: skip
        except (PipelineError, StoreError, ComfyError, models.ManifestError) as exc:
            self._production_notice(order, f"PRODUKTION NICHT GESTARTET · {order.order_no} · {exc}")
            return False
        self.store.mark_production_started(order.id)
        self._enqueue(jobs)
        self._card(
            order,
            f"PRODUKTION GESTARTET · {order.order_no} · {len(jobs)} Kandidat(en) · {wf.title}"
            + (" + Animation" if finish else ""),
        )
        log.info(
            "Auftrag %s: Produktion nach Zahlung gestartet (%d Jobs)", order.order_no, len(jobs)
        )
        self._orders_changed()
        self._message_changed(0)
        task = asyncio.create_task(self._delivery_note(order, offer, figure))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _delivery_note(self, order, offer: dict, figure: dict) -> None:
        """Dank und Lieferzeit nach dem Start: Formulierung aus dem Profilblock „delivery“ (ohne
        Ziffern und Währungszeichen), die gemessene Lieferzeit hängt das Backend an."""
        persona = self.store.active_persona(figure["id"])
        block = (persona["blocks"].get("delivery", "") if persona else "").strip()
        if persona is None or not block:
            self._card(order, f"DANK · {order.order_no} · Profilblock „Lieferung“ fehlt")
            self._message_changed(0)
            return
        minutes = eta.minutes(offer.get("delivery_s") or 0)
        wf = self._text_workflow("")
        values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
        values |= {
            "context": "",
            "memory": "",
            "facts": (
                f"{offer['product']} bezahlt, Produktion läuft, Lieferzeit ca. {minutes} Minuten"
            ),
            "message": block,
        }
        values |= {k: v for k, v in persona["params"].items() if k in wf.params}
        run = {
            "influencer_id": figure["id"],
            "persona_version": persona["id"],
            "customer_id": order.customer_id,
            "message": "(Dank nach Zahlung)",
            "context": {"order": order.order_no, "delivery_note": True},
        }
        error, run_id, _typed = await self._llm_run(
            "test" if order.test else "chat", wf.key, values, run
        )
        answer = (self.store.ai_run(run_id) or {}).get("answer", "").strip()
        if error or not answer:
            self._card(
                order, f"DANK · {order.order_no} · Sprachlauf fehlgeschlagen: {error or 'leer'}"
            )
            self._message_changed(0)
            return
        text = f"{answer}\n\nLieferzeit ca. {minutes} Minuten"
        digits = bool(OFFER_TEXT.search(answer))
        message_id = self.store.queue_reply(
            order.customer_id, offer["conversation_id"], text,
            status="draft" if digits else "queued", ai_run_id=run_id, test=order.test,
            reason="Dank-Text enthält Ziffern oder ein Währungszeichen." if digits else "",
        )  # fmt: skip
        self._wake(order)
        self._message_changed(message_id)

    def _delay_notices(self) -> None:
        """Zugesagte Lieferzeit überschritten: genau eine Zwischennachricht je Auftrag (vorab
        erzeugter Vertröst-Text der Influencerin), sonst Karte."""
        at = datetime.now(UTC).isoformat(timespec="milliseconds")
        for row in self.store.delayed_orders(at):
            order = self.store.order(row["order_no"])
            offer = self.store.offer(order.id)
            _product, figure = self._order_figure(offer or {})
            self.store.mark_delay_notice(order.id)
            persona = self.store.active_persona(figure["id"]) if figure else None
            found = self.store.take_consolation(persona["id"]) if persona else None
            if found is None:
                self._card(order, f"VERZUG · {order.order_no} · kein Vertröst-Text vorrätig")
                self._message_changed(0)
                continue
            cid, text, run_id = found
            message_id = self.store.queue_reply(
                order.customer_id, row["conversation_id"], text, status="queued",
                ai_run_id=run_id, test=order.test,
            )  # fmt: skip
            self.store.mark_consolation_used(cid, message_id)
            self._card(order, f"VERZUG · {order.order_no} · Zwischennachricht gesendet")
            self._wake(order)
            self._message_changed(message_id)
