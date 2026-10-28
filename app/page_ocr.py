"""Tela 'Reconhecer texto (OCR)'."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import core
from ui_common import (C, DropZone, MessageBar, PageHeader, card, icon, remember_dir,
                       reveal_in_folder, section_label, settings)

# Página com confiança média abaixo disso, ou com muitas palavras de baixa
# confiança, é marcada para revisão. Critério prático, não uma garantia.
REVIEW_CONF = 85.0
REVIEW_LOW_RATIO = 0.10

STAGE_PT = {
    "Scanning contents": "Lendo o conteúdo",
    "OCR": "Reconhecendo texto",
    "Image optimization": "Otimizando imagens",
    "Optimizing images": "Otimizando imagens",
    "Linearizing": "Finalizando",
    "Grafting": "Montando o PDF",
    "PDF/A conversion": "Convertendo",
}

ROLE_PATH = Qt.UserRole


from ocr_runner import OcrRunner, clean_stale_temp, kill_tree, worker_command  # noqa: E402,F401


class AnalyzeThread(QThread):
    analyzed = Signal(str, object)

    def __init__(self, paths: list[str]):
        super().__init__()
        self.paths = paths

    def run(self):
        for p in self.paths:
            if self.isInterruptionRequested():
                return
            self.analyzed.emit(p, core.analyze_pdf(p))


class FileEntry:
    def __init__(self, path: str, item: QTreeWidgetItem):
        self.path = path
        self.item = item
        self.info: core.DocInfo | None = None
        self.state = "analyzing"   # analyzing, ready, nothing, queued, running, done, error, cancelled
        self.result: dict = {}
        self.conf: dict[int, dict] = {}
        self.error = ""
        self.fraction = 0.0

    @property
    def weight(self) -> int:
        return max(1, len(self.info.ocr_pages)) if self.info else 1


class OcrPage(QWidget):
    busy_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.entries: list[FileEntry] = []
        self.queue: list[FileEntry] = []
        self.current: FileEntry | None = None
        self.runner: OcrRunner | None = None
        self.threads: list[AnalyzeThread] = []
        self.stage_text = ""
        self.out_dir: str | None = settings().value("ocr_out_dir", None)
        clean_stale_temp()
        self._build()

    # --- construção da tela -------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        root.addWidget(PageHeader(
            "Reconhecer texto (OCR)",
            "O programa confere cada página antes: páginas que já têm texto selecionável são "
            "mantidas como estão, e só as páginas em imagem passam pelo OCR. O original nunca é alterado."))

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        self.drop = DropZone("Arraste PDFs ou uma pasta para cá",
                             "ou clique para escolher os arquivos", multiple=True, compact=True)
        self.drop.files_dropped.connect(self.add_files)
        left.addWidget(self.drop)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Arquivo", "Páginas", "Análise", "Situação", "Confiança"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 64), (2, 180), (3, 175), (4, 82)):
            h.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, w)
        self.tree.itemSelectionChanged.connect(self._show_details)
        self.tree.itemDoubleClicked.connect(self._open_result)
        split.addWidget(self.tree)

        det = QWidget()
        dl = QVBoxLayout(det)
        dl.setContentsMargins(0, 6, 0, 0)
        dl.setSpacing(6)
        self.details_label = section_label("Detalhes por página")
        dl.addWidget(self.details_label)
        self.details = QTableWidget(0, 5)
        self.details.setHorizontalHeaderLabels(["Página", "Tipo", "Ação", "Confiança", "Observação"])
        self.details.verticalHeader().hide()
        self.details.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.details.setAlternatingRowColors(True)
        dh = self.details.horizontalHeader()
        dh.setSectionResizeMode(4, QHeaderView.Stretch)
        for col, w in ((0, 62), (1, 175), (2, 200), (3, 84)):
            self.details.setColumnWidth(col, w)
        dl.addWidget(self.details)
        split.addWidget(det)
        split.setSizes([300, 220])
        left.addWidget(split, 1)
        body.addLayout(left, 1)
        body.addWidget(self._options_card())
        root.addLayout(body, 1)

        self.msg = MessageBar()
        root.addWidget(self.msg)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        status_col = QVBoxLayout()
        status_col.setSpacing(4)
        self.status = QLabel("Adicione arquivos para começar.")
        self.status.setStyleSheet(f"color: {C['muted']};")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        status_col.addWidget(self.status)
        status_col.addWidget(self.progress)
        bottom.addLayout(status_col, 1)
        self.btn_remove = QPushButton("Remover")
        self.btn_remove.setIcon(icon("trash", C["muted"], 16))
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Limpar lista")
        self.btn_clear.clicked.connect(self.clear)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.hide()
        self.btn_start = QPushButton("Iniciar OCR")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start)
        for b in (self.btn_remove, self.btn_clear, self.btn_cancel, self.btn_start):
            bottom.addWidget(b)
        root.addLayout(bottom)
        self._refresh_buttons()

    def _options_card(self) -> QWidget:
        box = card()
        box.setFixedWidth(300)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        s = settings()

        lay.addWidget(section_label("Idioma do documento"))
        self.lang = QComboBox()
        self.lang.addItem("Português", "por")
        self.lang.addItem("Português + Inglês", "por+eng")
        self.lang.setCurrentIndex(int(s.value("ocr_lang_idx", 0)))
        lay.addWidget(self.lang)

        lay.addSpacing(6)
        lay.addWidget(section_label("Precisão"))
        self.prec_std = QRadioButton("Padrão (recomendado)")
        self.prec_max = QRadioButton("Máxima — bem mais lenta")
        self.prec_max.setToolTip("Usa o modelo de idioma mais preciso do Tesseract e amplia imagens de baixa\n"
                                 "resolução antes do OCR. Indicado para documentos difíceis.")
        grp = QButtonGroup(self)
        grp.addButton(self.prec_std)
        grp.addButton(self.prec_max)
        has_best = core.tessdata_dir(True) is not None
        self.prec_max.setEnabled(has_best)
        (self.prec_max if (has_best and s.value("ocr_max", "false") == "true") else self.prec_std).setChecked(True)
        lay.addWidget(self.prec_std)
        lay.addWidget(self.prec_max)

        lay.addSpacing(6)
        lay.addWidget(section_label("Ajustes"))
        self.chk_deskew = QCheckBox("Endireitar páginas tortas")
        self.chk_deskew.setToolTip("Corrige a inclinação de páginas escaneadas tortas. A rotação de páginas\n"
                                   "de cabeça para baixo ou deitadas é sempre corrigida.")
        self.chk_deskew.setChecked(s.value("ocr_deskew", "true") == "true")
        self.chk_txt = QCheckBox("Salvar também o texto (.txt)")
        self.chk_txt.setChecked(s.value("ocr_txt", "false") == "true")
        self.chk_txt.toggled.connect(lambda _on: self._refresh_buttons())
        self.chk_signed = QCheckBox("Permitir PDF com assinatura digital")
        self.chk_signed.setToolTip("O OCR cria uma cópia; a assinatura digital deixa de valer só na cópia.\n"
                                   "O arquivo original continua intacto e válido.")
        self.chk_signed.setChecked(s.value("ocr_signed", "false") == "true")
        for w in (self.chk_deskew, self.chk_txt, self.chk_signed):
            lay.addWidget(w)

        lay.addSpacing(6)
        lay.addWidget(section_label("Salvar em"))
        self.out_same = QRadioButton("Mesma pasta do original")
        self.out_other = QRadioButton("Outra pasta…")
        g2 = QButtonGroup(self)
        g2.addButton(self.out_same)
        g2.addButton(self.out_other)
        (self.out_other if self.out_dir else self.out_same).setChecked(True)
        self.out_label = QLabel()
        self.out_label.setWordWrap(True)
        self.out_label.setStyleSheet(f"color: {C['muted']}; font-size: 8.5pt;")
        self.out_other.clicked.connect(self._choose_out_dir)
        self.out_same.clicked.connect(self._use_same_dir)
        lay.addWidget(self.out_same)
        lay.addWidget(self.out_other)
        lay.addWidget(self.out_label)
        self._update_out_label()

        lay.addSpacing(6)
        lay.addWidget(section_label("Desempenho"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Páginas em paralelo:"))
        self.jobs = QComboBox()
        cpu = os.cpu_count() or 2
        default_jobs = max(1, cpu // 2)
        for n in range(1, cpu + 1):
            self.jobs.addItem(f"{n} (padrão)" if n == default_jobs else str(n), n)
        saved = int(s.value("ocr_jobs", default_jobs))
        self.jobs.setCurrentIndex(max(0, min(cpu, saved) - 1))
        self.jobs.setToolTip("Quantas páginas são lidas ao mesmo tempo. O padrão usa metade dos\n"
                             "processadores lógicos, para o computador continuar respondendo.")
        row.addWidget(self.jobs)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        note = QLabel("O nome do arquivo novo termina em “- OCR”. "
                      "Páginas com baixa confiança são marcadas para revisão.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C['muted']}; font-size: 8.5pt;")
        lay.addWidget(note)
        return box

    def _choose_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta para salvar os arquivos com OCR",
                                             self.out_dir or str(Path.home() / "Documents"))
        if d:
            self.out_dir = d
            settings().setValue("ocr_out_dir", d)
        elif not self.out_dir:
            self.out_same.setChecked(True)
        self._update_out_label()

    def _use_same_dir(self):
        self.out_dir = None
        settings().remove("ocr_out_dir")
        self._update_out_label()

    def _update_out_label(self):
        self.out_label.setText(self.out_dir if (self.out_other.isChecked() and self.out_dir) else "")
        self.out_label.setVisible(bool(self.out_label.text()))

    def _save_options(self):
        s = settings()
        s.setValue("ocr_lang_idx", self.lang.currentIndex())
        s.setValue("ocr_max", "true" if self.prec_max.isChecked() else "false")
        s.setValue("ocr_deskew", "true" if self.chk_deskew.isChecked() else "false")
        s.setValue("ocr_txt", "true" if self.chk_txt.isChecked() else "false")
        s.setValue("ocr_signed", "true" if self.chk_signed.isChecked() else "false")
        s.setValue("ocr_jobs", self.jobs.currentData())

    # --- lista de arquivos -----------------------------------------------------------
    def add_files(self, paths: list[str]):
        known = {os.path.normcase(os.path.abspath(e.path)) for e in self.entries}
        new = []
        for p in paths:
            key = os.path.normcase(os.path.abspath(p))
            if key in known:
                continue
            known.add(key)
            item = QTreeWidgetItem([Path(p).name, "…", "Analisando…", "", ""])
            item.setToolTip(0, p)
            item.setIcon(0, icon("file", C["muted"], 16))
            item.setData(0, ROLE_PATH, p)
            for col in (1, 4):
                item.setTextAlignment(col, Qt.AlignCenter)
            self.tree.addTopLevelItem(item)
            e = FileEntry(p, item)
            self.entries.append(e)
            new.append(p)
        if new:
            remember_dir(new[0])
            th = AnalyzeThread(new)
            th.analyzed.connect(self._on_analyzed)
            th.finished.connect(lambda t=th: self.threads.remove(t) if t in self.threads else None)
            self.threads.append(th)
            th.start()
            if self.tree.currentItem() is None:
                self.tree.setCurrentItem(self.entries[-len(new)].item)
        self._refresh_buttons()

    def _entry(self, path: str) -> FileEntry | None:
        for e in self.entries:
            if e.path == path:
                return e
        return None

    def _on_analyzed(self, path: str, info: core.DocInfo):
        e = self._entry(path)
        if e is None:
            return
        e.info = info
        it = e.item
        if info.error:
            e.state, e.error = "error", info.error
            it.setText(1, "—")
            it.setText(2, "Não foi possível ler")
            self._set_state(e, "Erro", C["error"], info.error)
        else:
            it.setText(1, str(info.page_count))
            n_ocr = len(info.ocr_pages)
            n_text = info.page_count - n_ocr
            if n_ocr == 0:
                it.setText(2, "Todas com texto")
                e.state = "nothing"
                self._set_state(e, "OCR desnecessário", C["ok"])
            elif n_text == 0:
                it.setText(2, f"{n_ocr} em imagem")
                e.state = "ready"
                self._set_state(e, "Pronto", C["muted"])
            else:
                it.setText(2, f"{n_text} com texto · {n_ocr} em imagem")
                e.state = "ready"
                self._set_state(e, "Pronto", C["muted"])
        if self.tree.currentItem() is it:
            self._show_details()
        self._refresh_buttons()

    def _set_state(self, e: FileEntry, text: str, color: str, tooltip: str = ""):
        from PySide6.QtGui import QBrush, QColor
        e.item.setText(3, text)
        e.item.setForeground(3, QBrush(QColor(color)))
        e.item.setToolTip(3, tooltip or text)

    def remove_selected(self):
        for it in self.tree.selectedItems():
            e = self._entry(it.data(0, ROLE_PATH))
            if e and e.state not in ("running", "queued"):
                self.entries.remove(e)
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))
        self._show_details()
        self._refresh_buttons()

    def clear(self):
        if self.current:
            return
        self.entries.clear()
        self.tree.clear()
        self.details.setRowCount(0)
        self.msg.hide()
        self.progress.setValue(0)
        self.status.setText("Adicione arquivos para começar.")
        self._refresh_buttons()

    def _can_run(self, e: FileEntry) -> bool:
        """Prontos, cancelados e com erro de OCR (ex.: PDF assinado) podem ser processados de novo."""
        if e.state in ("ready", "cancelled"):
            return True
        if e.state == "error":
            return e.info is not None and not e.info.error
        return e.state == "nothing" and self.chk_txt.isChecked()

    def _refresh_buttons(self):
        running = self.current is not None
        pending = [e for e in self.entries if self._can_run(e)]
        self.btn_start.setEnabled(not running and bool(pending))
        self.btn_start.setVisible(not running)
        self.btn_cancel.setVisible(running)
        self.btn_clear.setEnabled(not running and bool(self.entries))
        self.btn_remove.setEnabled(not running and bool(self.entries))
        self.drop.setEnabled(not running)
        for w in (self.lang, self.prec_std, self.prec_max, self.chk_deskew, self.chk_txt,
                  self.chk_signed, self.out_same, self.out_other, self.jobs):
            w.setEnabled(not running and (w is not self.prec_max or core.tessdata_dir(True) is not None))
        if not running and self.entries and not self.msg.isVisible():
            analyzing = any(e.state == "analyzing" for e in self.entries)
            if analyzing:
                self.status.setText("Analisando as páginas…")
            elif pending:
                n = sum(len(e.info.ocr_pages) for e in pending if e.info)
                self.status.setText(f"{len(pending)} arquivo(s) para processar · {n} página(s) em imagem.")
            else:
                self.status.setText("Nada a processar.")

    # --- detalhes por página -------------------------------------------------------------
    def _show_details(self):
        items = self.tree.selectedItems()
        self.details.setRowCount(0)
        if len(items) != 1:
            self.details_label.setText("DETALHES POR PÁGINA")
            return
        e = self._entry(items[0].data(0, ROLE_PATH))
        if e is None or e.info is None or e.info.error:
            return
        self.details_label.setText(f"DETALHES POR PÁGINA — {Path(e.path).name.upper()}")
        from PySide6.QtGui import QBrush, QColor
        still_empty = set(e.result.get("still_empty", []))
        done = e.state == "done"
        self.details.setRowCount(e.info.page_count)
        for r, p in enumerate(e.info.pages):
            if p.needs_ocr:
                action = "OCR" if p.kind == core.KIND_SCANNED and p.chars == 0 else "OCR (mantém o texto digital)"
            else:
                action = "Mantida (já tem texto)"
            conf = e.conf.get(p.number)
            conf_txt, note, color = "—", "", None
            if conf and conf.get("conf") is not None:
                conf_txt = f"{conf['conf']:.0f}%"
                words = conf.get("words") or 0
                low = conf.get("low_words") or 0
                if conf["conf"] < REVIEW_CONF or (words and low / words > REVIEW_LOW_RATIO):
                    note, color = f"Revisar: {low} de {words} palavras com baixa confiança", C["warn"]
            if done and p.number in still_empty:
                note, color = "Nenhum texto encontrado (página em branco ou só imagem?)", C["warn"]
            elif done and p.needs_ocr and not note:
                note = "Concluída"
            vals = [str(p.number), core.KIND_LABELS[p.kind], action, conf_txt, note]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 3):
                    cell.setTextAlignment(Qt.AlignCenter)
                if color and c == 4:
                    cell.setForeground(QBrush(QColor(color)))
                self.details.setItem(r, c, cell)

    # --- execução -------------------------------------------------------------------------------
    def _job_for(self, e: FileEntry) -> dict:
        src = Path(e.path)
        folder = Path(self.out_dir) if (self.out_other.isChecked() and self.out_dir) else src.parent
        out = core.unique_path(folder / f"{src.stem} - OCR.pdf")
        return {
            "input": str(src),
            "output": str(out),
            "language": self.lang.currentData(),
            "max_precision": self.prec_max.isChecked(),
            "deskew": self.chk_deskew.isChecked(),
            "save_txt": self.chk_txt.isChecked(),
            "allow_signed": self.chk_signed.isChecked(),
            "jobs": self.jobs.currentData(),
        }

    def start(self):
        if core.find_tesseract() is None:
            QMessageBox.warning(self, "Tesseract não encontrado",
                                "O motor de OCR (Tesseract) não foi encontrado neste computador.\n\n"
                                "Reinstale o Prumo PDF para que ele seja instalado de novo.")
            return
        self._save_options()
        self.msg.hide()
        self.queue = [e for e in self.entries if self._can_run(e)]
        if not self.queue:
            return
        for e in self.queue:
            e.state, e.fraction, e.conf, e.result = "queued", 0.0, {}, {}
            self._set_state(e, "Na fila", C["muted"])
        self.total_weight = sum(e.weight for e in self.queue)
        self.done_weight = 0
        self.batch = list(self.queue)
        self.t_start = time.time()
        self.busy_changed.emit(True)
        self._next()

    def _next(self):
        if not self.queue:
            self._finish_batch()
            return
        e = self.queue.pop(0)
        self.current = e
        e.state = "running"
        self._set_state(e, "Processando…", C["accent"])
        self.tree.setCurrentItem(e.item)
        self.runner = OcrRunner(self._job_for(e), self)
        self.runner.event.connect(self._on_event)
        self.runner.finished.connect(self._on_finished)
        self.runner.start()
        self._refresh_buttons()
        self._update_progress()

    def _on_event(self, ev: dict):
        e = self.current
        if e is None:
            return
        t = ev.get("type")
        if t == "stage":
            desc = ev.get("desc", "")
            self.stage_text = STAGE_PT.get(desc, desc)
        elif t == "progress":
            if ev.get("desc") == "OCR" and ev.get("total"):
                e.fraction = min(1.0, float(ev.get("done", 0)) / float(ev["total"]))
                self._set_state(e, f"Reconhecendo… {int(e.fraction * 100)}%", C["accent"])
        elif t == "page_conf" and ev.get("page"):
            e.conf[int(ev["page"])] = ev
            if self.tree.currentItem() is e.item:
                self._show_details()
        elif t == "done":
            e.result = ev
        elif t == "error":
            e.error = ev.get("message", "Erro desconhecido")
        self._update_progress()

    def _on_finished(self, code: int):
        e = self.current
        self.current = None
        if e is None:
            return
        if e.state == "cancelled":
            pass
        elif e.result.get("type") == "done":
            e.state = "done"
            confs = [c["conf"] for c in e.conf.values() if c.get("conf") is not None]
            if confs:
                e.item.setText(4, f"{min(confs):.0f}%" if len(confs) == 1 else f"mín. {min(confs):.0f}%")
            if e.result.get("status") == "nothing_to_do":
                self._set_state(e, "Texto salvo (.txt)" if e.result.get("txt") else "OCR desnecessário", C["ok"])
            else:
                review = self._pages_to_review(e)
                if review:
                    self._set_state(e, f"Concluído · revisar {len(review)} pág.", C["warn"],
                                    "Páginas para revisar: " + core.format_ranges(review))
                else:
                    self._set_state(e, "Concluído", C["ok"], e.result.get("output", ""))
        else:
            e.state = "error"
            msg = e.error or f"O processo de OCR terminou com erro (código {code})."
            self._set_state(e, "Erro", C["error"], msg)
        self.done_weight += e.weight
        e.fraction = 0.0
        if self.tree.currentItem() is e.item:
            self._show_details()
        if self.runner:
            self.runner.deleteLater()
            self.runner = None
        if e.state == "cancelled":
            self._finish_batch(cancelled=True)
        else:
            self._next()

    def _pages_to_review(self, e: FileEntry) -> list[int]:
        out = set(e.result.get("still_empty", []))
        for page, c in e.conf.items():
            if c.get("conf") is None:
                continue
            words = c.get("words") or 0
            low = c.get("low_words") or 0
            if c["conf"] < REVIEW_CONF or (words and low / words > REVIEW_LOW_RATIO):
                out.add(page)
        return sorted(out)

    def _update_progress(self):
        if not self.current and not self.queue:
            return
        cur = self.current.weight * self.current.fraction if self.current else 0
        frac = (self.done_weight + cur) / max(1, self.total_weight)
        self.progress.setValue(int(frac * 1000))
        idx = len(self.batch) - len(self.queue)
        name = Path(self.current.path).name if self.current else ""
        self.status.setText(f"Arquivo {idx} de {len(self.batch)} · {name} · {self.stage_text or 'Iniciando'}")

    def _finish_batch(self, cancelled: bool = False):
        self.current = None
        self.queue = []
        self.busy_changed.emit(False)
        self.progress.setValue(0 if cancelled else 1000)
        secs = time.time() - getattr(self, "t_start", time.time())
        batch = getattr(self, "batch", [])
        ok = [e for e in batch if e.state == "done"]
        err = [e for e in batch if e.state == "error"]
        review = sum(len(self._pages_to_review(e)) for e in ok)
        outputs = [e.result.get("output") for e in ok if e.result.get("output")]
        tempo = f"{secs:.0f} s" if secs < 90 else f"{secs / 60:.1f} min".replace(".", ",")
        if cancelled:
            self.status.setText("OCR cancelado.")
            self.msg.show_message("warn", "OCR cancelado. O arquivo em andamento não foi salvo; "
                                          "os já concluídos continuam salvos.")
        elif err:
            self.status.setText(f"Concluído com erros em {tempo}.")
            first = err[0]
            self.msg.show_message("error", f"{len(ok)} arquivo(s) concluído(s), {len(err)} com erro. "
                                           f"{Path(first.path).name}: {first.error}")
        else:
            self.status.setText(f"Concluído em {tempo}.")
            extra = (f" {review} página(s) com baixa confiança foram marcadas para revisão — "
                     "selecione o arquivo para ver quais.") if review else ""
            if len(outputs) == 1:
                self.msg.show_message("warn" if review else "ok",
                                      f"Arquivo salvo: {Path(outputs[0]).name}.{extra}", outputs[0])
            elif outputs:
                self.msg.show_message("warn" if review else "ok",
                                      f"{len(outputs)} arquivos salvos.{extra}", outputs[0], folder_only=True)
            else:
                self.msg.show_message("ok", "Nenhum arquivo precisou de OCR: todas as páginas já tinham texto.")
        self._refresh_buttons()

    def cancel(self):
        if self.current and self.runner:
            self.current.state = "cancelled"
            self._set_state(self.current, "Cancelado", C["muted"])
            for e in self.queue:
                e.state = "ready"
                self._set_state(e, "Pronto", C["muted"])
            self.queue = []
            self.runner.cancel()

    def is_busy(self) -> bool:
        return self.current is not None

    def shutdown(self):
        for th in list(self.threads):
            th.requestInterruption()
            th.wait(2000)
        if self.runner:
            self.cancel()

    def _open_result(self, item, _col):
        e = self._entry(item.data(0, ROLE_PATH))
        if e and e.result.get("output"):
            reveal_in_folder(e.result["output"])
