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


def reflow(text: str) -> list[str]:
    """Linhas de uma página → parágrafos."""
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in re.split(r"\r\n|\r|\n", text)]
    if not any(lines):
        return []
    longest = max((len(l) for l in lines if l), default=0)
    paras: list[str] = []
    cur = ""
    prev = ""
    for line in lines:
        if not line:
            if cur:
                paras.append(cur)
                cur = ""
            prev = ""
            continue
        both_titles = _is_title(prev) and _is_title(line) and not SENTENCE_END.search(prev)
        new_para = (not cur or BULLET.match(line) is not None
                    or (not both_titles and (_is_title(prev) or _is_title(line)))
                    or (SENTENCE_END.search(prev) is not None and len(prev) < 0.75 * longest)
                    or len(prev) < 0.5 * longest)   # só a última linha de um parágrafo é curta
        if new_para:
            if cur:
                paras.append(cur)
            cur = line
        else:
            if re.search(r"[A-Za-zÀ-ÿ]-$", cur) and line[:1].islower():
                cur = cur[:-1] + line          # palavra hifenizada no fim da linha
            else:
                cur = f"{cur} {line}"
        prev = line
    if cur:
        paras.append(cur)
    return paras


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
        height = page.get_height()
        hits = []
        for a, b in find_all(text, query):
            n = tp.count_rects(a, b - a)
            rects = []
            for k in range(n):
                left, bottom, right, top = tp.get_rect(k)
                rects.append((left, height - top, right, height - bottom))
            if rects:
                hits.append(Hit(index, rects))
        return hits
    finally:
        tp.close()
        page.close()


def has_text(path, sample_pages: int = 6) -> bool:
    """O PDF tem texto selecionável (nas primeiras páginas)?"""
    texts = page_texts(path)[:sample_pages] if sample_pages else page_texts(path)
    return any(t.strip() for t in texts)
