"""
Plugin do OCRmyPDF usado pelo Prumo PDF.

1. Mede a confiança do Tesseract em cada página: depois que o Tesseract gera o
   hOCR de uma página, lemos o valor x_wconf de cada palavra (0 a 100) e
   calculamos a média. É a confiança do próprio motor, não uma garantia de
   acerto: serve para indicar quais páginas merecem revisão.
2. Repassa o progresso para a interface.

O canal de saída (EMIT) é definido pelo processo de OCR antes de rodar.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from ocrmypdf import hookimpl
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine

EMIT = None            # função(dict) definida pelo worker
_LOCK = threading.Lock()

_WCONF = re.compile(r"x_wconf\s+(\d+)")
_WORD = re.compile(r"class=['\"]ocrx_word['\"][^>]*title=['\"]([^'\"]*)['\"][^>]*>(.*?)</span>", re.S)
_TAG = re.compile(r"<[^>]+>")
_PAGE_FROM_NAME = re.compile(r"^(\d+)")


def _emit(event: dict) -> None:
    if EMIT is not None:
        with _LOCK:
            EMIT(event)


def page_confidence(hocr_text: str) -> tuple[float | None, int, int]:
    """Devolve (confiança média ponderada por caracteres, nº de palavras, nº de palavras < 60)."""
    total_w = 0.0
    total_chars = 0
    words = 0
    low = 0
    for title, inner in _WORD.findall(hocr_text):
        m = _WCONF.search(title)
        if not m:
            continue
        word = _TAG.sub("", inner).strip()
        if not word:
            continue
        conf = int(m.group(1))
        n = len(word)
        total_w += conf * n
        total_chars += n
        words += 1
        if conf < 60:
            low += 1
    if not total_chars:
        return None, 0, 0
    return total_w / total_chars, words, low


class ConfidenceTesseract(TesseractOcrEngine):
    """Tesseract padrão + registro da confiança por página."""

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        TesseractOcrEngine.generate_hocr(input_file, output_hocr, output_text, options)
        try:
            m = _PAGE_FROM_NAME.match(Path(input_file).name)
            page = int(m.group(1)) if m else None
            text = Path(output_hocr).read_text(encoding="utf-8", errors="replace")
            conf, words, low = page_confidence(text)
            _emit({"type": "page_conf", "page": page, "conf": conf,
                   "words": words, "low_words": low})
        except Exception as exc:  # a medição nunca pode derrubar o OCR
            _emit({"type": "log", "message": f"Confiança indisponível: {exc}"})


class UiProgressBar:
    """Implementa o protocolo ProgressBar do OCRmyPDF repassando eventos."""

    def __init__(self, *, total=None, desc=None, unit=None, disable=False, **kwargs):
        self.total = total
        self.desc = desc or ""
        self.unit = unit or ""
        self.done = 0.0

    def __enter__(self):
        _emit({"type": "stage", "desc": self.desc, "total": self.total, "unit": self.unit})
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, n=1, *, completed=None, **kwargs):
        if completed is not None:
            self.done = completed
        else:
            self.done += n or 0
        # Limita a frequência dos avisos para não sobrecarregar a interface.
        now = time.monotonic()
        finished = self.total is not None and self.done >= self.total
        if not finished and now - getattr(self, "_last", 0.0) < 0.2:
            return
        self._last = now
        _emit({"type": "progress", "desc": self.desc, "done": self.done,
               "total": self.total, "unit": self.unit})


@hookimpl
def get_ocr_engine(options):
    return ConfidenceTesseract()


@hookimpl
def get_progressbar_class():
    return UiProgressBar
