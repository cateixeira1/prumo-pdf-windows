"""
Operações de páginas usadas pela biblioteca (equivalente ao PDFOps do iPhone).

Todas as gravações são atômicas: o resultado vai primeiro para um arquivo
temporário na mesma pasta e só então substitui o destino.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
        raise UserError(f"Não foi possível abrir o PDF ({exc}).") from None


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
        if len(set(sizes)) == 1:
            n = sizes[0]
            return f"{self.parts} partes de {n} página{'s' if n != 1 else ''}"
        big, small = max(sizes), min(sizes)
        nb = sizes.count(big)
        return (f"{nb} parte{'s' if nb != 1 else ''} de {big} páginas e "
                f"{self.parts - nb} de {small} página{'s' if small != 1 else ''}")


def split(src: str | Path, parts: int, dest_for_part) -> list[Path]:
    """Divide em `parts` partes; `dest_for_part(n)` devolve o caminho da parte n (começando em 1)."""
    with _open(src) as pdf:
        total = len(pdf.pages)
        if parts < 2:
            raise UserError("Escolha pelo menos 2 partes.")
        if parts > total:
            raise UserError(f"O PDF tem {total} página{'s' if total != 1 else ''}; "
                            f"não dá para dividir em {parts} partes.")
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
            raise UserError(f"Páginas inexistentes: {format_ranges(bad)}")
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
                    raise UserError(f"Página inexistente: {page_no}")
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

NUMBER_FORMATS = {
    "n": ("1", "{n}"),
    "pagina": ("Página 1", "Página {n}"),
    "pagina_de": ("Página 1 de 12", "Página {n} de {total}"),
    "barra": ("1/12", "{n}/{total}"),
    "tracos": ("- 1 -", "- {n} -"),
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
    return NUMBER_FORMATS.get(fmt, NUMBER_FORMATS["n"])[1].format(n=n, total=total)


def _text_width(text: str, size: float) -> float:
    return sum(_HELV.get(ch, 556) for ch in text) * size / 1000.0


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


def number_pages(path: str | Path, fmt: str = "n", position: str = "bottom_center", start: int = 1,
                 first_page: int = 1, size: float = 10.0, margin: float = 28.0) -> int:
    """
    Escreve o número em cada página, a partir de `first_page` (começando em 1), contando desde `start`.
    O número vira texto de verdade na página (Helvetica), na posição escolhida como a página aparece
    (já com recorte e giro). Devolve quantas páginas foram numeradas.
    """
    import math

    import pikepdf

    with _open(path) as pdf:
        n = len(pdf.pages)
        first_page = max(1, min(first_page, n))
        total = start + (n - first_page)
        count = 0
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
            ux, uy = _display_to_user(crop, rot, dx, dy)
            a = math.radians(rot)
            c, s = round(math.cos(a), 6), round(math.sin(a), 6)
            font = _page_font(pdf, obj)
            stamp = (b"Q\nq\nBT\n" + f"{font} {size:.2f} Tf 0 g\n".encode()
                     + f"{c} {s} {-s} {c} {ux:.2f} {uy:.2f} Tm\n".encode()
                     + _pdf_string(text) + b" Tj\nET\nQ\n")
            page.contents_add(pikepdf.Stream(pdf, b"q\n"), prepend=True)
            page.contents_add(pikepdf.Stream(pdf, stamp))
            count += 1
        _save_inplace(pdf, path)
    return count
