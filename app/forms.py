"""
Preencher formulários em PDF, gravando tudo no próprio arquivo (abre igual em qualquer leitor).

Dois tipos de formulário:

- PDF com campos (AcroForm): texto, caixa de marcar, botões de opção, lista e lista suspensa. O valor vai
  para o campo (/V) e o Prumo desenha a aparência (/AP) de cada campo: assim o valor aparece no Acrobat, no
  Edge, no Chrome e no iPhone, sem depender de o leitor redesenhar. A letra da aparência é uma das 14 fontes
  padrão do PDF (Helvetica, Times ou Courier, conforme a fonte do campo), que todo leitor tem.
- PDF sem campos (papel escaneado, impresso): caixas de texto e marcas (✓, ✗) colocadas em qualquer lugar
  da página. Cada uma é uma anotação de texto padrão (/FreeText), com aparência pronta. Continua editável no
  Prumo (e no Acrobat). As caixas feitas pelo Prumo têm o nome (/NM) começando por "prumo-tx-" ou "prumo-mk-".

"Finalizar" cria uma cópia achatada: campos e caixas viram parte do desenho da página e não podem mais ser
alterados. Os destaques continuam anotações.

Limite: as 14 fontes padrão só têm as letras do Windows-1252 (português, inglês, espanhol, francês, alemão
e as línguas nórdicas). Letra fora disso (japonês, chinês, emoji) não pode ser gravada; `unsupported()`
diz quais são, para a interface avisar antes.

Coordenadas: a interface trabalha na página como ela aparece (pontos, origem no alto à esquerda, já com o
giro da página). `PageGeo` converte para o espaço do PDF (origem embaixo à esquerda, sem o giro).
"""

from __future__ import annotations

import copy
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

PREFIX_TEXT = "prumo-tx-"
PREFIX_MARK = "prumo-mk-"
AUTHOR = "Prumo PDF"

FONTS = {   # chave → (nome da fonte padrão, nome em negrito, fonte parecida no Windows para a tela)
    "helvetica": ("Helvetica", "Helvetica-Bold", "Arial"),
    "times": ("Times-Roman", "Times-Bold", "Times New Roman"),
    "courier": ("Courier", "Courier-Bold", "Courier New"),
}
COLORS = {   # chave → RGB de 0 a 1
    "black": (0.0, 0.0, 0.0),
    "blue": (0.05, 0.20, 0.62),
    "red": (0.78, 0.07, 0.07),
    "green": (0.05, 0.45, 0.16),
}
MARKS = {"check": "✓", "cross": "✗", "dot": "●"}
BOX_PAD = 2.0          # folga da caixa de texto em volta das letras (pontos)
LINE = 1.2             # altura da linha = tamanho × LINE
ASCENT = 0.93          # do alto da linha até a base das letras, em relação ao tamanho
FIELD_PAD = 2.0        # margem interna dos campos


class FormError(Exception):
    """Erro com mensagem pronta (em português; a interface traduz)."""


# --- Medidas das fontes padrão ------------------------------------------------

def _widths(key: str, bold: bool) -> dict:
    from fpdf.fonts import CORE_FONTS_CHARWIDTHS
    return CORE_FONTS_CHARWIDTHS[key + ("B" if bold else "")]


def encodable(ch: str) -> bool:
    if ch in "\n\r\t":
        return True
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def unsupported(text: str) -> str:
    """As letras de `text` que as fontes padrão do PDF não têm (sem repetir)."""
    out = []
    for ch in text:
        if not encodable(ch) and ch not in out:
            out.append(ch)
    return "".join(out)


def clean(text: str) -> str:
    """Tira o que não pode ser gravado (a interface já avisou)."""
    return "".join(ch for ch in text.replace("\r\n", "\n").replace("\r", "\n") if encodable(ch)).replace("\t", " ")


def text_width(text: str, font: str = "helvetica", bold: bool = False, size: float = 12) -> float:
    w = _widths(font, bold)
    total = 0
    for b in clean(text).encode("cp1252"):
        total += w.get(chr(b), 556)
    return total * size / 1000.0


def box_size(text: str, font: str, bold: bool, size: float) -> tuple[float, float]:
    """Largura e altura (pontos) de uma caixa de texto livre: cada linha como foi digitada, sem quebra."""
    lines = clean(text).split("\n") or [""]
    w = max((text_width(line, font, bold, size) for line in lines), default=0.0)
    w = max(w, size * 0.6)
    return w + 2 * BOX_PAD, len(lines) * size * LINE + 2 * BOX_PAD


def _pdf_string(text: str) -> bytes:
    """Texto como literal de PDF, codificado em WinAnsi (Windows-1252)."""
    data = clean(text).encode("cp1252")
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _num(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _pdf_date() -> str:
    t = time.localtime()
    off = -time.timezone if not t.tm_isdst else -time.altzone
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return time.strftime("D:%Y%m%d%H%M%S", t) + f"{sign}{off // 3600:02d}'{off % 3600 // 60:02d}'"


# --- Geometria da página -------------------------------------------------------

@dataclass
class PageGeo:
    box: tuple[float, float, float, float]    # CropBox (l, b, r, t)
    rotate: int = 0                            # 0, 90, 180 ou 270 (horário, como /Rotate)

    @property
    def raw_size(self) -> tuple[float, float]:
        return self.box[2] - self.box[0], self.box[3] - self.box[1]

    @property
    def size(self) -> tuple[float, float]:
        """Largura e altura da página como aparece."""
        w, h = self.raw_size
        return (h, w) if self.rotate in (90, 270) else (w, h)

    def to_display(self, x: float, y: float) -> tuple[float, float]:
        w, h = self.raw_size
        u0, v0 = x - self.box[0], self.box[3] - y
        r = self.rotate
        if r == 90:
            return h - v0, u0
        if r == 180:
            return w - u0, h - v0
        if r == 270:
            return v0, w - u0
        return u0, v0

    def to_pdf(self, u: float, v: float) -> tuple[float, float]:
        w, h = self.raw_size
        r = self.rotate
        if r == 90:
            u0, v0 = v, h - u
        elif r == 180:
            u0, v0 = w - u, h - v
        elif r == 270:
            u0, v0 = w - v, u
        else:
            u0, v0 = u, v
        return u0 + self.box[0], self.box[3] - v0

    def rect_to_display(self, rect) -> tuple[float, float, float, float]:
        """(l, b, r, t) do PDF → (x0, y0, x1, y1) na página como aparece."""
        l, b, r, t = rect
        pts = [self.to_display(l, b), self.to_display(r, t), self.to_display(l, t), self.to_display(r, b)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def rect_to_pdf(self, x0, y0, x1, y1) -> tuple[float, float, float, float]:
        pts = [self.to_pdf(x0, y0), self.to_pdf(x1, y1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _rot_matrix(rot: int):
    """Matriz que deixa o desenho em pé para quem vê a página girada `rot` graus."""
    return {0: [1, 0, 0, 1, 0, 0], 90: [0, 1, -1, 0, 0, 0], 180: [-1, 0, 0, -1, 0, 0],
            270: [0, -1, 1, 0, 0, 0]}[rot % 360]


def page_geo(page) -> PageGeo:
    box = page.obj.get("/CropBox") or page.obj.get("/MediaBox")
    if box is None:
        box = page.mediabox
    b = [float(v) for v in box]
    rot = int(page.obj.get("/Rotate", 0) or 0) % 360
    if rot % 90:
        rot = 0
    return PageGeo((min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])), rot)


# --- Modelo ----------------------------------------------------------------------

@dataclass
class Widget:
    page: int
    rect: tuple[float, float, float, float]      # no espaço do PDF
    on_state: str | None = None                  # caixa de marcar / opção: nome do estado "ligado"
    key: tuple[int, int] = (0, 0)                # objgen do widget


@dataclass
class Field:
    name: str
    kind: str                                    # text, check, radio, combo, list
    value: object = ""                           # texto, True/False (check) ou estado (radio)
    options: list[tuple[str, str]] = field(default_factory=list)   # (valor gravado, texto mostrado)
    widgets: list[Widget] = field(default_factory=list)
    readonly: bool = False
    multiline: bool = False
    password: bool = False
    comb: bool = False
    editable: bool = False                      # lista suspensa que aceita texto digitado
    maxlen: int = 0
    font: str = "helvetica"
    bold: bool = False
    size: float = 0.0                            # 0 = automático
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    align: int = 0                               # 0 esquerda, 1 centro, 2 direita
    tooltip: str = ""


@dataclass
class Box:
    """Caixa de texto livre ou marca (✓ ✗ ●), na página como aparece (pontos, origem no alto à esquerda)."""
    page: int
    x: float
    y: float
    kind: str = "text"                           # text, check, cross, dot
    text: str = ""
    font: str = "helvetica"
    bold: bool = False
    size: float = 12.0
    color: str = "black"
    id: str = ""

    def size_pt(self) -> tuple[float, float]:
        if self.kind == "text":
            return box_size(self.text, self.font, self.bold, self.size)
        return self.size, self.size


@dataclass
class FormData:
    fields: list[Field]
    boxes: list[Box]
    pages: list[PageGeo]
    xfa: bool = False                            # formulário XFA (Adobe LiveCycle)
    xfa_only: bool = False                       # só XFA, sem campos AcroForm: o Prumo não consegue preencher

    def values(self) -> dict:
        return {f.name: f.value for f in self.fields}

    def snapshot(self):
        return self.values(), copy.deepcopy(self.boxes)


# --- Leitura -----------------------------------------------------------------------

def _inherited(d, key, default=None):
    seen = 0
    while d is not None and seen < 50:
        if key in d:
            return d[key]
        d = d.get("/Parent")
        seen += 1
    return default


def _text(v) -> str:
    if v is None:
        return ""
    try:
        import pikepdf
        if isinstance(v, pikepdf.Array):
            return _text(v[0]) if len(v) else ""
        if isinstance(v, pikepdf.Name):
            return str(v)[1:]
    except Exception:  # noqa: BLE001
        pass
    return str(v)


def _parse_da(da: str):
    """Fonte, tamanho e cor do /DA ("/Helv 10 Tf 0 g")."""
    fname, size, color = "", 0.0, (0.0, 0.0, 0.0)
    m = re.search(r"/([^\s/]+)\s+([\d.]+)\s+Tf", da or "")
    if m:
        fname = m.group(1)
        try:
            size = float(m.group(2))
        except ValueError:
            size = 0.0
    m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da or "")
    if m:
        color = tuple(min(1.0, float(v)) for v in m.groups())
    else:
        m = re.search(r"([\d.]+)\s+g(?:\s|$)", da or "")
        if m:
            color = (min(1.0, float(m.group(1))),) * 3
        else:
            m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+k", da or "")
            if m:
                c, mg, y, k = (float(v) for v in m.groups())
                color = ((1 - c) * (1 - k), (1 - mg) * (1 - k), (1 - y) * (1 - k))
    return fname, size, color


def _font_family(pdf, acro, widget, fname: str) -> tuple[str, bool]:
    """Qual fonte padrão usar na aparência, conforme a fonte do campo."""
    base = fname
    try:
        dr = widget.get("/DR") or (acro.get("/DR") if acro is not None else None)
        fd = dr.get("/Font", {}).get("/" + fname) if dr is not None and fname else None
        if fd is not None:
            base = str(fd.get("/BaseFont", fname))
    except Exception:  # noqa: BLE001
        pass
    low = base.lower()
    bold = "bold" in low or low.endswith("bo") or "black" in low
    if "cour" in low or "mono" in low:
        return "courier", bold
    if "times" in low or "tiro" in low or "roman" in low or ("serif" in low and "sans" not in low):
        return "times", bold
    return "helvetica", bold


def _page_index(pdf) -> dict:
    out = {}
    for i, page in enumerate(pdf.pages):
        for a in page.obj.get("/Annots", []) or []:
            try:
                out[a.objgen] = i
            except Exception:  # noqa: BLE001
                continue
    return out


def _widget_states(w) -> list[str]:
    try:
        n = w.get("/AP", {}).get("/N")
        if n is not None and hasattr(n, "keys"):
            return [str(k)[1:] for k in n.keys() if str(k) != "/Off"]
    except Exception:  # noqa: BLE001
        pass
    return []


def _terminal_fields(acro):
    """(campo, nome completo, widgets) de todos os campos terminais."""
    out = []

    def walk(node, prefix, depth):
        if depth > 40:
            return
        t = node.get("/T")
        name = prefix + ("." if prefix and t is not None else "") + (str(t) if t is not None else "")
        kids = node.get("/Kids")
        if kids is not None and len(kids) and any("/T" in k for k in kids):
            for k in kids:
                if "/T" in k:
                    walk(k, name, depth + 1)
                elif k.get("/Subtype") == "/Widget":   # mistura rara: widget solto entre filhos
                    out.append((node, name, [k]))
            return
        widgets = list(kids) if kids is not None and len(kids) else ([node] if node.get("/Subtype") == "/Widget" or "/Rect" in node else [])
        out.append((node, name, widgets))

    for f in acro.get("/Fields", []) or []:
        try:
            walk(f, "", 0)
        except Exception:  # noqa: BLE001
            continue
    return out


def _fields(pdf) -> tuple[list[Field], bool, bool]:
    acro = pdf.Root.get("/AcroForm")
    if acro is None:
        return [], False, False
    xfa = "/XFA" in acro
    pages = _page_index(pdf)
    fields = []
    names = set()
    for node, name, widgets in _terminal_fields(acro):
        ft = str(_inherited(node, "/FT", "") or "")
        ff = int(_inherited(node, "/Ff", 0) or 0)
        if ft not in ("/Tx", "/Btn", "/Ch"):
            continue                                   # assinatura e outros: não se preenchem aqui
        if ft == "/Btn" and ff & (1 << 16):
            continue                                   # botão de apertar
        if ft == "/Tx" and ff & (1 << 20):
            continue                                   # seleção de arquivo
        kind = "text"
        if ft == "/Btn":
            kind = "radio" if ff & (1 << 15) else "check"
        elif ft == "/Ch":
            kind = "combo" if ff & (1 << 17) else "list"
        da = str(_inherited(node, "/DA", "") or acro.get("/DA", "") or "")
        fname, size, color = _parse_da(da)
        fam, bold = _font_family(pdf, acro, widgets[0] if widgets else node, fname)
        f = Field(name=name or f"campo{len(fields) + 1}", kind=kind, readonly=bool(ff & 1),
                  multiline=bool(ff & (1 << 12)) and kind == "text", password=bool(ff & (1 << 13)),
                  comb=bool(ff & (1 << 24)), editable=bool(ff & (1 << 18)),
                  maxlen=int(_inherited(node, "/MaxLen", 0) or 0), font=fam, bold=bold, size=size, color=color,
                  align=int(_inherited(node, "/Q", 0) or 0), tooltip=str(node.get("/TU", "") or ""))
        if f.name in names:
            continue
        names.add(f.name)
        v = _inherited(node, "/V")
        for w in widgets:
            try:
                r = [float(x) for x in w["/Rect"]]
            except Exception:  # noqa: BLE001
                continue
            page = pages.get(w.objgen)
            if page is None:
                try:
                    p = w.get("/P")
                    page = next((i for i, pg in enumerate(pdf.pages) if pg.obj.objgen == p.objgen), None)
                except Exception:  # noqa: BLE001
                    page = None
            if page is None:
                continue
            flags = int(w.get("/F", 0) or 0)
            if flags & 2:                                # escondido
                continue
            states = _widget_states(w) if kind in ("check", "radio") else []
            f.widgets.append(Widget(page, (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])),
                                    states[0] if states else None, w.objgen))
        if not f.widgets:
            continue
        if kind == "check":
            on = {wd.on_state for wd in f.widgets if wd.on_state}
            vs = _text(v)
            f.value = bool(vs) and vs != "Off" and (not on or vs in on)
        elif kind == "radio":
            vs = _text(v)
            f.value = vs if vs and vs != "Off" else ""
            f.options = [(wd.on_state, wd.on_state) for wd in f.widgets if wd.on_state]
        elif kind in ("combo", "list"):
            for o in _inherited(node, "/Opt", []) or []:
                try:
                    import pikepdf
                    if isinstance(o, pikepdf.Array) and len(o) >= 2:
                        f.options.append((str(o[0]), str(o[1])))
                    else:
                        f.options.append((str(o), str(o)))
                except Exception:  # noqa: BLE001
                    continue
            f.value = _text(v)
        else:
            f.value = _text(v)
        fields.append(f)
    return fields, xfa, xfa and not fields


def _boxes(pdf, geos) -> list[Box]:
    out = []
    for i, page in enumerate(pdf.pages):
        for a in page.obj.get("/Annots", []) or []:
            try:
                if a.get("/Subtype") != "/FreeText":
                    continue
                nm = str(a.get("/NM", ""))
                if not nm.startswith((PREFIX_TEXT, PREFIX_MARK)):
                    continue
                style = _parse_style(str(a.get("/PrumoStyle", "") or a.get("/DS", "")))
                r = [float(v) for v in a["/Rect"]]
                x0, y0, _x1, _y1 = geos[i].rect_to_display((min(r[0], r[2]), min(r[1], r[3]),
                                                             max(r[0], r[2]), max(r[1], r[3])))
                kind = style.get("kind", "text") if nm.startswith(PREFIX_MARK) else "text"
                out.append(Box(page=i, x=x0, y=y0, kind=kind, text=str(a.get("/Contents", "")) if kind == "text" else "",
                               font=style.get("font", "helvetica"), bold=style.get("bold", False),
                               size=style.get("size", 12.0), color=style.get("color", "black"), id=nm))
            except Exception:  # noqa: BLE001
                continue
    return out


def _parse_style(s: str) -> dict:
    out: dict = {}
    for part in s.split(";"):
        if ":" not in part:
            continue
        k, v = (x.strip() for x in part.split(":", 1))
        if k == "prumo-kind" and v in MARKS:
            out["kind"] = v
        elif k == "font-family":
            low = v.lower()
            out["font"] = "courier" if "cour" in low else ("times" if "times" in low else "helvetica")
        elif k == "font-weight":
            out["bold"] = v.lower() == "bold"
        elif k == "font-size" or k == "font":
            m = re.search(r"([\d.]+)pt", v)
            if m:
                out["size"] = max(4.0, min(144.0, float(m.group(1))))
        elif k == "color":
            v = v.lower()
            for key, rgb in COLORS.items():
                if v == _hex(rgb):
                    out["color"] = key
    return out


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def read(pdf) -> FormData:
    geos = [page_geo(p) for p in pdf.pages]
    fields, xfa, xfa_only = _fields(pdf)
    return FormData(fields, _boxes(pdf, geos), geos, xfa, xfa_only)


def load(path, password: str | None = None) -> FormData:
    import pikepdf
    try:
        with pikepdf.open(str(path), password=password or "") as pdf:
            return read(pdf)
    except pikepdf.PasswordError:
        raise FormError("O PDF está protegido por senha.") from None


# --- Aparências ----------------------------------------------------------------------

def _font_dict(pdf, family: str, bold: bool):
    import pikepdf
    base = FONTS[family][1 if bold else 0]
    return pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name("/" + base),
                                                Encoding=pikepdf.Name.WinAnsiEncoding))


def _form_xobject(pdf, content: bytes, bbox, fonts: dict | None = None, matrix=None):
    import pikepdf
    s = pikepdf.Stream(pdf, content)
    s["/Type"] = pikepdf.Name.XObject
    s["/Subtype"] = pikepdf.Name.Form
    s["/BBox"] = pikepdf.Array([float(v) for v in bbox])
    if matrix is not None and list(matrix) != [1, 0, 0, 1, 0, 0]:
        s["/Matrix"] = pikepdf.Array([float(v) for v in matrix])
    res = pikepdf.Dictionary()
    if fonts:
        res["/Font"] = pikepdf.Dictionary({"/" + k: v for k, v in fonts.items()})
    s["/Resources"] = res
    return pdf.make_indirect(s)


def _wrap(text: str, width: float, family: str, bold: bool, size: float) -> list[str]:
    lines = []
    for para in clean(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if text_width(trial, family, bold, size) <= width or not cur:
                cur = trial
                while text_width(cur, family, bold, size) > width and len(cur) > 1:   # palavra maior que a linha
                    k = len(cur)
                    while k > 1 and text_width(cur[:k], family, bold, size) > width:
                        k -= 1
                    lines.append(cur[:k])
                    cur = cur[k:]
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _auto_size(f: Field, text: str, w: float, h: float) -> float:
    if f.size > 0:
        return f.size
    inner_w, inner_h = max(1.0, w - 2 * FIELD_PAD), max(1.0, h - 2 * FIELD_PAD)
    if f.multiline:
        for s in (12, 11, 10, 9, 8, 7, 6, 5, 4):
            if len(_wrap(text, inner_w, f.font, f.bold, s)) * s * LINE <= inner_h:
                return float(s)
        return 4.0
    s = min(12.0, inner_h / 1.15)
    if text and not f.comb:
        tw = text_width(text, f.font, f.bold, 1.0)
        if tw > 0:
            s = min(s, inner_w / tw)
    return max(4.0, s)


def _mk(widget):
    mk = widget.get("/MK") or {}
    def rgb(arr):
        try:
            vals = [float(v) for v in arr]
        except Exception:  # noqa: BLE001
            return None
        if len(vals) == 1:
            return (vals[0],) * 3
        if len(vals) == 3:
            return tuple(vals)
        if len(vals) == 4:
            c, m, y, k = vals
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
        return None
    bg = rgb(mk.get("/BG", [])) if "/BG" in mk else None
    bc = rgb(mk.get("/BC", [])) if "/BC" in mk else None
    rot = int(mk.get("/R", 0) or 0) % 360
    bs = widget.get("/BS") or {}
    bw = float(bs.get("/W", 1) if bs else 1)
    style = str(bs.get("/S", "/S")) if bs else "/S"
    return bg, bc, (rot if rot in (0, 90, 180, 270) else 0), bw, style


def _frame_ops(w: float, h: float, bg, bc, bw: float, style: str) -> list[str]:
    ops = []
    if bg is not None:
        ops.append(f"{_num(bg[0])} {_num(bg[1])} {_num(bg[2])} rg 0 0 {_num(w)} {_num(h)} re f")
    if bc is not None and bw > 0:
        ops.append(f"{_num(bc[0])} {_num(bc[1])} {_num(bc[2])} RG {_num(bw)} w")
        if style == "/U":
            ops.append(f"0 {_num(bw / 2)} m {_num(w)} {_num(bw / 2)} l S")
        else:
            if style == "/D":
                ops.append("[3] 0 d")
            ops.append(f"{_num(bw / 2)} {_num(bw / 2)} {_num(w - bw)} {_num(h - bw)} re S")
            if style == "/D":
                ops.append("[] 0 d")
    return ops


def _text_appearance(pdf, f: Field, widget, text: str):
    l, b, r, t = (float(v) for v in widget["/Rect"])
    W, H = abs(r - l), abs(t - b)
    bg, bc, rot, bw, style = _mk(widget)
    w, h = (H, W) if rot in (90, 270) else (W, H)
    shown = "*" * len(text) if f.password else clean(text)
    size = _auto_size(f, shown, w, h)
    pad = FIELD_PAD + (bw if bc is not None else 0)
    rgb = f.color
    ops = _frame_ops(w, h, bg, bc, bw, style)
    ops.append("/Tx BMC q")
    ops.append(f"{_num(pad / 2)} {_num(pad / 2)} {_num(w - pad)} {_num(h - pad)} re W n")
    ops.append(f"BT /F1 {_num(size)} Tf {_num(rgb[0])} {_num(rgb[1])} {_num(rgb[2])} rg")
    body = []
    if f.comb and f.maxlen > 0:
        cell = w / f.maxlen
        y = (h - size * 0.72) / 2
        for k, ch in enumerate(shown[:f.maxlen]):
            cw = text_width(ch, f.font, f.bold, size)
            body.append((k * cell + (cell - cw) / 2, y, ch))
    elif f.multiline:
        inner = w - 2 * pad
        y = h - pad - size * ASCENT * 0.95
        for line in _wrap(shown, inner, f.font, f.bold, size):
            lw = text_width(line, f.font, f.bold, size)
            x = pad + (inner - lw) / 2 if f.align == 1 else (w - pad - lw if f.align == 2 else pad)
            body.append((x, y, line))
            y -= size * LINE
    else:
        line = shown.replace("\n", " ")
        lw = text_width(line, f.font, f.bold, size)
        inner = w - 2 * pad
        x = pad + (inner - lw) / 2 if f.align == 1 else (w - pad - lw if f.align == 2 else pad)
        y = (h - size * 0.72) / 2       # altura das maiúsculas da Helvetica ≈ 0,72 do tamanho
        body.append((x, y, line))
    content = "\n".join(ops).encode("latin-1") + b"\n"
    lastx = lasty = 0.0
    for x, y, line in body:
        content += f"{_num(x - lastx)} {_num(y - lasty)} Td ".encode("latin-1") + _pdf_string(line) + b" Tj\n"
        lastx, lasty = x, y
    content += b"ET Q EMC\n"
    return _form_xobject(pdf, content, [0, 0, w, h], {"F1": _font_dict(pdf, f.font, f.bold)}, _rot_matrix(rot))


def _choice_appearance(pdf, f: Field, widget, value: str):
    if f.kind == "combo":
        shown = next((disp for exp, disp in f.options if exp == value), value)
        return _text_appearance(pdf, f, widget, shown)
    # lista: todas as opções, com a escolhida em destaque (como os leitores desenham)
    l, b, r, t = (float(v) for v in widget["/Rect"])
    W, H = abs(r - l), abs(t - b)
    bg, bc, rot, bw, style = _mk(widget)
    w, h = (H, W) if rot in (90, 270) else (W, H)
    size = f.size if f.size > 0 else 10.0
    pad = FIELD_PAD + (bw if bc is not None else 0)
    ops = _frame_ops(w, h, bg, bc, bw, style)
    ops.append("/Tx BMC q")
    ops.append(f"{_num(pad / 2)} {_num(pad / 2)} {_num(w - pad)} {_num(h - pad)} re W n")
    content = "\n".join(ops).encode("latin-1") + b"\n"
    y = h - pad
    for exp, disp in f.options:
        y -= size * LINE
        if y < -size:
            break
        color = f.color
        if exp == value:
            content += f"0.6 0.75 0.95 rg {_num(pad / 2)} {_num(y - size * 0.25)} {_num(w - pad)} {_num(size * LINE)} re f\n".encode()
        content += f"BT /F1 {_num(size)} Tf {_num(color[0])} {_num(color[1])} {_num(color[2])} rg {_num(pad)} {_num(y)} Td ".encode()
        content += _pdf_string(disp) + b" Tj ET\n"
    content += b"Q EMC\n"
    return _form_xobject(pdf, content, [0, 0, w, h], {"F1": _font_dict(pdf, f.font, f.bold)}, _rot_matrix(rot))


def _mark_ops(kind: str, s: float, rgb) -> str:
    r, g, b = (_num(v) for v in rgb)
    lw = _num(max(0.8, s * 0.12))
    if kind == "check":
        return (f"{r} {g} {b} RG {lw} w 1 J 1 j {_num(s * 0.15)} {_num(s * 0.52)} m {_num(s * 0.40)} {_num(s * 0.22)} l "
                f"{_num(s * 0.86)} {_num(s * 0.82)} l S")
    if kind == "cross":
        return (f"{r} {g} {b} RG {lw} w 1 J {_num(s * 0.2)} {_num(s * 0.2)} m {_num(s * 0.8)} {_num(s * 0.8)} l S "
                f"{_num(s * 0.2)} {_num(s * 0.8)} m {_num(s * 0.8)} {_num(s * 0.2)} l S")
    k = 0.5523
    c, rr = s / 2, s * 0.28
    return (f"{r} {g} {b} rg {_num(c + rr)} {_num(c)} m "
            f"{_num(c + rr)} {_num(c + rr * k)} {_num(c + rr * k)} {_num(c + rr)} {_num(c)} {_num(c + rr)} c "
            f"{_num(c - rr * k)} {_num(c + rr)} {_num(c - rr)} {_num(c + rr * k)} {_num(c - rr)} {_num(c)} c "
            f"{_num(c - rr)} {_num(c - rr * k)} {_num(c - rr * k)} {_num(c - rr)} {_num(c)} {_num(c - rr)} c "
            f"{_num(c + rr * k)} {_num(c - rr)} {_num(c + rr)} {_num(c - rr * k)} {_num(c + rr)} {_num(c)} c f")


def _box_annotation(pdf, page_index: int, geo: PageGeo, box: Box):
    import pikepdf
    w, h = box.size_pt()
    rect = geo.rect_to_pdf(box.x, box.y, box.x + w, box.y + h)
    rgb = COLORS.get(box.color, COLORS["black"])
    rot = geo.rotate
    if box.kind == "text":
        content = [f"BT /F1 {_num(box.size)} Tf {_num(rgb[0])} {_num(rgb[1])} {_num(rgb[2])} rg"]
        data = "\n".join(content).encode("latin-1") + b"\n"
        lasty = 0.0
        first = True
        y = h - BOX_PAD - box.size * ASCENT
        for line in clean(box.text).split("\n"):
            dy = y if first else y - lasty
            data += f"{_num(BOX_PAD) if first else 0} {_num(dy)} Td ".encode("latin-1") + _pdf_string(line) + b" Tj\n"
            lasty = y
            first = False
            y -= box.size * LINE
        data += b"ET\n"
        ap = _form_xobject(pdf, data, [0, 0, w, h], {"F1": _font_dict(pdf, box.font, box.bold)}, _rot_matrix(rot))
        nm = box.id if box.id.startswith(PREFIX_TEXT) else PREFIX_TEXT + uuid.uuid4().hex[:16]
        contents = clean(box.text)
    else:
        ap = _form_xobject(pdf, _mark_ops(box.kind, box.size, rgb).encode("latin-1") + b"\n", [0, 0, w, h], None,
                           _rot_matrix(rot))
        nm = box.id if box.id.startswith(PREFIX_MARK) else PREFIX_MARK + uuid.uuid4().hex[:16]
        contents = MARKS[box.kind]
    fam = FONTS[box.font][0].split("-")[0]
    ds = (f"font: {_num(box.size)}pt {fam}; font-family: {fam}; font-size: {_num(box.size)}pt; "
          f"font-weight: {'bold' if box.bold else 'normal'}; color: {_hex(rgb)}")
    pstyle = ds + (f"; prumo-kind: {box.kind}" if box.kind != "text" else "")
    std = {"helvetica": "Helv", "times": "TiRo", "courier": "Cour"}[box.font]
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FreeText, Rect=pikepdf.Array([float(v) for v in rect]),
        Contents=pikepdf.String(contents), NM=pikepdf.String(nm), T=pikepdf.String(AUTHOR),
        M=pikepdf.String(_pdf_date()), F=4,
        DA=pikepdf.String(f"/{std} {_num(box.size)} Tf {_num(rgb[0])} {_num(rgb[1])} {_num(rgb[2])} rg"),
        DS=pikepdf.String(ds), Q=0,
        BS=pikepdf.Dictionary(W=0), Border=pikepdf.Array([0, 0, 0]),
        P=pdf.pages[page_index].obj,
    )
    annot["/PrumoStyle"] = pikepdf.String(pstyle)
    annot["/AP"] = pikepdf.Dictionary(N=ap)
    box.id = nm
    return pdf.make_indirect(annot)


# --- Gravar ------------------------------------------------------------------------

def _set_text(pdf, node, f: Field, value: str, widgets):
    import pikepdf
    if f.maxlen > 0:
        value = value[:f.maxlen]
    target = node
    target["/V"] = pikepdf.String(value)
    for w in widgets:
        ap = _text_appearance(pdf, f, w, value)
        w["/AP"] = pikepdf.Dictionary(N=ap)


def apply(pdf, values: dict, boxes: list[Box]) -> None:
    """Grava valores dos campos e troca as caixas do Prumo pelas de `boxes` (num pikepdf.Pdf aberto)."""
    import pikepdf

    acro = pdf.Root.get("/AcroForm")
    if acro is not None:
        known = {f.name: f for f in _fields(pdf)[0]}
        for node, name, widgets in _terminal_fields(acro):
            f = known.get(name or "")
            if f is None or f.readonly or name not in values:
                continue
            value = values[name]
            if value == f.value:
                continue
            live = [w for w in widgets if "/Rect" in w]
            if f.kind == "text":
                _set_text(pdf, node, f, clean(str(value or "")), live)
            elif f.kind in ("combo", "list"):
                v = clean(str(value or ""))
                node["/V"] = pikepdf.String(v)
                idx = [k for k, (exp, _d) in enumerate(f.options) if exp == v]
                if idx:
                    node["/I"] = pikepdf.Array(idx)
                elif "/I" in node:
                    del node["/I"]
                for w in live:
                    w["/AP"] = pikepdf.Dictionary(N=_choice_appearance(pdf, f, w, v))
            elif f.kind == "check":
                on = bool(value)
                states = [s for w in live for s in _widget_states(w)]
                state = states[0] if states else "Yes"
                node["/V"] = pikepdf.Name("/" + state) if on else pikepdf.Name.Off
                for w in live:
                    ws = _widget_states(w)
                    w["/AS"] = pikepdf.Name("/" + (ws[0] if ws else state)) if on else pikepdf.Name.Off
            elif f.kind == "radio":
                state = str(value or "")
                node["/V"] = pikepdf.Name("/" + state) if state else pikepdf.Name.Off
                for w in live:
                    ws = _widget_states(w)
                    w["/AS"] = pikepdf.Name("/" + state) if state and state in ws else pikepdf.Name.Off
        if "/XFA" in acro:
            del acro["/XFA"]   # os leitores passam a mostrar os campos AcroForm, que têm os valores novos
        if acro.get("/NeedAppearances"):
            acro["/NeedAppearances"] = False   # as aparências estão prontas
    geos = [page_geo(p) for p in pdf.pages]
    for i, page in enumerate(pdf.pages):
        annots = page.obj.get("/Annots")
        if annots is None:
            continue
        keep = pikepdf.Array()
        for a in annots:
            try:
                nm = str(a.get("/NM", ""))
                if a.get("/Subtype") == "/FreeText" and nm.startswith((PREFIX_TEXT, PREFIX_MARK)):
                    continue
            except Exception:  # noqa: BLE001
                pass
            keep.append(a)
        page.obj["/Annots"] = keep
    for box in boxes:
        if box.kind == "text" and not clean(box.text).strip():
            continue
        if not 0 <= box.page < len(pdf.pages):
            continue
        page = pdf.pages[box.page]
        ref = _box_annotation(pdf, box.page, geos[box.page], box)
        if "/Annots" not in page.obj:
            page.obj["/Annots"] = pikepdf.Array()
        page.obj["/Annots"].append(ref)


def save(path, values: dict, boxes: list[Box]) -> None:
    """Grava no próprio arquivo (para Library.modify, que guarda a versão anterior para o Desfazer)."""
    import pdfops
    pdf = pdfops._open(path)
    try:
        apply(pdf, values, boxes)
        pdfops._save_inplace(pdf, path)
    finally:
        try:
            pdf.close()
        except Exception:  # noqa: BLE001
            pass


# --- Cópia para desenhar a tela de preenchimento -------------------------------------

def make_base(src, dest) -> None:
    """Cópia sem as aparências dos campos que se preenchem e sem as caixas do Prumo: a tela desenha essas
    partes por cima, editáveis, sem o valor antigo aparecer por baixo."""
    import pikepdf
    with pikepdf.open(str(src)) as pdf:
        fields, _xfa, _only = _fields(pdf)
        hide = {w.key for f in fields for w in f.widgets}
        for page in pdf.pages:
            annots = page.obj.get("/Annots")
            if annots is None:
                continue
            keep = pikepdf.Array()
            for a in annots:
                try:
                    if a.objgen in hide:
                        continue
                    nm = str(a.get("/NM", ""))
                    if a.get("/Subtype") == "/FreeText" and nm.startswith((PREFIX_TEXT, PREFIX_MARK)):
                        continue
                except Exception:  # noqa: BLE001
                    pass
                keep.append(a)
            page.obj["/Annots"] = keep
        pdf.save(str(dest))


# --- Achatar ("Finalizar") -------------------------------------------------------------

def _resources(page):
    import pikepdf
    res = page.obj.get("/Resources")
    if res is None:
        node = page.obj.get("/Parent")
        while node is not None and res is None:
            res = node.get("/Resources")
            node = node.get("/Parent")
        res = pikepdf.Dictionary() if res is None else pikepdf.Dictionary(copy.copy(dict(res.items())))
        page.obj["/Resources"] = res
    return res


def _flatten_matrix(ap, rect):
    bbox = [float(v) for v in ap.get("/BBox", [0, 0, 0, 0])]
    m = [float(v) for v in ap.get("/Matrix", [1, 0, 0, 1, 0, 0])]
    pts = [(bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3])]
    tx = [m[0] * x + m[2] * y + m[4] for x, y in pts]
    ty = [m[1] * x + m[3] * y + m[5] for x, y in pts]
    x0, x1, y0, y1 = min(tx), max(tx), min(ty), max(ty)
    l, b, r, t = rect
    sx = (r - l) / (x1 - x0) if x1 > x0 else 1.0
    sy = (t - b) / (y1 - y0) if y1 > y0 else 1.0
    return sx, sy, l - x0 * sx, b - y0 * sy


def flatten(src, dest) -> int:
    """Cópia com campos e caixas do Prumo gravados no desenho das páginas. Devolve quantos foram achatados."""
    import pikepdf
    count = 0
    with pikepdf.open(str(src)) as pdf:
        for page in pdf.pages:
            annots = page.obj.get("/Annots")
            if annots is None:
                continue
            keep = pikepdf.Array()
            ops = []
            for a in annots:
                try:
                    sub = a.get("/Subtype")
                    nm = str(a.get("/NM", ""))
                    flat = sub == "/Widget" or (sub == "/FreeText" and nm.startswith((PREFIX_TEXT, PREFIX_MARK)))
                    if not flat:
                        keep.append(a)
                        continue
                    flags = int(a.get("/F", 0) or 0)
                    ap = (a.get("/AP") or {}).get("/N")
                    if ap is not None and not isinstance(ap, pikepdf.Stream):
                        state = a.get("/AS")
                        ap = ap.get(str(state)) if state is not None and str(state) in ap else None
                    if ap is None or flags & 2 or flags & 32 or not isinstance(ap, pikepdf.Stream):
                        continue                    # sem desenho (ou escondido): simplesmente sai
                    if "/BBox" not in ap:
                        continue
                    rect = [float(v) for v in a["/Rect"]]
                    rect = (min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3]))
                    sx, sy, tx, ty = _flatten_matrix(ap, rect)
                    res = _resources(page)
                    if "/XObject" not in res:
                        res["/XObject"] = pikepdf.Dictionary()
                    name = f"/PrumoFx{uuid.uuid4().hex[:10]}"
                    res["/XObject"][name] = ap
                    ops.append(f"q {_num(sx)} 0 0 {_num(sy)} {_num(tx)} {_num(ty)} cm {name} Do Q")
                    count += 1
                except Exception:  # noqa: BLE001
                    keep.append(a)
            if ops:
                page.contents_add(pikepdf.Stream(pdf, b"q\n"), prepend=True)
                page.contents_add(pikepdf.Stream(pdf, b"\nQ\n" + "\n".join(ops).encode("latin-1") + b"\n"))
            page.obj["/Annots"] = keep
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root.AcroForm
            sigs = pikepdf.Array([f for f in acro.get("/Fields", []) if str(f.get("/FT", "")) == "/Sig"])
            if len(sigs):
                acro["/Fields"] = sigs
            else:
                del pdf.Root["/AcroForm"]
        pdf.save(str(dest), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return count


def has_content(path) -> bool:
    """O PDF tem campos ou caixas do Prumo (algo para finalizar)?"""
    try:
        data = load(path)
    except Exception:  # noqa: BLE001
        return False
    return bool(data.fields or data.boxes)
