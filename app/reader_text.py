"""
Texto do PDF para o modo leitor e para a busca, sem interface.

- `page_texts`: texto de cada página (pelo PDFium).
- `reflow`: junta as linhas de uma página em parágrafos (o mesmo critério do iPhone: frase
  terminada em linha curta, títulos em maiúsculas, marcadores de lista; palavras hifenizadas
  no fim da linha são reunidas).
- `Folded` / `find_all`: busca que ignora acentos e maiúsculas ("indenizacao" acha "Indenização"),
  devolvendo as posições no texto original.
- `search_pdf`: resultados com os retângulos de cada ocorrência, para destacar na página.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import core

BULLET = re.compile(r"^\s*([•\-–—*▪●◦]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)]|[IVXLC]{1,6}[.)\-–])\s+")
SENTENCE_END = re.compile(r"[.!?:;…][\"'”»)]*$")


# --- Busca sem acentos ------------------------------------------------------------

class Folded:
    """Texto "dobrado" (sem acentos, minúsculo) com o mapa de volta para as posições originais."""

    def __init__(self, text: str):
        out, back = [], []
        for i, ch in enumerate(text):
            f = unicodedata.normalize("NFD", ch)
            f = "".join(c for c in f if not unicodedata.combining(c)).casefold()
            if ch in "\r\n\t  ":
                f = " "
            for c in f:
                out.append(c)
                back.append(i)
        self.text = "".join(out)
        self.back = back
        self.original = text

    @staticmethod
    def fold_query(q: str) -> str:
        f = unicodedata.normalize("NFD", q)
        f = "".join(c for c in f if not unicodedata.combining(c)).casefold()
        return re.sub(r"\s+", " ", f).strip()

    def find_all(self, query: str) -> list[tuple[int, int]]:
        """Ocorrências como (início, fim) no texto original (fim exclusivo)."""
        q = self.fold_query(query)
        if not q:
            return []
        hay = re.sub(r"\s", " ", self.text)
        out, start = [], 0
        while True:
            i = hay.find(q, start)
            if i < 0:
                break
            j = i + len(q) - 1
            out.append((self.back[i], self.back[j] + 1))
            start = i + max(1, len(q))
        return out


def find_all(text: str, query: str) -> list[tuple[int, int]]:
    return Folded(text).find_all(query)


# --- Texto das páginas e parágrafos ----------------------------------------------

def page_texts(path, password: str | None = None) -> list[str]:
    import pypdfium2 as pdfium

    out = []
    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path), password=password)
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                tp = page.get_textpage()
                try:
                    out.append(tp.get_text_range() or "")
                finally:
                    tp.close()
                    page.close()
        finally:
            pdf.close()
    return out


def _is_title(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters) and len(line) <= 90


_SPACES = re.compile(r"[ \t\xa0]+")


def _clean_line(line: str, start: int) -> tuple[str, list[int]]:
    """Uma linha com os espaços repetidos trocados por um só e sem espaços nas pontas,
    com a posição de cada caractere no texto da página."""
    out: list[str] = []
    idx: list[int] = []
    pos = 0
    for m in _SPACES.finditer(line):
        for k in range(pos, m.start()):
            out.append(line[k])
            idx.append(start + k)
        out.append(" ")
        idx.append(start + m.start())
        pos = m.end()
    for k in range(pos, len(line)):
        out.append(line[k])
        idx.append(start + k)
    text = "".join(out)
    lead = len(text) - len(text.lstrip())
    trail = len(text.rstrip())
    return text[lead:trail], idx[lead:trail]


def reflow_mapped(text: str) -> list[tuple[str, list[int]]]:
    """
    Linhas de uma página → parágrafos, cada um com a posição (no texto da página) de cada
    caractere; espaços criados ao juntar linhas ficam com -1. Usado pelo modo leitor para
    destacar no PDF o trecho escolhido no texto corrido.
    """
    lines: list[tuple[str, list[int]]] = []
    pos = 0
    for m in re.finditer(r"\r\n|\r|\n", text):
        lines.append(_clean_line(text[pos:m.start()], pos))
        pos = m.end()
    lines.append(_clean_line(text[pos:], pos))
    if not any(t for t, _ in lines):
        return []
    longest = max((len(t) for t, _ in lines if t), default=0)
    paras: list[tuple[str, list[int]]] = []
    cur, cur_idx = "", []
    prev = ""
    for line, idx in lines:
        if not line:
            if cur:
                paras.append((cur, cur_idx))
                cur, cur_idx = "", []
            prev = ""
            continue
        both_titles = _is_title(prev) and _is_title(line) and not SENTENCE_END.search(prev)
        new_para = (not cur or BULLET.match(line) is not None
                    or (not both_titles and (_is_title(prev) or _is_title(line)))
                    or (SENTENCE_END.search(prev) is not None and len(prev) < 0.75 * longest)
                    or len(prev) < 0.5 * longest)   # só a última linha de um parágrafo é curta
        if new_para:
            if cur:
                paras.append((cur, cur_idx))
            cur, cur_idx = line, list(idx)
        else:
            if re.search(r"[A-Za-zÀ-ÿ]-$", cur) and line[:1].islower():
                cur, cur_idx = cur[:-1] + line, cur_idx[:-1] + list(idx)   # palavra hifenizada no fim da linha
            else:
                cur, cur_idx = f"{cur} {line}", cur_idx + [-1] + list(idx)
        prev = line
    if cur:
        paras.append((cur, cur_idx))
    return paras


def reflow(text: str) -> list[str]:
    """Linhas de uma página → parágrafos."""
    return [t for t, _ in reflow_mapped(text)]


@dataclass
class ReaderPage:
    number: int               # começa em 1
    paragraphs: list[str]


def reader_pages(path, password: str | None = None) -> list[ReaderPage]:
    return [ReaderPage(i + 1, reflow(t)) for i, t in enumerate(page_texts(path, password))]


# --- Busca dentro do PDF (para destacar na página) ----------------------------------

@dataclass
class Hit:
    page: int                                     # começa em 0
    rects: list[tuple[float, float, float, float]]  # (x0, y0, x1, y1) em pontos, origem no alto à esquerda


def search_page(pdf, index: int, query: str) -> list[Hit]:
    page = pdf[index]
    tp = page.get_textpage()
    try:
        text = tp.get_text_range() or ""
        geom = PageGeom(page)
        hits = []
        for a, b in find_all(text, query):
            n = tp.count_rects(a, b - a)
            rects = [geom.rect_to_view(tp.get_rect(k)) for k in range(n)]
            if rects:
                hits.append(Hit(index, rects))
        return hits
    finally:
        tp.close()
        page.close()


# --- Posições na página (com recorte e giro) ------------------------------------------

class PageGeom:
    """
    Converte entre o espaço do PDF (origem embaixo à esquerda, sem giro) e a página como ela
    aparece na tela, em pontos, com origem no alto à esquerda e já com o recorte (CropBox) e o
    giro (/Rotate) aplicados. Usa a mesma conta do PDFium ao desenhar a página.
    """

    SCALE = 16.0

    def __init__(self, page):
        import ctypes

        import pypdfium2.raw as pdfium_c

        w, h = page.get_size()
        self.w, self.h = float(w), float(h)
        sx, sy = max(1, int(round(self.w * self.SCALE))), max(1, int(round(self.h * self.SCALE)))

        def dev(x, y):
            dx, dy = ctypes.c_int(), ctypes.c_int()
            pdfium_c.FPDF_PageToDevice(page, 0, 0, sx, sy, 0, x, y, dx, dy)
            return dx.value / sx * self.w, dy.value / sy * self.h

        (ox, oy), (ax, ay), (bx, by) = dev(0.0, 0.0), dev(1000.0, 0.0), dev(0.0, 1000.0)
        self.a, self.b = (ax - ox) / 1000.0, (ay - oy) / 1000.0
        self.c, self.d = (bx - ox) / 1000.0, (by - oy) / 1000.0
        self.e, self.f = ox, oy
        det = self.a * self.d - self.b * self.c
        self.det = det if abs(det) > 1e-9 else 1e-9

    def to_view(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def to_pdf(self, u: float, v: float) -> tuple[float, float]:
        u, v = u - self.e, v - self.f
        return (self.d * u - self.c * v) / self.det, (-self.b * u + self.a * v) / self.det

    def rect_to_view(self, r) -> tuple[float, float, float, float]:
        """(esquerda, baixo, direita, alto) do PDF → (x0, y0, x1, y1) na tela, em pontos."""
        l, b, ri, t = r
        p1, p2 = self.to_view(l, b), self.to_view(ri, t)
        return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))


# --- Camada de texto para selecionar com o mouse -------------------------------------

class TextLayer:
    """
    Texto da página com a posição de cada caractere, para selecionar com o mouse, copiar,
    destacar e montar o resumo. Abre o PDF a partir da memória: no Windows, um arquivo aberto
    não pode ser substituído, e o leitor precisa gravar destaques no mesmo arquivo.
    """

    KEEP = 8

    def __init__(self, path, password: str | None = None):
        from collections import OrderedDict
        from pathlib import Path

        import pypdfium2 as pdfium

        self._data = Path(path).read_bytes()
        with core.PDFIUM_LOCK:
            self.pdf = pdfium.PdfDocument(self._data, password=password)
            self.count = len(self.pdf)
        self._pages = OrderedDict()

    def close(self):
        with core.PDFIUM_LOCK:
            for page, tp, *_ in self._pages.values():
                try:
                    tp.close()
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
            self._pages.clear()
            try:
                self.pdf.close()
            except Exception:  # noqa: BLE001
                pass

    def _entry(self, i: int):
        """(página, textpage, geom, caixas na tela, texto) da página i, guardando poucas abertas."""
        e = self._pages.get(i)
        if e is not None:
            self._pages.move_to_end(i)
            return e
        with core.PDFIUM_LOCK:
            page = self.pdf[i]
            tp = page.get_textpage()
            geom = PageGeom(page)
            n = tp.count_chars()
            boxes = []
            for k in range(n):
                try:
                    box = tp.get_charbox(k)
                except Exception:  # noqa: BLE001
                    box = (0, 0, 0, 0)
                l, b, r, t = box
                boxes.append(geom.rect_to_view(box) if r > l and t > b else None)
            text = tp.get_text_range(0, n) if n else ""
        e = (page, tp, geom, boxes, text)
        self._pages[i] = e
        while len(self._pages) > self.KEEP:
            _k, (p, t, *_r) = self._pages.popitem(last=False)
            with core.PDFIUM_LOCK:
                t.close()
                p.close()
        return e

    def char_count(self, i: int) -> int:
        return len(self._entry(i)[3])

    def has_text(self, i: int) -> bool:
        return any(b is not None for b in self._entry(i)[3])

    def geom(self, i: int) -> PageGeom:
        return self._entry(i)[2]

    def boundary_at(self, i: int, x: float, y: float) -> int | None:
        """Posição entre caracteres mais perto do ponto (x, y em pontos na tela). None sem texto."""
        boxes = self._entry(i)[3]
        best, best_d = None, 9e9
        for k, box in enumerate(boxes):
            if box is None:
                continue
            x0, y0, x1, y1 = box
            dy = 0.0 if y0 - 2 <= y <= y1 + 2 else min(abs(y - y0), abs(y - y1))
            dx = 0.0 if x0 <= x <= x1 else min(abs(x - x0), abs(x - x1))
            d = dy * 6 + dx      # a linha pesa mais que a distância na horizontal
            if d < best_d:
                best, best_d = k, d
        if best is None:
            return None
        x0, _y0, x1, _y1 = boxes[best]
        return best + 1 if x > (x0 + x1) / 2 else best

    def word_at(self, i: int, x: float, y: float) -> tuple[int, int] | None:
        b = self.boundary_at(i, x, y)
        text = self._entry(i)[4]
        if b is None or not text:
            return None
        k = min(max(0, b if b < len(text) and text[b:b + 1].isalnum() else b - 1), len(text) - 1)
        if not text[k].isalnum():
            return (k, k + 1)
        a = k
        while a > 0 and text[a - 1].isalnum():
            a -= 1
        z = k + 1
        while z < len(text) and text[z].isalnum():
            z += 1
        return (a, z)

    def view_rects(self, i: int, a: int, b: int) -> list[tuple[float, float, float, float]]:
        """Retângulos (na tela, em pontos) do trecho [a, b) da página i, um por linha."""
        _page, tp, geom, *_ = self._entry(i)
        return [geom.rect_to_view(r) for r in self.pdf_rects(i, a, b)] if b > a else []

    def pdf_rects(self, i: int, a: int, b: int) -> list[tuple[float, float, float, float]]:
        """Retângulos (no espaço do PDF) do trecho [a, b), para gravar o destaque."""
        if b <= a:
            return []
        _page, tp, *_ = self._entry(i)
        with core.PDFIUM_LOCK:
            n = tp.count_rects(a, b - a)
            return [tuple(tp.get_rect(k)) for k in range(n)]

    def text(self, i: int, a: int, b: int) -> str:
        if b <= a:
            return ""
        _page, tp, *_ = self._entry(i)
        with core.PDFIUM_LOCK:
            return tp.get_text_range(a, b - a) or ""

    def page_text(self, i: int) -> str:
        """Texto da página inteira; a posição de cada letra é o número do caractere no PDF."""
        return self._entry(i)[4]

    def chars_in(self, i: int, rects) -> list[int]:
        """Caracteres da página i cujo centro cai num dos retângulos (na tela, em pontos)."""
        boxes = self._entry(i)[3]
        out = []
        for k, box in enumerate(boxes):
            if box is None:
                continue
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            for x0, y0, x1, y1 in rects:
                if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
                    out.append(k)
                    break
        return out


def runs(indices) -> list[tuple[int, int]]:
    """Posições soltas → trechos contínuos [(início, fim)), fim exclusivo."""
    out: list[tuple[int, int]] = []
    for k in sorted(set(indices)):
        if out and out[-1][1] == k:
            out[-1] = (out[-1][0], k + 1)
        else:
            out.append((k, k + 1))
    return out


def clean_excerpt(text: str) -> str:
    """Trecho selecionado → texto corrido: junta as linhas, refaz palavras hifenizadas e mantém parágrafos."""
    return "\n\n".join(reflow(text.replace("\x02", "-")))


def has_text(path, sample_pages: int = 6) -> bool:
    """O PDF tem texto selecionável (nas primeiras páginas)?"""
    texts = page_texts(path)[:sample_pages] if sample_pages else page_texts(path)
    return any(t.strip() for t in texts)
