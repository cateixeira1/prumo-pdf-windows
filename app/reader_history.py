"""
Desfazer e refazer do leitor.

Antes de cada mudança feita no leitor (destacar, apagar ou mudar a cor de um destaque, cortar,
girar, numerar, incluir páginas, adicionar ao resumo), guarda uma cópia dos arquivos que vão
mudar; depois, guarda como ficaram. Desfazer põe de volta a cópia de antes; refazer, a de depois.
As cópias ficam numa pasta temporária e somem quando o leitor fecha.
"""

from __future__ import annotations

import filecmp
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _File:
    kind: str                 # "item": PDF da biblioteca; "raw": arquivo auxiliar (anotação do resumo)
    key: str                  # id do PDF ou caminho completo do arquivo
    rel: str | None           # caminho do PDF na biblioteca (para trazê-lo de volta ao refazer)
    before: Path | None       # cópia de antes (None: o arquivo não existia)
    after: Path | None = None


@dataclass
class Step:
    label: str
    files: list[_File]


def _same(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


class ReaderHistory:
    LIMIT = 30

    def __init__(self, lib):
        self.lib = lib
        self.dir = Path(tempfile.mkdtemp(prefix="prumo_desfazer_"))
        self.undo_steps: list[Step] = []
        self.redo_steps: list[Step] = []
        self._n = 0

    # --- cópias ---
    def _copy(self, path) -> Path | None:
        path = Path(path)
        if not path.exists():
            return None
        self._n += 1
        dest = self.dir / f"{self._n}{path.suffix or '.bin'}"
        shutil.copy2(path, dest)
        return dest

    def _current(self, f: _File) -> Path | None:
        if f.kind == "raw":
            p = Path(f.key)
            return p if p.exists() else None
        item = self.lib.item(f.key)
        return item.path if item is not None and item.path.exists() else None

    @staticmethod
    def _drop(step: Step):
        for f in step.files:
            for p in (f.before, f.after):
                if p is not None:
                    p.unlink(missing_ok=True)

    # --- gravar ---
    def begin(self, items=(), raws=()) -> list[_File]:
        """Antes da mudança: copia os PDFs (`items`) e arquivos auxiliares (`raws`) que podem mudar."""
        files = [_File("item", it.id, it.rel, self._copy(it.path)) for it in items if it is not None]
        files += [_File("raw", str(r), None, self._copy(r)) for r in raws]
        return files

    def commit(self, label: str, files: list[_File], created=()) -> bool:
        """
        Depois da mudança: guarda como os arquivos ficaram. `created`: PDFs que a ação criou
        (o resumo novo, por exemplo). Devolve False (e não guarda nada) se nada mudou.
        """
        for f in files:
            cur = self._current(f)
            f.after = self._copy(cur) if cur is not None else None
        for it in created:
            if it is not None:
                files.append(_File("item", it.id, it.rel, None, self._copy(it.path)))
        step = Step(label, files)
        if all(_same(f.before, f.after) for f in files):
            self._drop(step)
            return False
        self.undo_steps.append(step)
        while len(self.undo_steps) > self.LIMIT:
            self._drop(self.undo_steps.pop(0))
        for s in self.redo_steps:
            self._drop(s)
        self.redo_steps.clear()
        return True

    # --- desfazer e refazer ---
    @property
    def can_undo(self) -> bool:
        return bool(self.undo_steps)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_steps)

    def undo(self) -> Step | None:
        if not self.undo_steps:
            return None
        step = self.undo_steps.pop()
        self._apply(step, "before")
        self.redo_steps.append(step)
        return step

    def redo(self) -> Step | None:
        if not self.redo_steps:
            return None
        step = self.redo_steps.pop()
        self._apply(step, "after")
        self.undo_steps.append(step)
        return step

    def _apply(self, step: Step, which: str):
        files = list(reversed(step.files)) if which == "before" else step.files
        for f in files:
            src = getattr(f, which)
            if f.kind == "raw":
                p = Path(f.key)
                if src is None:
                    p.unlink(missing_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, p)
                continue
            item = self.lib.item(f.key)
            if src is None:
                if item is not None:            # o PDF foi criado por esta ação: sai da biblioteca
                    self.lib.delete([item])
            elif item is None:                  # volta um PDF que o desfazer tinha tirado
                folder, _, name = (f.rel or "").rpartition("/")
                dest = self.lib.unique_path(folder, Path(name).stem or "Resumo")
                shutil.copy2(src, dest)
                new = self.lib.register(dest)
                if new is not None:
                    f.key, f.rel = new.id, new.rel
            else:
                self.lib.modify(item, lambda path, s=src: shutil.copyfile(s, path), keep_review=True)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)
