"""KI-Kennzeichnung in jeder über einen Kanal versandten Datei (PHASENPLAN_V0 Regel 12 d).

Die Zustellkopie trägt XMP ``Iptc4xmpExt:DigitalSourceType = trainedAlgorithmicMedia``; das
Original in Dateien bleibt unverändert. Eingebettete Erzeugungsdaten (ComfyUI schreibt Workflow und
Prompt in PNG-Textblöcke bzw. die MP4-Metadaten) verlassen den Mac nicht: PNG-Textblöcke und
vorhandenes XMP werden entfernt, in MP4/MOV werden die Metadatenblöcke ``moov/udta``/``moov/meta``
und altes XMP zu ``free`` mit genulltem Inhalt (gleiche Größe, keine Versätze ändern sich). Andere
Dateitypen werden nicht versandt.
"""

from __future__ import annotations

import os
import shutil
import struct
import zlib
from pathlib import Path

DIGITAL_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
XMP = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about=""'
    ' xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'
    f' Iptc4xmpExt:DigitalSourceType="{DIGITAL_SOURCE}"/>'
    "</rdf:RDF></x:xmpmeta>"
    '<?xpacket end="r"?>'
).encode()

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_TEXT = {b"tEXt", b"zTXt", b"iTXt"}
JPEG_XMP = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")  # XMP in ISO-BMFF (Adobe XMP Teil 3)
SUFFIXES = {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".m4v"}


class AiMetaError(Exception):
    """Datei kann nicht gekennzeichnet werden (Typ unbekannt oder Aufbau fehlerhaft)."""


def _png(data: bytes) -> bytes:
    if not data.startswith(PNG_SIGNATURE):
        raise AiMetaError("keine PNG-Datei")
    out, pos, marked = [PNG_SIGNATURE], len(PNG_SIGNATURE), False
    while pos < len(data):
        if pos + 8 > len(data):
            raise AiMetaError("PNG abgeschnitten")
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise AiMetaError("PNG abgeschnitten")
        if kind not in PNG_TEXT:  # Erzeugungsdaten und altes XMP bleiben auf dem Mac
            out.append(data[pos:end])
        if kind == b"IHDR" and not marked:
            body = b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + XMP
            crc = zlib.crc32(b"iTXt" + body) & 0xFFFFFFFF
            out.append(struct.pack(">I4s", len(body), b"iTXt") + body + struct.pack(">I", crc))
            marked = True
        pos = end
        if kind == b"IEND":
            break
    if not marked:
        raise AiMetaError("PNG ohne IHDR")
    return b"".join(out)


def _jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise AiMetaError("keine JPEG-Datei")
    segment = JPEG_XMP + XMP
    app1 = b"\xff\xe1" + struct.pack(">H", len(segment) + 2) + segment
    out, pos, inserted = [b"\xff\xd8"], 2, False
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise AiMetaError("JPEG-Segment fehlerhaft")
        marker = data[pos + 1]
        if marker == 0xDA:  # Bilddaten: Rest unverändert
            break
        end = pos + 2 + struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if not inserted and marker != 0xE0:  # nach JFIF-APP0, vor allem anderen
            out.append(app1)
            inserted = True
        old_xmp = marker == 0xE1 and data[pos + 4 : end].startswith(JPEG_XMP)
        if not old_xmp and marker != 0xFE:  # altes XMP und Kommentare entfallen
            out.append(data[pos:end])
        pos = end
    if not inserted:
        out.append(app1)
    out.append(data[pos:])
    return b"".join(out)


CHUNK = 4 * 2**20  # Blockgröße beim Kopieren, Nullen und Suchen (kein Ganzdatei-Puffer)


def _boxes(f, start: int, end: int):
    """Kisten zwischen ``start`` und ``end``; liest nur die Köpfe (mdat bleibt auf der Platte)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", f.read(8))[0], 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise AiMetaError("MP4-Box fehlerhaft")
        yield pos, size, kind, header
        pos += size


def _mp4(src: Path, tmp: Path) -> None:
    """MP4/MOV blockweise: Kopie der Datei, darin ``moov/udta``, ``moov/meta`` und altes XMP zu
    ``free`` mit genulltem Inhalt (Größe und Versätze bleiben), neue XMP-Kiste am Ende. Kein
    Ganzdatei-Puffer, damit eine große Datei den Hauptstrang nicht über die GIL blockiert
    (SP0 Schritt 5)."""
    blank, kinds = [], set()
    with open(src, "rb") as f:
        for pos, size, kind, header in list(_boxes(f, 0, src.stat().st_size)):
            kinds.add(kind)
            if kind == b"uuid":
                f.seek(pos + header)
                if f.read(16) == XMP_UUID:
                    blank.append((pos, size, header))  # altes XMP
            if kind == b"moov":
                for inner, inner_size, sub, inner_header in list(
                    _boxes(f, pos + header, pos + size)
                ):
                    if sub in (b"udta", b"meta"):
                        blank.append((inner, inner_size, inner_header))
    if b"moov" not in kinds or b"ftyp" not in kinds:
        raise AiMetaError("keine MP4/MOV-Datei")
    shutil.copyfile(src, tmp)
    box = XMP_UUID + XMP
    with open(tmp, "r+b") as out:
        for pos, size, header in blank:
            out.seek(pos + 4)
            out.write(b"free")
            out.seek(pos + header)
            left = size - header
            while left:
                n = min(left, CHUNK)
                out.write(bytes(n))
                left -= n
        out.seek(0, os.SEEK_END)
        out.write(struct.pack(">I4s", len(box) + 8, b"uuid") + box)


def mark(src: Path, dst: Path) -> None:
    """Gekennzeichnete Zustellkopie von ``src`` nach ``dst`` (schreibgeschützt)."""
    suffix = src.suffix.lower()
    if suffix not in SUFFIXES:
        raise AiMetaError(f"Dateityp {suffix or 'ohne Endung'} kann nicht gekennzeichnet werden")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    if tmp.exists():
        os.chmod(tmp, 0o644)
        tmp.unlink()
    if suffix == ".png":
        tmp.write_bytes(_png(src.read_bytes()))
    elif suffix in (".jpg", ".jpeg"):
        tmp.write_bytes(_jpeg(src.read_bytes()))
    else:
        _mp4(src, tmp)
    os.chmod(tmp, 0o444)
    os.replace(tmp, dst)


def is_marked(path: Path) -> bool:
    """Trägt die Datei die Kennzeichnung? (Abgleich vor dem Versand)"""
    needle = DIGITAL_SOURCE.encode()
    tail = b""
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):  # blockweise, auch über Blockgrenzen
            if needle in chunk or needle in tail + chunk[: len(needle) - 1]:
                return True
            tail = chunk[-(len(needle) - 1) :]
    return False
