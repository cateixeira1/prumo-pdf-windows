"""
Destaques (marca-texto) gravados no próprio PDF, como anotações padrão de destaque (/Highlight).

Cada destaque leva as QuadPoints (os trechos marcados, linha a linha), a cor, o texto marcado
em /Contents e uma aparência pronta (/AP), desenhada com mistura "Multiply" para o texto continuar
legível. Assim ele aparece igual no Prumo, no Adobe, no Edge, no Chrome e no iPhone, e pode ser
apagado ou mudado de cor em qualquer um deles. Nada aqui depende da interface.

As coordenadas são as do PDF (espaço do usuário: origem embaixo à esquerda, sem o giro da página).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# chave: (rótulo, cor RGB de 0 a 1)
COLORS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "yellow": ("Amarelo", (1.0, 0.89, 0.25)),
    "green": ("Verde", (0.56, 0.87, 0.42)),
    "blue": ("Azul", (0.49, 0.76, 1.0)),
    "pink": ("Rosa", (1.0, 0.6, 0.8)),
    "orange": ("Laranja", (1.0, 0.7, 0.36)),
}
AUTHOR = "Prumo PDF"
PAD = 0.8   # folga em volta das linhas marcadas (pontos)


@dataclass
class Mark:
    """Um destaque já gravado no PDF."""
    page: int                                       # começa em 0
    ref: str                                        # /NM ou "obj:N:G" quando não há nome
    color: tuple[float, float, float]
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)   # (l, b, r, t)
    text: str = ""


def color_key(rgb) -> str:
    """A cor da paleta mais parecida (para mostrar destaques feitos em outros programas)."""
    best, dist = "yellow", 9e9
    for k, (_label, c) in COLORS.items():
        d = sum((a - b) ** 2 for a, b in zip(c, rgb))
        if d < dist:
            best, dist = k, d
    return best


def _pdf_date() -> str:
    t = time.localtime()
    off = -time.timezone if not t.tm_isdst else -time.altzone
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return time.strftime("D:%Y%m%d%H%M%S", t) + f"{sign}{off // 3600:02d}'{off % 3600 // 60:02d}'"


def _appearance(pdf, rects, rgb, bbox):
    import pikepdf

    r, g, b = rgb
    ops = [f"/GS0 gs {r:.3f} {g:.3f} {b:.3f} rg"]
    for l, bo, ri, t in rects:
        ops.append(f"{l - PAD:.2f} {bo - PAD:.2f} {ri - l + 2 * PAD:.2f} {t - bo + 2 * PAD:.2f} re f")
    stream = pikepdf.Stream(pdf, "\n".join(ops).encode("latin-1"))
    stream["/Type"] = pikepdf.Name.XObject
    stream["/Subtype"] = pikepdf.Name.Form
    stream["/BBox"] = pikepdf.Array([float(v) for v in bbox])
    stream["/Resources"] = pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(
        GS0=pikepdf.Dictionary(Type=pikepdf.Name.ExtGState, BM=pikepdf.Name.Multiply, ca=1, CA=1)))
    return pdf.make_indirect(stream)


def _bbox(rects):
    return (min(r[0] for r in rects) - PAD, min(r[1] for r in rects) - PAD,
            max(r[2] for r in rects) + PAD, max(r[3] for r in rects) + PAD)


def add_highlight(pdf, page_index: int, rects, color: str, text: str = "") -> str:
    """Acrescenta um destaque à página (num pikepdf.Pdf aberto). Devolve o nome (/NM) dele."""
    import pikepdf

    rects = [tuple(float(v) for v in r) for r in rects if r[2] > r[0] and r[3] > r[1]]
    if not rects:
        raise ValueError("Nada para destacar.")
    rgb = COLORS.get(color, COLORS["yellow"])[1]
    name = f"prumo-hl-{uuid.uuid4().hex[:16]}"
    quads = []
    for l, b, r, t in rects:
        quads += [l, t, r, t, l, b, r, b]   # alto à esquerda, alto à direita, baixo à esquerda, baixo à direita
    bbox = _bbox(rects)
    page = pdf.pages[page_index]
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Highlight,
        Rect=pikepdf.Array([float(v) for v in bbox]),
        QuadPoints=pikepdf.Array([float(v) for v in quads]),
        C=pikepdf.Array([float(v) for v in rgb]), CA=1, F=4,
        NM=pikepdf.String(name), T=pikepdf.String(AUTHOR), M=pikepdf.String(_pdf_date()),
        Contents=pikepdf.String(text[:2000]), P=page.obj,
    )
    annot["/AP"] = pikepdf.Dictionary(N=_appearance(pdf, rects, rgb, bbox))
    ref = pdf.make_indirect(annot)
    if "/Annots" not in page.obj:
        page.obj["/Annots"] = pikepdf.Array()
    page.obj["/Annots"].append(ref)
    return name


def _ref_of(annot) -> str:
    nm = annot.get("/NM")
    if nm is not None:
        return str(nm)
    try:
        num, gen = annot.objgen
        return f"obj:{num}:{gen}"
    except Exception:  # noqa: BLE001
        return ""


def _rects_of(annot) -> list[tuple[float, float, float, float]]:
    q = [float(v) for v in annot.get("/QuadPoints", [])]
    out = []
    for k in range(0, len(q) - 7, 8):
        xs, ys = q[k:k + 8:2], q[k + 1:k + 8:2]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    if not out and "/Rect" in annot:
        r = [float(v) for v in annot["/Rect"]]
        out.append((min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])))
    return out


def marks(pdf) -> dict[int, list[Mark]]:
    """Todos os destaques do PDF (feitos no Prumo ou em outro programa), por página."""
    out: dict[int, list[Mark]] = {}
    for i, page in enumerate(pdf.pages):
        for annot in page.obj.get("/Annots", []) or []:
            try:
                if annot.get("/Subtype") != "/Highlight":
                    continue
                c = [float(v) for v in annot.get("/C", [])]
                rgb = (c[0], c[1], c[2]) if len(c) >= 3 else ((c[0],) * 3 if c else (1.0, 0.9, 0.2))
                out.setdefault(i, []).append(Mark(i, _ref_of(annot), rgb, _rects_of(annot),
                                                  str(annot.get("/Contents", ""))))
            except Exception:  # noqa: BLE001 - anotação estranha: ignora
                continue
    return out


def read_marks(path, password: str | None = None) -> dict[int, list[Mark]]:
    import pikepdf

    try:
        with pikepdf.open(str(path), password=password or "") as pdf:
            return marks(pdf)
    except Exception:  # noqa: BLE001
        return {}


def _find(pdf, page_index: int, ref: str):
    page = pdf.pages[page_index]
    annots = page.obj.get("/Annots", []) or []
    for k, annot in enumerate(annots):
        if _ref_of(annot) == ref:
            return page, k, annot
    return page, None, None


def remove_highlight(pdf, page_index: int, ref: str) -> bool:
    page, k, _annot = _find(pdf, page_index, ref)
    if k is None:
        return False
    del page.obj["/Annots"][k]
    return True


def recolor_highlight(pdf, page_index: int, ref: str, color: str) -> bool:
    import pikepdf

    _page, _k, annot = _find(pdf, page_index, ref)
    if annot is None:
        return False
    rgb = COLORS.get(color, COLORS["yellow"])[1]
    rects = _rects_of(annot)
    annot["/C"] = pikepdf.Array([float(v) for v in rgb])
    annot["/M"] = pikepdf.String(_pdf_date())
    if rects:
        annot["/AP"] = pikepdf.Dictionary(N=_appearance(pdf, rects, rgb, [float(v) for v in annot["/Rect"]]))
    return True


# --- Operações sobre o arquivo (para Library.modify) ----------------------------------

def _edit(path, fn):
    import pdfops

    pdf = pdfops._open(path)
    try:
        result = fn(pdf)
        pdfops._save_inplace(pdf, path)
        return result
    finally:
        try:
            pdf.close()
        except Exception:  # noqa: BLE001
            pass


def add_to_file(path: str | Path, items) -> list[tuple[int, str]]:
    """`items`: lista de (página, retângulos, cor, texto). Devolve [(página, nome)] dos destaques criados."""
    return _edit(path, lambda pdf: [(p, add_highlight(pdf, p, rects, color, text)) for p, rects, color, text in items])


def remove_from_file(path: str | Path, refs) -> int:
    """`refs`: lista de (página, nome). Devolve quantos foram apagados."""
    return _edit(path, lambda pdf: sum(1 for p, ref in refs if remove_highlight(pdf, p, ref)))


def recolor_in_file(path: str | Path, page_index: int, ref: str, color: str) -> bool:
    return _edit(path, lambda pdf: recolor_highlight(pdf, page_index, ref, color))
