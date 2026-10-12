"""vCard QR as SVG (no external dependencies)."""
from __future__ import annotations

from servicesystem.services.qrcodegen import QrCode


def vcard_qr_svg(data: str, *, size_px: int = 256, border: int = 4) -> str:
    qr = QrCode.encode_text(data, QrCode.Ecc.MEDIUM)
    modules = qr.get_size()
    total = modules + border * 2
    rects: list[str] = []
    for y in range(modules):
        for x in range(modules):
            if qr.get_module(x, y):
                rects.append(f'<rect x="{x + border}" y="{y + border}" width="1" height="1"/>')
    body = "".join(rects)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{size_px}" height="{size_px}" role="img" aria-label="QR vCard">'
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>'
        f'<g fill="#0f2d5c">{body}</g></svg>'
    )
