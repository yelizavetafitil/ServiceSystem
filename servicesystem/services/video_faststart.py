"""Перенос атома moov перед mdat (faststart).

Телефонные MP4/MOV часто пишут оглавление в конец файла. Плеер тогда
не начинает показ, пока не скачает ролик целиком, и поток «лагает» на загрузке.
"""

from __future__ import annotations

import os
import tempfile

_MP4_BRANDS = {
    b"mp41",
    b"mp42",
    b"isom",
    b"iso2",
    b"iso5",
    b"iso6",
    b"avc1",
    b"dash",
    b"msnv",
}


def video_content_type(path: str, filename: str = "") -> str:
    """MP4 внутри .mov браузер не играет, если отдать video/quicktime."""
    import mimetypes

    guessed = mimetypes.guess_type(filename or path)[0]
    try:
        with open(path, "rb") as fh:
            hdr = fh.read(16)
    except OSError:
        hdr = b""
    if len(hdr) >= 12 and hdr[4:8] == b"ftyp":
        brand = hdr[8:12]
        if brand in _MP4_BRANDS or brand[:2] == b"mp":
            return "video/mp4"
    if hdr[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return guessed or "video/mp4"


_CONTAINERS = {
    b"moov",
    b"trak",
    b"edts",
    b"mdia",
    b"minf",
    b"stbl",
    b"mvex",
    b"moof",
    b"traf",
    b"udta",
}


def _patch_offsets(data: bytearray, start: int, end: int, shift: int) -> None:
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos : pos + 4], "big")
        typ = bytes(data[pos + 4 : pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = int.from_bytes(data[pos + 8 : pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        body = pos + header
        if typ in _CONTAINERS:
            _patch_offsets(data, body, pos + size, shift)
        elif typ in (b"stco", b"co64"):
            width = 4 if typ == b"stco" else 8
            if body + 8 > pos + size:
                return
            count = int.from_bytes(data[body + 4 : body + 8], "big")
            off = body + 8
            for _ in range(count):
                if off + width > pos + size:
                    return
                val = int.from_bytes(data[off : off + width], "big")
                data[off : off + width] = (val + shift).to_bytes(width, "big")
                off += width
        pos += size


def _top_atoms(path: str):
    atoms = []
    file_size = os.path.getsize(path)
    with open(path, "rb") as fh:
        pos = 0
        while pos + 8 <= file_size:
            fh.seek(pos)
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            size = int.from_bytes(hdr[:4], "big")
            typ = hdr[4:8]
            header = 8
            if size == 1:
                ext = fh.read(8)
                if len(ext) < 8:
                    break
                size = int.from_bytes(ext, "big")
                header = 16
            elif size == 0:
                size = file_size - pos
            if size < header or pos + size > file_size:
                break
            atoms.append((pos, size, typ))
            pos += size
    return atoms


def make_faststart(path: str) -> bool:
    """Если moov стоит после mdat — переписать файл. True, если файл изменён."""
    atoms = _top_atoms(path)
    moov = next((a for a in atoms if a[2] == b"moov"), None)
    mdat = next((a for a in atoms if a[2] == b"mdat"), None)
    if not moov or not mdat or moov[0] < mdat[0]:
        return False
    if any(a[2] == b"moof" for a in atoms):
        return False
    moov_pos, moov_size, _ = moov
    if moov_size > 256 * 1024 * 1024:
        return False

    with open(path, "rb") as fh:
        fh.seek(moov_pos)
        moov_bytes = bytearray(fh.read(moov_size))
    if len(moov_bytes) != moov_size:
        return False
    _patch_offsets(moov_bytes, 0, len(moov_bytes), moov_size)

    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".faststart-", dir=directory)
    os.close(fd)
    try:
        with open(path, "rb") as src, open(tmp_path, "wb") as out:
            for pos, size, typ in atoms:
                if typ == b"mdat":
                    out.write(moov_bytes)
                if typ == b"moov":
                    continue
                src.seek(pos)
                remaining = size
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return True
