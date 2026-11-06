"""
Operações de páginas usadas pela biblioteca (equivalente ao PDFOps do iPhone).

Todas as gravações são atômicas: o resultado vai primeiro para um arquivo
temporário na mesma pasta e só então substitui o destino.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from core import format_ranges, parse_page_selection  # noqa: F401  (reexportados)


class UserError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


def _save(pdf, dest: str | Path) -> None:
    import pikepdf

    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    pdf.save(str(tmp), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    os.replace(tmp, dest)


def _open(path: str | Path):
    import pikepdf

    try:
        return pikepdf.open(str(path))
    except pikepdf.PasswordError:
        raise UserError("O PDF está protegido por senha.") from None
    except pikepdf.PdfError as exc:
        raise UserError(__import__("i18n").trf("Não foi possível abrir o PDF ({}).", exc)) from None


def page_count(path: str | Path) -> int:
    with _open(path) as pdf:
        return len(pdf.pages)


# --- Dividir ------------------------------------------------------------------

@dataclass
class SplitPlan:
    total: int
    parts: int

    @property
    def sizes(self) -> list[int]:
        """Páginas por parte. Quando a conta não fecha, as primeiras partes ficam com uma a mais."""
        if self.parts < 1 or self.total < 1:
            return []
        base, extra = divmod(self.total, self.parts)
        return [base + (1 if i < extra else 0) for i in range(self.parts)]

    @property
    def ranges(self) -> list[tuple[int, int]]:
        """Intervalos (início, fim), começando em 1."""
        out, start = [], 1
        for size in self.sizes:
            out.append((start, start + size - 1))
            start += size
        return out

    @property
    def summary(self) -> str:
        sizes = self.sizes
        if not sizes:
            return ""
        from i18n import trf, trn

        def pages(k):
            return trn(k, "1 página", "{} páginas")
        if len(set(sizes)) == 1:
            return trn(self.parts, "1 parte de {}", "{} partes de {}", pages(sizes[0]))
        big, small = max(sizes), min(sizes)
        nb = sizes.count(big)
        return trf("{} e {}", trn(nb, "1 parte de {}", "{} partes de {}", pages(big)),
                   trn(self.parts - nb, "1 parte de {}", "{} partes de {}", pages(small)))


def split(src: str | Path, parts: int, dest_for_part) -> list[Path]:
    """Divide em `parts` partes; `dest_for_part(n)` devolve o caminho da parte n (começando em 1)."""
    with _open(src) as pdf:
        total = len(pdf.pages)
        if parts < 2:
            raise UserError("Escolha pelo menos 2 partes.")
        if parts > total:
            from i18n import trf, trn
            raise UserError(trf("O PDF tem {}; não dá para dividir em {} partes.",
                                trn(total, "1 página", "{} páginas"), parts))
        import pikepdf

        outs = []
        for n, (a, b) in enumerate(SplitPlan(total, parts).ranges, start=1):
            with pikepdf.new() as dst:
                for i in range(a - 1, b):
                    dst.pages.append(pdf.pages[i])
                path = Path(dest_for_part(n))
                _save(dst, path)
                outs.append(path)
        return outs


# --- Extrair, remover, incluir, reorganizar -----------------------------------

def extract(src: str | Path, dest: str | Path, pages: list[int]) -> int:
    """Novo PDF só com as páginas indicadas (começando em 1), na ordem dada."""
    import pikepdf

    if not pages:
        raise UserError("Nenhuma página selecionada.")
    with _open(src) as pdf:
        n = len(pdf.pages)
        bad = [p for p in pages if p < 1 or p > n]
        if bad:
            raise UserError(__import__("i18n").trf("Páginas inexistentes: {}", format_ranges(bad)))
        with pikepdf.new() as dst:
            for p in pages:
                dst.pages.append(pdf.pages[p - 1])
            _save(dst, dest)
    return len(pages)


def remove(path: str | Path, pages: list[int]) -> int:
    """Remove as páginas do próprio arquivo. Devolve quantas páginas sobraram."""
    with _open(path) as pdf:
        n = len(pdf.pages)
        drop = sorted({p for p in pages if 1 <= p <= n}, reverse=True)
        if not drop:
            raise UserError("Nenhuma página selecionada.")
        if len(drop) >= n:
            raise UserError("Não dá para remover todas as páginas. Para apagar o PDF, use Excluir.")
        for p in drop:
            del pdf.pages[p - 1]
        left = len(pdf.pages)
        _save_inplace(pdf, path)
    return left


def insert(target: str | Path, source: str | Path, pages: list[int], at: int) -> int:
    """Inclui `pages` de `source` em `target`, antes da página `at` (1 = início; total+1 = fim)."""
    if not pages:
        raise UserError("Nenhuma página selecionada.")
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        # Páginas do próprio PDF: trabalha sobre uma cópia da origem.
        import shutil
        import tempfile

        fd, copy = tempfile.mkstemp(suffix=".pdf", prefix="prumo_src_")
        os.close(fd)
        shutil.copyfile(source, copy)
        try:
            return insert(target, copy, pages, at)
        finally:
            os.remove(copy)
    with _open(source) as src, _open(target) as dst:
        n = len(dst.pages)
        at = max(1, min(at, n + 1))
        for offset, p in enumerate(pages):
            dst.pages.insert(at - 1 + offset, src.pages[p - 1])
        _save_inplace(dst, target)
    return len(pages)


def arrange(path: str | Path, entries: list[tuple[int, int]]) -> None:
    """
    Reorganiza: `entries` é a nova ordem, como (página original começando em 1, rotação extra em graus).
    Páginas ausentes da lista são excluídas.
    """
    import pikepdf

    if not entries:
        raise UserError("O PDF precisa ter pelo menos uma página.")
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    with _open(path) as pdf:
        n = len(pdf.pages)
        with pikepdf.new() as out:
            for page_no, rot in entries:
                if not 1 <= page_no <= n:
                    raise UserError(__import__("i18n").trf("Página inexistente: {}", page_no))
                out.pages.append(pdf.pages[page_no - 1])
                if rot % 360:
                    out.pages[-1].rotate(rot % 360, relative=True)
            out.save(str(tmp), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    # Só substitui depois de fechar o original (no Windows, arquivo aberto não pode ser trocado).
    os.replace(tmp, path)


def _save_inplace(pdf, path: str | Path) -> None:
    """Grava um PDF aberto sobre o próprio arquivo (pikepdf não grava sobre o arquivo aberto)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    import pikepdf

    pdf.save(str(tmp), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()
    os.replace(tmp, path)


# --- Senha (criptografia padrão de PDF) ---------------------------------------------------

def is_encrypted(path: str | Path) -> bool:
    """O PDF pede senha para abrir? (Só a senha de dono, sem senha de abertura, não conta.)"""
    import pikepdf
    try:
        with pikepdf.open(str(path)):
            return False
    except pikepdf.PasswordError:
        return True
    except Exception:
        return False


def page_count_locked(path: str | Path) -> int | None:
    """Número de páginas de um PDF com senha, lido sem abrir o conteúdo (quando der)."""
    import re
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    counts = [int(m.group(1)) for m in re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
    counts += [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", data)]
    return max(counts) if counts else None


def check_password(path: str | Path, password: str) -> bool:
    import pikepdf
    try:
        with pikepdf.open(str(path), password=password):
            return True
    except pikepdf.PasswordError:
        return False


def protect(src: str | Path, dest: str | Path, password: str) -> None:
    """
    Grava uma cópia com senha, na criptografia padrão de PDF (AES-256): qualquer leitor de PDF
    (Adobe, Edge, Chrome, o do iPhone) abre com a senha. Sem a senha, não há como abrir.
    """
    import pikepdf
    if not password:
        raise UserError("Digite uma senha.")
    with _open(src) as pdf:
        pdf.save(str(dest), encryption=pikepdf.Encryption(owner=password, user=password, R=6, aes=True),
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)


def unprotect(src: str | Path, dest: str | Path, password: str) -> None:
    """Grava uma cópia sem senha (precisa da senha atual)."""
    import pikepdf
    try:
        pdf = pikepdf.open(str(src), password=password)
    except pikepdf.PasswordError:
        raise UserError("Senha incorreta.") from None
    with pdf:
        pdf.save(str(dest), object_stream_mode=pikepdf.ObjectStreamMode.generate)


# --- Cortar margens e girar ---------------------------------------------------------------------
# As margens são dadas como a página aparece na tela (esquerda, alto, direita, baixo), em pontos,
# a partir da página inteira (MediaBox). Elas viram o CropBox, o recorte padrão do PDF: o conteúdo
# fora dele continua no arquivo e volta com "Página inteira" (ou em qualquer programa de PDF).

def _inherited(page_obj, key: str):
    node, seen = page_obj, 0
    while node is not None and seen < 64:
        if key in node:
            return node[key]
        node = node.get("/Parent")
        seen += 1
    return None


def _box(page_obj, key: str = "/MediaBox") -> tuple[float, float, float, float]:
    b = _inherited(page_obj, key)
    if b is None and key != "/MediaBox":
        return _box(page_obj, "/MediaBox")
    if b is None:
        return (0.0, 0.0, 612.0, 792.0)
    x0, y0, x1, y1 = (float(v) for v in list(b)[:4])
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _rotation(page_obj) -> int:
    r = _inherited(page_obj, "/Rotate")
    try:
        return int(r) % 360 if r is not None else 0
    except (TypeError, ValueError):
        return 0


def margins_to_box(media, rotate: int, margins) -> tuple[float, float, float, float]:
    """Margens (esquerda, alto, direita, baixo) como aparecem na tela → CropBox no espaço do PDF."""
    x0, y0, x1, y1 = media
    l, t, r, b = margins
    rot = rotate % 360
    if rot == 90:
        box = (x0 + t, y0 + l, x1 - b, y1 - r)
    elif rot == 180:
        box = (x0 + r, y0 + t, x1 - l, y1 - b)
    elif rot == 270:
        box = (x0 + b, y0 + r, x1 - t, y1 - l)
    else:
        box = (x0 + l, y0 + b, x1 - r, y1 - t)
    if box[2] - box[0] < 18 or box[3] - box[1] < 18:
        raise UserError("As margens deixam a página pequena demais.")
    return box


def box_to_margins(media, rotate: int, box) -> tuple[float, float, float, float]:
    """O inverso de margins_to_box: CropBox → margens (esquerda, alto, direita, baixo) na tela."""
    x0, y0, x1, y1 = media
    cx0, cy0, cx1, cy1 = box
    dl, db, dr, dt = cx0 - x0, cy0 - y0, x1 - cx1, y1 - cy1   # recortes no espaço do PDF
    rot = rotate % 360
    if rot == 90:
        return (db, dl, dt, dr)
    if rot == 180:
        return (dr, db, dl, dt)
    if rot == 270:
        return (dt, dr, db, dl)
    return (dl, dt, dr, db)


def page_boxes(path: str | Path) -> list[dict]:
    """Para cada página: MediaBox, CropBox e giro (para a tela de cortar)."""
    with _open(path) as pdf:
        return [{"media": _box(p.obj), "crop": _box(p.obj, "/CropBox"), "rotate": _rotation(p.obj)}
                for p in pdf.pages]


def crop_and_rotate(path: str | Path, pages: list[int], margins=None, rotate_by: int = 0) -> int:
    """
    Gira (`rotate_by`, em graus, no sentido horário) e corta (`margins` em pontos, como a página fica
    depois do giro; None não mexe no corte; (0, 0, 0, 0) volta à página inteira) as páginas indicadas
    (começando em 1). Grava no próprio arquivo. Devolve quantas páginas mudaram.
    """
    import pikepdf

    with _open(path) as pdf:
        n = len(pdf.pages)
        todo = sorted({p for p in pages if 1 <= p <= n})
        if not todo:
            raise UserError("Nenhuma página selecionada.")
        for p in todo:
            page = pdf.pages[p - 1]
            if rotate_by % 360:
                page.obj["/Rotate"] = (_rotation(page.obj) + rotate_by) % 360
            if margins is not None:
                media = _box(page.obj)
                if all(abs(m) < 0.01 for m in margins):
                    page.obj["/CropBox"] = pikepdf.Array([float(v) for v in media])
                else:
                    box = margins_to_box(media, _rotation(page.obj), margins)
                    page.obj["/CropBox"] = pikepdf.Array([round(v, 3) for v in box])
        _save_inplace(pdf, path)
    return len(todo)


# --- Numerar páginas --------------------------------------------------------------------------------

# (exemplo, modelo). Os modelos com palavra ("Página {}") saem no idioma dos textos gravados no PDF.
NUMBER_FORMATS = {
    "n": ("1", "{}"),
    "pagina": ("Página 1", "Página {}"),
    "pagina_de": ("Página 1 de 12", "Página {} de {}"),
    "barra": ("1/12", "{}/{}"),
    "tracos": ("- 1 -", "- {} -"),
}
NUMBER_POSITIONS = {
    "bottom_center": "Embaixo, no centro",
    "bottom_right": "Embaixo, à direita",
    "bottom_left": "Embaixo, à esquerda",
    "top_center": "No alto, no centro",
    "top_right": "No alto, à direita",
    "top_left": "No alto, à esquerda",
}
# larguras da Helvetica (em milésimos do corpo), para alinhar o número ao centro ou à direita
_HELV = {" ": 278, "/": 278, "-": 333, "P": 667, "i": 222, "á": 556, "a": 556, "g": 556, "n": 556,
         "d": 556, "e": 556}


def number_text(fmt: str, n: int, total: int) -> str:
    import i18n
    template = NUMBER_FORMATS.get(fmt, NUMBER_FORMATS["n"])[1]
    return i18n.trf_in(i18n.doc_language(), template, n, total)


def number_example(fmt: str) -> str:
    """Exemplo do formato para a lista ("Página 1 de 12" no idioma dos textos gravados no PDF)."""
    return number_text(fmt, 1, 12)


def _text_width(text: str, size: float) -> float:
    try:
        from fpdf.fonts import CORE_FONTS_CHARWIDTHS
        widths = CORE_FONTS_CHARWIDTHS["helvetica"]
    except Exception:  # noqa: BLE001
        widths = _HELV
    return sum(widths.get(ch, 556) for ch in text) * size / 1000.0


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _display_to_user(crop, rotate: int, dx: float, dy: float) -> tuple[float, float]:
    """Ponto na página como aparece (origem no alto à esquerda) → espaço do PDF."""
    x0, y0, x1, y1 = crop
    rot = rotate % 360
    if rot == 90:
        return x0 + dy, y0 + dx
    if rot == 180:
        return x1 - dx, y0 + dy
    if rot == 270:
        return x1 - dy, y1 - dx
    return x0 + dx, y1 - dy


def _page_font(pdf, page_obj):
    """Garante a Helvetica nos recursos da página (com /Resources herdados copiados para a página)."""
    import pikepdf

    if "/Resources" not in page_obj:
        inherited = _inherited(page_obj, "/Resources")
        page_obj["/Resources"] = pikepdf.Dictionary(inherited) if inherited is not None else pikepdf.Dictionary()
    res = page_obj["/Resources"]
    if "/Font" not in res:
        res["/Font"] = pikepdf.Dictionary()
    fonts = res["/Font"]
    name = "/PrumoNum"
    if name not in fonts:
        fonts[name] = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
            Encoding=pikepdf.Name.WinAnsiEncoding))
    return name


NUMBER_MARK = "PrumoNum"          # comentário no conteúdo da página: identifica o número gravado pelo Prumo


@dataclass
class NumberReport:
    """O que aconteceu na última numeração (para o aviso mostrado ao usuário)."""
    numbered: int = 0
    replaced: int = 0                                   # páginas cujo número anterior do Prumo (mesma posição) foi trocado
    moved: list[int] = field(default_factory=list)      # páginas (a partir de 1) com algo na posição: o número foi deslocado
    crowded: list[int] = field(default_factory=list)    # páginas sem lugar livre perto: o número ficou na posição escolhida


LAST_NUMBERING = NumberReport()


def _strip_previous_numbers(pdf, position: str) -> int:
    """Tira os números que o Prumo gravou antes, na mesma posição (numerar de novo troca, não empilha)."""
    import pikepdf

    marker = f"% {NUMBER_MARK} {position}\n".encode()
    pages = 0
    for page in pdf.pages:
        try:
            contents = page.obj.get("/Contents")
            if contents is None or not isinstance(contents, pikepdf.Array):
                continue
            keep = []
            for stream in contents:
                small = int(stream.get("/Length", 0)) < 4096
                if small and marker in stream.read_bytes():
                    continue
                keep.append(stream)
            if len(keep) != len(contents):
                page.obj["/Contents"] = pikepdf.Array(keep)
                pages += 1
        except Exception:  # noqa: BLE001  (página estranha: deixa como está)
            continue
    return pages


class _OverlapChecker:
    """Vê se já existe texto ou tinta (número impresso, carimbo, borda escaneada) no lugar do número."""

    INK_LEVEL = 140          # tons abaixo disso contam como tinta
    INK_SHARE = 0.004        # fração mínima de tinta na caixa para contar como ocupada

    def __init__(self, path):
        import core
        import pypdfium2 as pdfium

        self._lock = core.PDFIUM_LOCK
        with self._lock:
            self.doc = pdfium.PdfDocument(str(path))

    def close(self):
        with self._lock:
            try:
                self.doc.close()
            except Exception:  # noqa: BLE001
                pass

    def occupied(self, index: int, crop, rot: int, box) -> bool:
        """`box`: (esquerda, alto, direita, baixo) como a página aparece, origem no alto à esquerda."""
        x0, y0, x1, y1 = box
        with self._lock:
            try:
                page = self.doc[index]
            except Exception:  # noqa: BLE001
                return False
            try:
                a = _display_to_user(crop, rot, x0, y0)
                b = _display_to_user(crop, rot, x1, y1)
                tp = page.get_textpage()
                try:
                    found = tp.get_text_bounded(left=min(a[0], b[0]), bottom=min(a[1], b[1]),
                                                right=max(a[0], b[0]), top=max(a[1], b[1]))
                finally:
                    tp.close()
                if found and found.strip():
                    return True
                w, h = page.get_size()
                scale = 2.0
                bmp = page.render(scale=scale, crop=(max(0.0, x0), max(0.0, h - y1), max(0.0, w - x1), max(0.0, y0)),
                                  may_draw_forms=False)
                im = bmp.to_pil().convert("L")
                hist = im.histogram()
                total = max(1, im.width * im.height)
                return sum(hist[:self.INK_LEVEL]) / total > self.INK_SHARE
            except Exception:  # noqa: BLE001  (não deu para conferir: segue sem deslocar)
                return False
            finally:
                page.close()


def number_pages(path: str | Path, fmt: str = "n", position: str = "bottom_center", start: int = 1,
                 first_page: int = 1, size: float = 10.0, margin: float = 28.0, avoid_overlap: bool = True) -> int:
    """
    Escreve o número em cada página, a partir de `first_page` (começando em 1), contando desde `start`.
    O número vira texto de verdade na página (Helvetica), na posição escolhida como a página aparece
    (já com recorte e giro), marcado como número de página (artefato de paginação do PDF).
    - Numerar de novo, na mesma posição, troca os números que o Prumo gravou antes (não empilha).
    - Se já houver texto ou tinta onde o número iria (número impresso no documento, carimbo, borda), o número
      é deslocado para o lado livre mais próximo, em vez de ficar por cima.
    Devolve quantas páginas foram numeradas; os detalhes ficam em `LAST_NUMBERING`.
    """
    import math

    import pikepdf

    global LAST_NUMBERING
    report = NumberReport()
    with _open(path) as pdf:
        n = len(pdf.pages)
        first_page = max(1, min(first_page, n))
        total = start + (n - first_page)
        report.replaced = _strip_previous_numbers(pdf, position)
        check_path, tmp = Path(path), None
        if report.replaced:
            tmp = Path(str(path) + ".chk")
            pdf.save(str(tmp))
            check_path = tmp
        checker = _OverlapChecker(check_path) if avoid_overlap else None
        tag = f"% {NUMBER_MARK} {position}\n".encode()
        try:
            for i in range(first_page - 1, n):
                page = pdf.pages[i]
                obj = page.obj
                crop = _box(obj, "/CropBox")
                rot = _rotation(obj)
                wd, hd = crop[2] - crop[0], crop[3] - crop[1]
                if rot in (90, 270):
                    wd, hd = hd, wd
                text = number_text(fmt, start + (i - (first_page - 1)), total)
                tw = _text_width(text, size)
                vert, horiz = position.split("_")
                dx = {"left": margin, "center": (wd - tw) / 2, "right": wd - margin - tw}[horiz]
                dy = (hd - margin) if vert == "bottom" else (margin + size * 0.72)
                if checker is not None:
                    def box_at(y):
                        return (dx - 2, y - size * 0.78 - 1, dx + tw + 2, y + size * 0.26 + 1)
                    if checker.occupied(i, crop, rot, box_at(dy)):
                        step = size * 1.5 if vert == "bottom" else -size * 1.5
                        free = None
                        for k in range(1, 6):
                            y = dy - k * step
                            if y - size * 0.8 < 2 or y + size * 0.3 > hd - 2:
                                break
                            if not checker.occupied(i, crop, rot, box_at(y)):
                                free = y
                                break
                        if free is None:
                            report.crowded.append(i + 1)
                        else:
                            dy = free
                            report.moved.append(i + 1)
                ux, uy = _display_to_user(crop, rot, dx, dy)
                a = math.radians(rot)
                c, s = round(math.cos(a), 6), round(math.sin(a), 6)
                font = _page_font(pdf, obj)
                stamp = (b"Q\nq\n" + tag + b"/Artifact <</Type /Pagination /Subtype /PageNum>> BDC\nBT\n"
                         + f"{font} {size:.2f} Tf 0 g\n".encode()
                         + f"{c} {s} {-s} {c} {ux:.2f} {uy:.2f} Tm\n".encode()
                         + _pdf_string(text) + b" Tj\nET\nEMC\nQ\n")
                page.contents_add(pikepdf.Stream(pdf, b"q\n" + tag), prepend=True)
                page.contents_add(pikepdf.Stream(pdf, stamp))
                report.numbered += 1
        finally:
            if checker is not None:
                checker.close()
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        _save_inplace(pdf, path)
    LAST_NUMBERING = report
    return report.numbered
