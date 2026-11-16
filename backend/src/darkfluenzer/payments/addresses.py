"""Prüfung öffentlicher Adressen beim Start (V0 §8.5 Punkt 1): Format und Prüfsumme.

BTC: Bech32/Bech32m nach BIP-173/BIP-350 (Native SegWit ``bc1…``). EVM (BSC): EIP-55-Prüfsumme
über Keccak-256 (Ethereum-Variante mit Keccak-Padding, nicht SHA3-256). Beide nach den
Referenzspezifikationen, geprüft gegen deren Testvektoren.
"""

from __future__ import annotations

# ------------------------------------------------------------------ Bech32 / Bech32m

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32, _BECH32M = 1, 0x2BC830A3


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _convertbits(data: list[int], frombits: int, tobits: int) -> list[int] | None:
    acc, bits, out, maxv = 0, 0, [], (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return out


def btc_address_error(address: str, hrp: str = "bc") -> str:
    """Leer, wenn ``address`` eine gültige SegWit-Adresse ist, sonst der Grund."""
    if not address.lower().startswith(f"{hrp}1"):
        return f"keine Native-SegWit-Adresse ({hrp}1…)"
    if address != address.lower() and address != address.upper():
        return "gemischte Groß-/Kleinschreibung"
    addr = address.lower()
    pos = addr.rfind("1")
    if addr[:pos] != hrp or pos + 7 > len(addr) or len(addr) > 90:
        return f"keine Native-SegWit-Adresse ({hrp}1…)"
    if any(c not in _CHARSET for c in addr[pos + 1 :]):
        return "ungültiges Zeichen"
    data = [_CHARSET.find(c) for c in addr[pos + 1 :]]
    const = _polymod([ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + data)
    if const not in (_BECH32, _BECH32M):
        return "Prüfsumme falsch"
    version, program = data[0], _convertbits(data[1:-6], 5, 8)
    if program is None or not 2 <= len(program) <= 40 or version > 16:
        return "Programm ungültig"
    if version == 0 and (const != _BECH32 or len(program) not in (20, 32)):
        return "SegWit v0 ungültig"
    if version > 0 and const != _BECH32M:
        return "SegWit v1+ braucht Bech32m"
    return ""


# ------------------------------------------------------------------ Keccak-256 / EIP-55

_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)  # fmt: skip
_ROT = ((0, 36, 3, 41, 18), (1, 44, 10, 45, 2), (62, 6, 43, 15, 61), (28, 55, 25, 21, 56),
        (27, 20, 39, 8, 14))  # fmt: skip
_MASK = (1 << 64) - 1


def _rotl(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def _keccak_f(a: list[int]) -> list[int]:
    for rc in _RC:
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        a = [a[i] ^ d[i % 5] for i in range(25)]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(a[x + 5 * y], _ROT[x][y])
        a = [
            b[i] ^ ((~b[(i + 1) % 5 + 5 * (i // 5)]) & _MASK & b[(i + 2) % 5 + 5 * (i // 5)])
            for i in range(25)
        ]
        a[0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    pad = rate - len(data) % rate
    msg = data + (b"\x81" if pad == 1 else b"\x01" + b"\x00" * (pad - 2) + b"\x80")
    state = [0] * 25
    for off in range(0, len(msg), rate):
        for i in range(rate // 8):
            state[i] ^= int.from_bytes(msg[off + 8 * i : off + 8 * i + 8], "little")
        state = _keccak_f(state)
    return b"".join(lane.to_bytes(8, "little") for lane in state[:4])


def eip55(address: str) -> str:
    """Adresse in EIP-55-Schreibweise (gemischte Groß-/Kleinschreibung als Prüfsumme)."""
    hex_part = address.lower().removeprefix("0x")
    digest = keccak256(hex_part.encode()).hex()
    return "0x" + "".join(
        c.upper() if c.isalpha() and int(digest[i], 16) >= 8 else c for i, c in enumerate(hex_part)
    )


def evm_address_error(address: str) -> str:
    """Leer, wenn ``address`` eine gültige EVM-Adresse mit korrekter EIP-55-Prüfsumme ist (reine
    Klein- oder Großschreibung trägt keine Prüfsumme und wird abgewiesen)."""
    hex_part = address.removeprefix("0x")
    if not address.startswith("0x") or len(hex_part) != 40:
        return "keine EVM-Adresse (0x + 40 Hex-Zeichen)"
    if any(c not in "0123456789abcdefABCDEF" for c in hex_part):
        return "ungültiges Zeichen"
    if hex_part in (hex_part.lower(), hex_part.upper()):
        return "ohne EIP-55-Prüfsumme (aus MetaMask kopieren)"
    if eip55(address) != address:
        return "EIP-55-Prüfsumme falsch"
    return ""
