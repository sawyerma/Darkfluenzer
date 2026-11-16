"""Zahlungseingang (V0 §8.5, C5a): Adressprüfung gegen die Testvektoren der Spezifikationen."""

from __future__ import annotations

from darkfluenzer.payments import addresses as a


def test_keccak256_vectors():
    assert a.keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert a.keccak256(b"abc").hex() == (
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    )
    long = a.keccak256(b"a" * 200).hex()  # mehr als ein Block (rate 136)
    assert len(long) == 64 and long != a.keccak256(b"a" * 199).hex()


def test_eip55_vectors():
    for addr in (  # EIP-55 Testvektoren
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    ):
        assert a.evm_address_error(addr) == ""
    assert "Prüfsumme falsch" in a.evm_address_error("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")
    assert "ohne EIP-55" in a.evm_address_error("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
    assert "keine EVM" in a.evm_address_error("0x1234")


def test_bech32_vectors():
    assert a.btc_address_error("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4") == ""  # BIP-173
    assert (
        a.btc_address_error(  # BIP-350, Taproot (v1, Bech32m)
            "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
        )
        == ""
    )
    assert a.btc_address_error("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5") == "Prüfsumme falsch"
    assert "Native-SegWit" in a.btc_address_error("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    assert a.btc_address_error("bc1Qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") != ""  # gemischt


def test_bloom_detects_contained_items_only():
    from darkfluenzer.payments.chain import bloom_has

    bloom = bytearray(256)
    for item in (b"token", b"topic"):
        digest = a.keccak256(item)
        for i in (0, 2, 4):
            bit = int.from_bytes(digest[i : i + 2], "big") & 2047
            bloom[255 - bit // 8] |= 1 << (bit % 8)
    assert bloom_has(bytes(bloom), b"token") and bloom_has(bytes(bloom), b"topic")
    assert not bloom_has(bytes(bloom), b"andere-adresse")


def test_inflow_once_then_unassigned_after_confirmations(tmp_path):
    from darkfluenzer.store import Store

    store = Store(tmp_path / "local")
    args = dict(
        method="usdt", network="bsc", asset="USDT", amount="24.9937", txid="0xabc",
        position=3, block=100, confirmations=1, required=15, eur=22.7, rate=0.908, rate_ms=1,
    )  # fmt: skip
    assert store.upsert_payment(**args) is True
    assert store.upsert_payment(**args) is False  # genau einmal
    (row,) = store.unconfirmed_payments("bsc")
    assert row["status"] == "detected" and row["amount"] == "24.9937"
    assert store.update_confirmations(row["id"], 14, 15) is True
    assert store.update_confirmations(row["id"], 15, 15) is True
    assert store.payment(row["id"])["status"] == "unassigned"  # kein passendes Angebot
    assert store.update_confirmations(row["id"], 40, 15) is False  # danach unveränderlich
    assert [p["id"] for p in store.payment_page(0, 10, "unassigned")[0]] == [row["id"]]
    assert store.payment_page(0, 10, "open")[0] == []
    events, _ = store.payment_events(0, 10)
    assert [e["payment_id"] for e in events] == [row["id"]] * 3
    store.close()


def test_wallet_config_checks_addresses(tmp_path):
    import pytest
    from conftest import write_config as wc

    from darkfluenzer import config

    wc(tmp_path)
    cfg_file = tmp_path / "local" / "config.toml"
    cfg_file.write_text(
        cfg_file.read_text()
        + '\n[wallet]\nbtc_address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5"\n'
        + 'bsc_address = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"\n'
    )
    w = config.load(tmp_path).wallet
    assert w.btc_address == "" and w.btc_error == "Prüfsumme falsch"  # ungültig: leer + Grund
    assert w.bsc_address == "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed" and w.bsc_error == ""
    cfg_file.write_text(
        cfg_file.read_text()
        + '\n[wallet.tokens.USDT]\ncontract = "0x55d398326f99059ff775485246999027b3197955"\n'
    )
    with pytest.raises(config.ConfigError, match="EIP-55"):
        config.load(tmp_path)


def test_decimal_text_has_no_exponent():
    from decimal import Decimal

    from darkfluenzer.payments.chain import decimal_text

    assert decimal_text(Decimal("10.000")) == "10"
    assert decimal_text(Decimal("0.00012300")) == "0.000123"
    assert decimal_text(Decimal(2427573233001881212) / Decimal(10) ** 18) == "2.427573233001881212"
