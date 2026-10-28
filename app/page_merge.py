"""Tela 'Combinar PDFs'."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

import core
from ui_common import (C, DropZone, MessageBar, PageHeader, human_size, icon, last_dir,
                       remember_dir, settings)

ROLE_PATH = Qt.UserRole
ROLE_PAGES = Qt.UserRole + 1


class CountThread(QThread):
    counted = Signal(str, int, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        for p in self.paths:
            try:
                self.counted.emit(p, core.page_count(p), "")
            except Exception as exc:
                self.counted.emit(p, -1, core.open_error_message(exc))


class MergeThread(QThread):
    done = Signal(str, int, str)

    def __init__(self, paths, out, bookmarks):
        super().__init__()
        self.paths, self.out, self.bookmarks = paths, out, bookmarks

    def run(self):
        try:
            n = core.merge_pdfs(self.paths, self.out, self.bookmarks)
            self.done.emit(self.out, n, "")
        except Exception as exc:
            self.done.emit(self.out, 0, str(exc))


class MergePage(QWidget):
    def __init__(self):
        super().__init__()
        self.threads = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        root.addWidget(PageHeader(
            "Combinar PDFs",
            "Junta vários PDFs em um só, na ordem da lista. Arraste os itens para mudar a ordem."))

        self.drop = DropZone("Arraste PDFs ou uma pasta para cá", "ou clique para escolher",
                             multiple=True, compact=True)
        self.drop.files_dropped.connect(self.add_files)
        root.addWidget(self.drop)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAlternatingRowColors(True)
        self.list.setSpacing(1)
        self.list.model().rowsMoved.connect(lambda *a: self._renumber())
        mid.addWidget(self.list, 1)

        side = QVBoxLayout()
        side.setSpacing(8)
        self.btn_up = QPushButton(" Subir")
        self.btn_up.setIcon(icon("up", C["text"], 16))
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QPushButton(" Descer")
        self.btn_down.setIcon(icon("down", C["text"], 16))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_sort = QPushButton("Ordenar por nome")
        self.btn_sort.clicked.connect(self._sort)
        self.btn_remove = QPushButton(" Remover")
        self.btn_remove.setIcon(icon("trash", C["muted"], 16))
        self.btn_remove.clicked.connect(self._remove)
        self.btn_clear = QPushButton("Limpar lista")
        self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_up, self.btn_down, self.btn_sort, self.btn_remove, self.btn_clear):
            side.addWidget(b)
        side.addStretch(1)
        mid.addLayout(side)
        root.addLayout(mid, 1)

        self.msg = MessageBar()
        root.addWidget(self.msg)

        bottom = QHBoxLayout()
        self.summary = QLabel("Nenhum arquivo na lista.")
        self.summary.setStyleSheet(f"color: {C['muted']};")
        self.chk_bookmarks = QCheckBox("Criar um marcador para cada arquivo")
        self.chk_bookmarks.setToolTip("No leitor de PDF, o painel de marcadores mostra onde começa cada arquivo.\n"
                                      "Os marcadores que os arquivos já tinham ficam dentro do marcador do arquivo.")
        self.chk_bookmarks.setChecked(settings().value("merge_bookmarks", "true") == "true")
        self.btn_go = QPushButton("Combinar e salvar…")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._merge)
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(self.chk_bookmarks)
        bottom.addSpacing(12)
        bottom.addWidget(self.btn_go)
        root.addLayout(bottom)
        self._refresh()

    # --- lista -----------------------------------------------------------------------
    def add_files(self, paths):
        known = {os.path.normcase(os.path.abspath(self.list.item(i).data(ROLE_PATH)))
                 for i in range(self.list.count())}
        new = []
        for p in paths:
            if os.path.normcase(os.path.abspath(p)) in known:
                continue
            it = QListWidgetItem(icon("file", C["muted"], 18), Path(p).name)
            it.setData(ROLE_PATH, p)
            it.setData(ROLE_PAGES, None)
            it.setToolTip(p)
            self.list.addItem(it)
            new.append(p)
        if new:
            remember_dir(new[0])
            th = CountThread(new)
            th.counted.connect(self._on_counted)
            th.finished.connect(lambda t=th: self.threads.remove(t) if t in self.threads else None)
            self.threads.append(th)
            th.start()
        self._renumber()

    def _item(self, path):
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_PATH) == path:
                return self.list.item(i)
        return None

    def _on_counted(self, path, n, err):
        it = self._item(path)
        if it is None:
            return
        it.setData(ROLE_PAGES, n)
        if err:
            it.setForeground(Qt.red)
            it.setToolTip(f"{path}\n{err}")
        self._renumber()

    def _renumber(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = it.data(ROLE_PATH)
            n = it.data(ROLE_PAGES)
            try:
                size = human_size(os.path.getsize(p))
            except OSError:
                size = "?"
            pages = "…" if n is None else ("ilegível" if n < 0 else f"{n} pág.")
            it.setText(f"{i + 1}.  {Path(p).name}      —  {pages} · {size}")
        self._refresh()

    def _move(self, delta):
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()}, reverse=delta > 0)
        if not rows:
            return
        if (delta < 0 and rows[0] == 0) or (delta > 0 and rows[0] == self.list.count() - 1):
            return
        for r in rows:
            it = self.list.takeItem(r)
            self.list.insertItem(r + delta, it)
            it.setSelected(True)
        self._renumber()

    def _sort(self):
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        items.sort(key=lambda it: Path(it.data(ROLE_PATH)).name.lower())
        for it in items:
            self.list.addItem(it)
        self._renumber()

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._renumber()

    def _clear(self):
        self.list.clear()
        self.msg.hide()
        self._renumber()

    def _refresh(self):
        n = self.list.count()
        pages = [self.list.item(i).data(ROLE_PAGES) for i in range(n)]
        known = [p for p in pages if p is not None and p >= 0]
        bad = any(p is not None and p < 0 for p in pages)
        if n == 0:
            self.summary.setText("Nenhum arquivo na lista.")
        else:
            total = sum(known)
            self.summary.setText(f"{n} arquivo(s) · {total} página(s) no total"
                                 + ("" if len(known) == n else " (contando…)" if not bad else ""))
        self.btn_go.setEnabled(n >= 2 and not bad and len(known) == n)
        for b in (self.btn_up, self.btn_down, self.btn_sort, self.btn_remove, self.btn_clear):
            b.setEnabled(n > 0)
        if bad:
            self.summary.setText(self.summary.text() + " — remova os arquivos ilegíveis (em vermelho).")

    # --- combinar ------------------------------------------------------------------------
    def _merge(self):
        paths = [self.list.item(i).data(ROLE_PATH) for i in range(self.list.count())]
        first = Path(paths[0])
        suggestion = core.unique_path(first.parent / f"{first.stem} - combinado.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "Salvar PDF combinado", str(suggestion), "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        if any(core.same_file(p, out) for p in paths if os.path.exists(out)):
            self.msg.show_message("error", "Escolha outro nome: o arquivo de saída não pode ser um dos arquivos da lista.")
            return
        settings().setValue("merge_bookmarks", "true" if self.chk_bookmarks.isChecked() else "false")
        self.btn_go.setEnabled(False)
        self.btn_go.setText("Combinando…")
        th = MergeThread(paths, out, self.chk_bookmarks.isChecked())
        th.done.connect(self._on_done)
        th.finished.connect(lambda t=th: self.threads.remove(t) if t in self.threads else None)
        self.threads.append(th)
        th.start()

    def _on_done(self, out, n, err):
        self.btn_go.setText("Combinar e salvar…")
        self._refresh()
        if err:
            self.msg.show_message("error", f"Não foi possível combinar: {err}")
        else:
            self.msg.show_message("ok", f"PDF combinado salvo ({n} páginas): {Path(out).name}", out)

    def shutdown(self):
        for th in list(self.threads):
            th.wait(5000)
