"""Beobachtung von Claras öffentlichen Adressen (V0 §8.5 Punkt 4) – nur lesen, nie senden.

BTC über eine Esplora-kompatible Schnittstelle (mempool.space): Guthaben, Eingänge je Ausgang,
Bestätigungen aus der Blockhöhe. BSC über einen öffentlichen RPC-Endpunkt ohne ``eth_getLogs`` (wird
dort verweigert): Block-Header in Paketen, Bloom-Filter je Header auf Token-Vertrag, Transfer-Topic
und Claras Adresse, nur für Kandidaten ``eth_getBlockReceipts``; Fortsetzungspunkt in
``adapter_state``.
Kurse aus einer kostenlosen Kursquelle; Euro-Wert und Kurs werden mit jedem Eingang gespeichert.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from urllib.parse import urlparse

import aiohttp

from ..config import Config, TokenConfig
from ..store import Store
from .addresses import keccak256

log = logging.getLogger("darkfluenzer.wallet")

TRANSFER = keccak256(b"Transfer(address,address,uint256)")
BALANCE_OF = keccak256(b"balanceOf(address)")[:4]
SATOSHI = Decimal(10) ** 8


def bloom_has(bloom: bytes, item: bytes) -> bool:
    """Logs-Bloom (2048 Bit) enthält ``item``: drei Bits aus Keccak-256 (Yellow Paper)."""
    digest = keccak256(item)
    for i in (0, 2, 4):
        bit = int.from_bytes(digest[i : i + 2], "big") & 2047
        if not bloom[255 - bit // 8] & (1 << (bit % 8)):
            return False
    return True


def decimal_text(value: Decimal) -> str:
    """Dezimaltext ohne Exponent (Decimal.normalize() schreibt 10 als „1E+1“)."""
    return format(value.normalize(), "f")


def topic_of(address: str) -> bytes:
    return bytes(12) + bytes.fromhex(address.removeprefix("0x"))


class WalletWatcher:
    """Hält Guthaben, Kurse und Quellenzustand im Speicher (STATE wallet) und schreibt Eingänge
    genau einmal in SQLite (EVENT payments.updated)."""

    def __init__(
        self,
        cfg: Config,
        store: Store,
        on_state: Callable[[], None],
        on_payment: Callable[[], None],
    ) -> None:
        assert cfg.wallet is not None
        self.cfg = cfg
        self.w = cfg.wallet
        self.store = store
        self.on_state = on_state
        self.on_payment = on_payment
        self.rates: dict[str, float] = {}
        self.rate_ms = 0
        self.balances: dict[str, dict[str, Decimal]] = {"btc": {}, "bsc": {}}
        self.checked: dict[str, tuple[int, str]] = {}  # Konto -> (Unix-ms, „Block …“)
        self.errors: dict[str, str] = {}  # Quelle oder Konto -> letzter Fehler
        self.source_ok: dict[str, int] = {}

    # ------------------------------------------------------------------ Ablauf

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.server.timeout_s * 3)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            self._http = http
            while True:
                for name, step in (("price", self._prices), ("btc", self._btc), ("bsc", self._bsc)):
                    try:
                        await step()
                        self.errors.pop(name, None)
                    except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as exc:
                        self.errors[name] = f"{type(exc).__name__}: {str(exc)[:160]}"
                        log.warning("Wallet %s: %s", name, self.errors[name])
                self.errors.pop("watcher", None)  # Runde gelungen: Meldung der Aufsicht erledigt
                self.on_state()
                await asyncio.sleep(self.w.poll_s)

    async def _get(self, url: str, **params: str) -> object:
        async with self._http.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _rpc(self, calls: list[tuple[str, list]]) -> list:
        """JSON-RPC-Paket; Fehler eines Aufrufs bricht die Runde ab (nächste Runde neu)."""
        body = [
            {"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)
        ]
        async with self._http.post(self.w.bsc_rpc, json=body) as resp:
            resp.raise_for_status()
            answers = await resp.json(content_type=None)
        if isinstance(answers, dict):  # Endpunkt lehnt das ganze Paket ab
            raise ValueError(str(answers.get("error", answers))[:160])
        by_id = {a["id"]: a for a in answers}
        out = []
        for i in range(len(calls)):
            answer = by_id.get(i) or {}
            if "error" in answer:
                raise ValueError(str(answer["error"])[:160])
            out.append(answer.get("result"))
        return out

    # ------------------------------------------------------------------ Kurse

    async def _prices(self) -> None:
        ids = [self.w.btc_price_id, *(t.price_id for t in self.w.tokens)]
        data = await self._get(self.w.price_api, ids=",".join(ids), vs_currencies="eur")
        self.rates = {i: float(data[i]["eur"]) for i in ids if i in data}  # type: ignore[index]
        self.rate_ms = int(time.time() * 1000)
        self.source_ok["price"] = self.rate_ms

    def _rate(self, price_id: str) -> float:
        return self.rates.get(price_id, 0.0)

    # ------------------------------------------------------------------ BTC

    async def _btc(self) -> None:
        addr = self.w.btc_address
        if not addr:
            return
        api = self.w.btc_api
        tip = int(await self._get(f"{api}/blocks/tip/height"))  # type: ignore[arg-type]
        stats = await self._get(f"{api}/address/{addr}")
        chain = stats["chain_stats"]  # type: ignore[index]
        self.balances["btc"] = {
            "BTC": Decimal(chain["funded_txo_sum"] - chain["spent_txo_sum"]) / SATOSHI
        }
        # Erfasst wird ab der Einrichtung: ältere bestätigte Eingänge sind keine Auftragszahlungen
        since = self.store.adapter_get("wallet", addr, "btc_since")
        if since is None:
            self.store.adapter_set("wallet", addr, "btc_since", str(tip))
            since = str(tip)
        changed = False
        for tx in await self._get(f"{api}/address/{addr}/txs"):  # type: ignore[union-attr]
            status = tx.get("status") or {}
            height = status.get("block_height") if status.get("confirmed") else None
            if height is not None and height <= int(since):
                continue
            conf = tip - height + 1 if height else 0
            for n, out in enumerate(tx.get("vout") or []):
                if out.get("scriptpubkey_address") != addr:
                    continue
                changed |= self._record(
                    "btc", "bitcoin", "BTC", Decimal(out["value"]) / SATOSHI, tx["txid"], n,
                    height, conf, self.w.btc_confirmations, self.w.btc_price_id,
                )  # fmt: skip
        self.checked["btc"] = (int(time.time() * 1000), f"Block {tip}")
        self.source_ok["btc"] = self.checked["btc"][0]
        if changed:
            self.on_payment()

    # ------------------------------------------------------------------ BSC

    async def _bsc(self) -> None:
        addr = self.w.bsc_address
        if not addr or not self.w.tokens:
            return
        (latest_hex,) = await self._rpc([("eth_blockNumber", [])])
        latest = int(latest_hex, 16)
        cursor = int(self.store.adapter_get("wallet", addr, "bsc_cursor") or latest)
        mine = topic_of(addr)
        changed = False
        start = cursor + 1
        rounds = 0
        while start <= latest and rounds < 20:  # Aufholen in Grenzen, Rest in der nächsten Runde
            end = min(latest, start + self.w.bsc_header_batch - 1)
            headers = await self._rpc(
                [("eth_getHeaderByNumber", [hex(n)]) for n in range(start, end + 1)]
            )
            for header in headers:
                bloom = bytes.fromhex(header["logsBloom"][2:])
                if not (bloom_has(bloom, TRANSFER) and bloom_has(bloom, mine)):
                    continue
                tokens = [
                    t for t in self.w.tokens if bloom_has(bloom, bytes.fromhex(t.contract[2:]))
                ]
                if tokens:
                    changed |= await self._receipts(int(header["number"], 16), tokens, mine)
            self.store.adapter_set("wallet", addr, "bsc_cursor", str(end))
            start, rounds = end + 1, rounds + 1
        changed |= await self._confirm_bsc(latest)
        calls = [
            ("eth_call", [{"to": t.contract, "data": "0x" + (BALANCE_OF + mine).hex()}, "latest"])
            for t in self.w.tokens
        ]
        values = await self._rpc(calls)
        self.balances["bsc"] = {
            t.symbol: Decimal(int(v, 16)) / (Decimal(10) ** t.decimals)
            for t, v in zip(self.w.tokens, values, strict=True)
        }
        self.checked["bsc"] = (int(time.time() * 1000), f"Block {min(start - 1, latest)}")
        self.source_ok["bsc"] = self.checked["bsc"][0]
        if changed:
            self.on_payment()

    async def _receipts(self, block: int, tokens: list[TokenConfig], mine: bytes) -> bool:
        (receipts,) = await self._rpc([("eth_getBlockReceipts", [hex(block)])])
        by_contract = {t.contract.lower(): t for t in tokens}
        changed = False
        for receipt in receipts or []:
            for entry in receipt.get("logs") or []:
                token = by_contract.get(entry["address"].lower())
                topics = entry.get("topics") or []
                if (
                    token is None
                    or len(topics) < 3
                    or bytes.fromhex(topics[0][2:]) != TRANSFER
                    or bytes.fromhex(topics[2][2:]) != mine
                ):
                    continue
                amount = Decimal(int(entry["data"], 16)) / (Decimal(10) ** token.decimals)
                changed |= self._record(
                    token.symbol.lower(), "bsc", token.symbol, amount, entry["transactionHash"],
                    int(entry["logIndex"], 16), block, 1, self.w.bsc_confirmations, token.price_id,
                )  # fmt: skip
        return changed

    async def _confirm_bsc(self, latest: int) -> bool:
        """Bestätigungen nach Blockhöhe. Bevor eine Zahlung als bestätigt gilt, wird ihre
        Transaktion erneut abgefragt (FABLE-014): nicht mehr in der Kette (Reorganisation) oder
        fehlgeschlagen -> bleibt offen; in einen anderen Block verschoben -> zählt ab dort."""
        required = self.w.bsc_confirmations
        payments = self.store.unconfirmed_payments("bsc")
        due = [p for p in payments if latest - p["block"] + 1 >= required]
        found = (
            await self._rpc([("eth_getTransactionReceipt", [p["txid"]]) for p in due])
            if due
            else []
        )
        receipts = {p["id"]: r for p, r in zip(due, found, strict=True)}
        changed = False
        for p in payments:
            block, conf = p["block"], latest - p["block"] + 1
            if p["id"] in receipts:
                receipt = receipts[p["id"]] or {}
                if int(receipt.get("status") or "0x0", 16) != 1 or not receipt.get("blockNumber"):
                    log.warning(
                        "BSC-Zahlung %s: Transaktion %s nicht (mehr) erfolgreich in der Kette",
                        p["id"], p["txid"],
                    )  # fmt: skip
                    conf = 0
                else:
                    block = int(receipt["blockNumber"], 16)
                    conf = latest - block + 1
            changed |= self.store.update_confirmations(p["id"], conf, required, block)
        return changed

    # ------------------------------------------------------------------ Eingänge

    def _record(
        self,
        method: str,
        network: str,
        asset: str,
        amount: Decimal,
        txid: str,
        position: int,
        block: int | None,
        confirmations: int,
        required: int,
        price_id: str,
    ) -> bool:
        rate = self._rate(price_id)
        return self.store.upsert_payment(
            method=method,
            network=network,
            asset=asset,
            amount=decimal_text(amount),
            txid=txid,
            position=position,
            block=block,
            confirmations=confirmations,
            required=required,
            eur=float(amount) * rate if rate else None,
            rate=rate or None,
            rate_ms=self.rate_ms if rate else None,
        )

    # ------------------------------------------------------------------ Zustand

    def accounts(self) -> list[dict]:
        """Kontokarten für STATE wallet (FRONT F7.8)."""
        now_ms = int(time.time() * 1000)
        stale_after = int(self.w.poll_s * 3 * 1000)
        out = []
        for key, title, network, address, error, source in (
            ("btc", "Bitcoin", "bitcoin", self.w.btc_address, self.w.btc_error, self.w.btc_api),
            ("bsc", "BSC", "bsc", self.w.bsc_address, self.w.bsc_error, self.w.bsc_rpc),
        ):
            checked_ms, checked_at = self.checked.get(key, (0, ""))
            prices = {"BTC": self.w.btc_price_id} | {t.symbol: t.price_id for t in self.w.tokens}
            balances = [
                {"asset": a, "amount": decimal_text(v), "eur": float(v) * self._rate(prices[a])}
                for a, v in self.balances.get(key, {}).items()
            ]
            state = (
                "MISSING"
                if not address
                else "ERROR"
                if self.errors.get(key)
                else "STALE"
                if not checked_ms or now_ms - checked_ms > stale_after
                else "OK"
            )
            out.append(
                {
                    "key": key,
                    "title": title,
                    "network": network,
                    "address": address,
                    "balances": balances,
                    "eur_total": sum(b["eur"] for b in balances),
                    "rate_ms": self.rate_ms,
                    "checked_ms": checked_ms,
                    "checked_at": checked_at,
                    "source": urlparse(source).netloc,
                    "state": state,
                    "error": self.errors.get(key, ""),
                    "missing": f"Adresse ungültig: {error}"
                    if error
                    else ("" if address else "Adresse in config.toml [wallet]"),
                }
            )
        return out

    def sources(self) -> list[dict]:
        """Genutzte Datenquellen (ohne Adresse wird die jeweilige Kette nicht abgefragt)."""
        used = (
            ("price", "Kursquelle", self.w.price_api, True),
            ("btc", "BTC-Schnittstelle", self.w.btc_api, bool(self.w.btc_address)),
            ("bsc", "BSC-RPC", self.w.bsc_rpc, bool(self.w.bsc_address and self.w.tokens)),
        )
        return [
            {
                "name": name,
                "url": url,
                "ok_ms": self.source_ok.get(key, 0),
                "error": self.errors.get(key, ""),
            }
            for key, name, url, active in used
            if active
        ] + (
            [{"name": "Beobachter", "url": "", "ok_ms": 0, "error": self.errors["watcher"]}]
            if self.errors.get("watcher")
            else []
        )
