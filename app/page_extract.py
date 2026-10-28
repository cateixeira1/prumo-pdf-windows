"""Tela 'Extrair páginas'."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QThread, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

import core
from ui_common import (C, DropZone, MessageBar, PageHeader, card, debounce, icon, remember_dir,
                       section_label)

THUMB_W = 130


def render_page(path: str, index: int, width: int) -> QImage | None:
    import pypdfium2 as pdfium

    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[index]
            w, _h = page.get_size()
            bmp = page.render(scale=width / max(w, 1), may_draw_forms=True)
            img = bmp.to_pil().convert("RGB")
            page.close()
        finally:
            pdf.close()
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, 3 * img.width, QImage.Format_RGB888).copy()


class ThumbThread(QThread):
    rendered = Signal(str, int, QImage)

    def __init__(self, path: str, count: int):
        super().__init__()
        self.path, self.count = path, count

    def run(self):
        import pypdfium2 as pdfium

        try:
            with core.PDFIUM_LOCK:
                pdf = pdfium.PdfDocument(self.path)
        except Exception:
            return
        try:
            for i in range(self.count):
                if self.isInterruptionRequested():
                    return
                with core.PDFIUM_LOCK:
                    page = pdf[i]
                    w, _h = page.get_size()
                    bmp = page.render(scale=(THUMB_W * 2) / max(w, 1))
                    img = bmp.to_pil().convert("RGB")
                    page.close()
                data = img.tobytes("raw", "RGB")
                qimg = QImage(data, img.width, img.height, 3 * img.width, QImage.Format_RGB888).copy()
                self.rendered.emit(self.path, i, qimg)
        finally:
            with core.PDFIUM_LOCK:
                pdf.close()


class ExtractThread(QThread):
    done = Signal(list, str)

    def __init__(self, src, jobs):
        super().__init__()
        self.src, self.jobs = src, jobs  # jobs: list[(out_path, pages)]

    def run(self):
        outs = []
        try:
            for out, pages in self.jobs:
                core.extract_pages(self.src, out, pages)
                outs.append(out)
            self.done.emit(outs, "")
        except Exception as exc:
            self.done.emit(outs, str(exc))


def _placeholder(w: int, h: int) -> QIcon:
    pm = QPixmap(w * 2, h * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor(C["border_strong"]))
    p.setBrush(QColor("#FBFAF8"))
    p.drawRect(1, 1, w * 2 - 3, h * 2 - 3)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def _thumb_icon(img: QImage) -> QIcon:
    """Miniatura com borda fina, para destacar páginas brancas do fundo."""
    pm = QPixmap.fromImage(img)
    framed = QPixmap(pm.width() + 2, pm.height() + 2)
    framed.fill(QColor(C["border_strong"]))
    p = QPainter(framed)
    p.drawPixmap(1, 1, pm)
    p.end()
    framed.setDevicePixelRatio(2)
    ic = QIcon()
    ic.addPixmap(framed, QIcon.Normal)
    ic.addPixmap(framed, QIcon.Selected)  # sem o tom azul do Qt sobre a página selecionada
    return ic


class ExtractPage(QWidget):
    def __init__(self):
        super().__init__()
        self.path: str | None = None
        self.count = 0
        self.thumb_thread: ThumbThread | None = None
        self.threads = []
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        root.addWidget(PageHeader(
            "Extrair páginas",
            "Escolha as páginas clicando nas miniaturas (Ctrl e Shift para várias) ou digitando, "
            "por exemplo: 1, 3-5, 10-fim. O resultado é um PDF novo; o original não muda."))

        self.stack = QStackedWidget()
        self.drop = DropZone("Arraste um PDF para cá", "ou clique para escolher o arquivo", multiple=False)
        self.drop.files_dropped.connect(lambda fs: self.open_pdf(fs[0]))
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.drop)
        el.addStretch(1)
        self.stack.addWidget(empty)

        work = QWidget()
        wl = QHBoxLayout(work)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(10)
        top = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setStyleSheet("font-weight: 600;")
        self.btn_other = QPushButton("Abrir outro PDF…")
        self.btn_other.clicked.connect(self._pick_other)
        top.addWidget(self.file_label, 1)
        top.addWidget(self.btn_other)
        left.addLayout(top)

        self.grid = QListWidget()
        self.grid.setObjectName("pagesGrid")
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(THUMB_W, int(THUMB_W * 1.42)))
        self.grid.setGridSize(QSize(THUMB_W + 34, int(THUMB_W * 1.42) + 40))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setSpacing(4)
        self.grid.itemSelectionChanged.connect(self._selection_changed)
        self.grid.currentItemChanged.connect(lambda cur, _prev: self._preview(cur))
        left.addWidget(self.grid, 1)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        sel_row.addWidget(QLabel("Páginas:"))
        self.field = QLineEdit()
        self.field.setPlaceholderText("ex.: 1, 3-5, 10-fim")
        self.field.textEdited.connect(lambda _t: self.field_timer.start())
        self.field_timer = debounce(self, 450, self._field_changed)
        sel_row.addWidget(self.field, 1)
        for text, fn in (("Todas", self.grid.selectAll), ("Inverter", self._invert),
                         ("Nenhuma", self.grid.clearSelection)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            sel_row.addWidget(b)
        left.addLayout(sel_row)
        self.field_hint = QLabel("")
        self.field_hint.setStyleSheet(f"color: {C['error']}; font-size: 9pt;")
        self.field_hint.hide()
        left.addWidget(self.field_hint)
        wl.addLayout(left, 1)

        side = card()
        side.setFixedWidth(300)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(8)
        sl.addWidget(section_label("Pré-visualização"))
        self.preview = QLabel("Clique em uma página")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(340)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setStyleSheet(f"color: {C['muted']};")
        sl.addWidget(self.preview, 1)
        self.preview_caption = QLabel("")
        self.preview_caption.setAlignment(Qt.AlignCenter)
        self.preview_caption.setStyleSheet(f"color: {C['muted']};")
        sl.addWidget(self.preview_caption)
        sl.addSpacing(8)
        sl.addWidget(section_label("Resultado"))
        self.chk_separate = QCheckBox("Um arquivo para cada página")
        sl.addWidget(self.chk_separate)
        self.sel_summary = QLabel("Nenhuma página selecionada.")
        self.sel_summary.setWordWrap(True)
        self.sel_summary.setStyleSheet(f"color: {C['muted']};")
        sl.addWidget(self.sel_summary)
        self.btn_go = QPushButton("Extrair páginas…")
        self.btn_go.setObjectName("primary")
        self.btn_go.setEnabled(False)
        self.btn_go.clicked.connect(self._extract)
        sl.addWidget(self.btn_go)
        wl.addWidget(side)
        self.stack.addWidget(work)
        root.addWidget(self.stack, 1)

        self.msg = MessageBar()
        root.addWidget(self.msg)

    # --- abrir --------------------------------------------------------------------------
    def _pick_other(self):
        from ui_common import last_dir
        f, _ = QFileDialog.getOpenFileName(self, "Escolher PDF", last_dir(), "PDF (*.pdf)")
        if f:
            remember_dir(f)
            self.open_pdf(f)

    def open_pdf(self, path: str):
        self.msg.hide()
        try:
            count = core.page_count(path)
        except Exception as exc:
            self.msg.show_message("error", core.open_error_message(exc))
            return
        if self.thumb_thread:
            self.thumb_thread.requestInterruption()
            self.thumb_thread.wait(3000)
        self.path, self.count = path, count
        self.file_label.setText(f"{Path(path).name}  ·  {count} página(s)")
        self.file_label.setToolTip(path)
        self.grid.clear()
        ph = _placeholder(THUMB_W, int(THUMB_W * 1.42))
        self.grid.setUpdatesEnabled(False)
        for i in range(count):
            it = QListWidgetItem(ph, str(i + 1))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.grid.addItem(it)
        self.grid.setUpdatesEnabled(True)
        self.field.clear()
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Clique em uma página")
        self.preview_caption.clear()
        self.stack.setCurrentIndex(1)
        th = ThumbThread(path, count)
        th.rendered.connect(self._on_thumb)
        self.thumb_thread = th
        th.start()
        self._selection_changed()

    def _on_thumb(self, path: str, index: int, img: QImage):
        if path != self.path or index >= self.grid.count():
            return
        self.grid.item(index).setIcon(_thumb_icon(img))

    def _preview(self, item):
        if item is None or not self.path:
            return
        idx = self.grid.row(item)
        img = render_page(self.path, idx, 560)
        if img is None:
            return
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(2)
        self.preview.setPixmap(pm)
        self.preview_caption.setText(f"Página {idx + 1} de {self.count}")

    # --- seleção ----------------------------------------------------------------------------
    def selected_pages(self) -> list[int]:
        return sorted(self.grid.row(it) + 1 for it in self.grid.selectedItems())

    def _selection_changed(self):
        pages = self.selected_pages()
        if not self._syncing:
            self.field.setText(core.format_ranges(pages))
            self.field_hint.hide()
        n = len(pages)
        self.btn_go.setEnabled(n > 0)
        self.sel_summary.setText("Nenhuma página selecionada." if n == 0 else
                                 f"{n} página(s) selecionada(s): {core.format_ranges(pages)}")

    def _field_changed(self):
        text = self.field.text().strip()
        if not text:
            self._syncing = True
            self.grid.clearSelection()
            self._syncing = False
            self.field_hint.hide()
            return
        try:
            pages = core.parse_page_selection(text, self.count)
        except ValueError as exc:
            self.field_hint.setText(str(exc))
            self.field_hint.show()
            return
        self.field_hint.hide()
        self._syncing = True
        self.grid.clearSelection()
        for p in pages:
            self.grid.item(p - 1).setSelected(True)
        if pages:
            self.grid.scrollToItem(self.grid.item(pages[0] - 1))
        self._syncing = False
        self._selection_changed()

    def _invert(self):
        self.grid.blockSignals(True)
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setSelected(not it.isSelected())
        self.grid.blockSignals(False)
        self._selection_changed()

    # --- extrair --------------------------------------------------------------------------------
    def _extract(self):
        pages = self.selected_pages()
        if not pages or not self.path:
            return
        src = Path(self.path)
        if self.chk_separate.isChecked():
            folder = QFileDialog.getExistingDirectory(self, "Pasta para salvar as páginas", str(src.parent))
            if not folder:
                return
            jobs = []
            for p in pages:
                out = core.unique_path(Path(folder) / f"{src.stem} - pág. {p}.pdf")
                jobs.append((str(out), [p]))
        else:
            label = core.format_ranges(pages).replace(", ", "_")
            if len(label) > 40:
                label = f"{len(pages)} páginas"
            suggestion = core.unique_path(src.parent / f"{src.stem} - pág. {label}.pdf")
            out, _ = QFileDialog.getSaveFileName(self, "Salvar páginas extraídas", str(suggestion), "PDF (*.pdf)")
            if not out:
                return
            if not out.lower().endswith(".pdf"):
                out += ".pdf"
            if Path(out).exists() and core.same_file(out, src):
                self.msg.show_message("error", "Escolha outro nome: não é possível salvar sobre o arquivo original.")
                return
            jobs = [(out, pages)]
        self.btn_go.setEnabled(False)
        self.btn_go.setText("Extraindo…")
        th = ExtractThread(str(src), jobs)
        th.done.connect(self._on_done)
        th.finished.connect(lambda t=th: self.threads.remove(t) if t in self.threads else None)
        self.threads.append(th)
        th.start()

    def _on_done(self, outs, err):
        self.btn_go.setText("Extrair páginas…")
        self.btn_go.setEnabled(bool(self.selected_pages()))
        if err:
            self.msg.show_message("error", f"Não foi possível extrair: {err}")
        elif len(outs) == 1:
            self.msg.show_message("ok", f"Novo PDF salvo: {Path(outs[0]).name}", outs[0])
        else:
            self.msg.show_message("ok", f"{len(outs)} arquivos salvos, um por página.", outs[0], folder_only=True)

    def shutdown(self):
        if self.thumb_thread:
            self.thumb_thread.requestInterruption()
            self.thumb_thread.wait(3000)
        for th in list(self.threads):
            th.wait(5000)
