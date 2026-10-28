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
