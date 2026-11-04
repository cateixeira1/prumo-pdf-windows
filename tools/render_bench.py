"""
Medida no CI (Windows de verdade): perfil do computador e quanto custa desenhar uma página,
do jeito antigo (RGB de 3 bytes, várias cópias) e do atual (formato do Qt, uma cópia).

Uso: python tools/render_bench.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core  # noqa: E402
import fixtures  # noqa: E402
import machine  # noqa: E402
import services  # noqa: E402

app = QApplication.instance() or QApplication([])


def old_render(path, page, px):
    with core.PDFIUM_LOCK:
        pdf = core.open_for_render(str(path))
        pg = pdf[page]
        bmp = pg.render(scale=px / pg.get_width(), rev_byteorder=True)
        pil = bmp.to_pil().convert("RGB")
        pg.close()
        pdf.close()
    return QImage(pil.tobytes(), pil.width, pil.height, pil.width * 3, QImage.Format_RGB888).copy()


def timed(fn, n=5):
    fn()
    t = time.perf_counter()
    for _ in range(n):
        out = fn()
    return (time.perf_counter() - t) / n * 1000, out


def main():
    m = machine.current()
    print(f"computador: {m.describe()}")
    print(f"OCR: {machine.ocr_jobs(False, m)} páginas ao mesmo tempo ({machine.ocr_jobs(True, m)} na precisão máxima)")
    print(f"memória: leitor {machine.page_cache_bytes(m) // machine.MB} MB, miniaturas {machine.thumb_cache_bytes(m) // machine.MB} MB")
    tmp = Path(tempfile.mkdtemp(prefix="prumo_bench_"))
    scan = fixtures.scanned_pdf(tmp / "scan.pdf", 1)
    for px in (300, 1800, 3600):
        a, _ = timed(lambda: old_render(scan, 0, px))
        b, _ = timed(lambda: services.render_page(scan, 0, px))
        print(f"desenhar página {px:4d} px: antes {a:6.1f} ms, agora {b:6.1f} ms")
    target = QImage(1200, 1400, QImage.Format_ARGB32_Premultiplied)
    for name, img in (("antes (RGB888)", old_render(scan, 0, 1800)), ("agora (RGB32)", services.render_page(scan, 0, 1800))):
        p = QPainter(target)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(10, 10, 900, 900 * img.height() / img.width())
        ms, _ = timed(lambda: p.drawImage(r, img), 30)
        p.end()
        print(f"pintar página na tela, {name}: {ms:.2f} ms")


if __name__ == "__main__":
    main()
