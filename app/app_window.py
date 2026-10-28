"""Janela principal: navegação entre telas (como no iPhone), avisos, OCR e preferências."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QMimeData, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QStackedWidget

import core
from ios_kit import JobBanner, Toast, alert
from ios_theme import T, app_icon
from library import Library, default_root
from pdfops import UserError
from services import JobCenter, LibraryHub


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, library: Library | None = None):
        super().__init__()
        self.settings = settings or QSettings("Prumo", "PrumoPDF")
        self.setWindowTitle(core.APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(420, 600)
        self.setAcceptDrops(True)
        if library is None:
            library = Library(self.setting("library_root", "") or str(default_root()))
        self.hub = LibraryHub(library)
        self.jobs = JobCenter(self.hub, self.setting)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        from screens import Actions, HomeScreen
        self.actions = Actions(self)
        self.toast_w = Toast(self)
        self.banner = JobBanner(self)
        self.banner.cancel_requested.connect(self._cancel_ocr)
        self.hub.changed.connect(self._library_changed)
        self.jobs.progress.connect(self._job_progress)
        self.jobs.finished.connect(self._job_finished)
        T.changed.connect(self._theme_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(400)
        self._reload_timer.timeout.connect(lambda: self.lib.reload())
        QShortcut(QKeySequence("Alt+Left"), self, self.back)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, self._backspace)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+O"), self, lambda: self.import_dialog(self._drop_folder()))
        QShortcut(QKeySequence("F5"), self, lambda: self.lib.reload())
        self.push(HomeScreen(self))
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 780)

    # --- preferências ---
    def setting(self, key, default=None):
        v = self.settings.value(key, default)
        if isinstance(default, bool) and isinstance(v, str):
            return v.lower() == "true"
        return v

    def set_setting(self, key, value):
        self.settings.setValue(key, value)

    def set_appearance(self, mode):
        self.set_setting("appearance", mode)
        T.set_mode(mode)

    @property
    def lib(self) -> Library:
        return self.hub.lib

    # --- navegação ---
    def current(self):
        return self.stack.currentWidget()

    def push(self, screen):
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)
        screen.on_shown()

    def back(self):
        if self.stack.count() <= 1 or self._overlay_open():
            return
        top = self.stack.currentWidget()
        self.stack.removeWidget(top)
        top.deleteLater()
        self.current().on_shown()

    def _backspace(self):
        from PySide6.QtWidgets import QLineEdit
        if not isinstance(QApplication.focusWidget(), QLineEdit):
            self.back()

    def _overlay_open(self) -> bool:
        from ios_kit import _Overlay
        return any(isinstance(c, _Overlay) and c.isVisible() for c in self.children())

    def _focus_search(self):
        s = getattr(self.current(), "search", None)
        if s is not None:
            s.edit.setFocus()
            s.edit.selectAll()

    def home(self):
        while self.stack.count() > 1:
            self.back()

    def open_document(self, item_id: str):
        from screens import DocumentScreen
        if self.lib.item(item_id) is not None:
            self.push(DocumentScreen(self, item_id))

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:
            self.back()
        else:
            super().mousePressEvent(e)

    # --- avisos ---
    def toast(self, text, action=None, callback=None):
        self.toast_w.show_message(text, action, callback)
        self._place_bottom()

    def show_error(self, message: str):
        alert(self, "Não foi possível concluir", message, [("OK", "default")])

    def attempt(self, fn, busy: str | None = None) -> bool:
        """Executa uma ação e mostra o erro em português, se houver."""
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            fn()
            return True
        except UserError as exc:
            self._restore_cursor(busy)
            self.show_error(str(exc))
        except PermissionError:
            self._restore_cursor(busy)
            self.show_error("O Windows não permitiu a operação. O arquivo pode estar aberto em outro programa "
                            "(feche o leitor de PDF e tente de novo).")
        except OSError as exc:
            self._restore_cursor(busy)
            self.show_error(f"Erro ao acessar o arquivo: {exc.strerror or exc}")
        except Exception as exc:  # noqa: BLE001 - mostra qualquer erro em vez de fechar o app
            self._restore_cursor(busy)
            self.show_error(f"{type(exc).__name__}: {exc}")
        finally:
            self._restore_cursor(busy)
        return False

    @staticmethod
    def _restore_cursor(busy):
        if busy and QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def coming_soon(self, what: str):
        self.toast(f"“{what}” chega na próxima etapa da versão para Windows.")

    # --- arquivos ---
    def reveal(self, path):
        from ui_common import reveal_in_folder
        reveal_in_folder(str(path))

    def open_external(self, item):
        self.lib.mark_opened(item)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.path)))

    def read(self, item):
        # O leitor próprio (com modo leitor) vem na fase 4; por enquanto abre no leitor do Windows.
        self.open_external(item)

    def copy_files(self, paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        QGuiApplication.clipboard().setMimeData(mime)

    def export_copies(self, items):
        start = self.setting("export_dir", str(Path.home() / "Desktop"))
        if len(items) == 1:
            dest, _ = QFileDialog.getSaveFileName(self, "Exportar cópia", str(Path(start) / f"{items[0].name}.pdf"),
                                                  "PDF (*.pdf)")
            if not dest:
                return
            if self.attempt(lambda: shutil.copy2(items[0].path, dest)):
                self.set_setting("export_dir", str(Path(dest).parent))
                self.toast("Cópia exportada.", "Mostrar", lambda: self.reveal(dest))
        else:
            folder = QFileDialog.getExistingDirectory(self, "Exportar cópias para", start)
            if not folder:
                return

            def run():
                for it in items:
                    target = core.unique_path(Path(folder) / f"{it.name}.pdf")
                    shutil.copy2(it.path, target)
            if self.attempt(run):
                self.set_setting("export_dir", folder)
                self.toast(f"{len(items)} cópias exportadas.", "Mostrar", lambda: self.reveal(folder))

    def import_dialog(self, folder: str = ""):
        start = self.setting("import_dir", str(Path.home() / "Documents"))
        files, _ = QFileDialog.getOpenFileNames(self, "Importar PDFs", start, "PDF (*.pdf)")
        if files:
            self.set_setting("import_dir", str(Path(files[0]).parent))
            self.import_paths(files, folder)

    def import_paths(self, paths, folder: str = ""):
        pdfs = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                pdfs.extend(sorted(p.glob("*.pdf")))
            elif p.suffix.lower() == ".pdf":
                pdfs.append(p)
        if not pdfs:
            self.toast("Nenhum PDF para importar.")
            return
        root = self.lib.root.resolve()
        inside = [p for p in pdfs if root in p.resolve().parents]
        if inside and len(inside) == len(pdfs):
            self.toast("Esses PDFs já estão na biblioteca.")
            return
        res = {}
        if self.attempt(lambda: res.setdefault("items", self.lib.import_files(pdfs, folder)), busy="Importando…"):
            items = res["items"]
            if len(items) == 1:
                self.toast(f"PDF importado: {items[0].name}", "Abrir", lambda: self.open_document(items[0].id))
            elif items:
                self.toast(f"{len(items)} PDFs importados.")

    def _drop_folder(self) -> str:
        f = getattr(self.current(), "drop_folder", None)
        return f() if f else ""

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") or os.path.isdir(u.toLocalFile())
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        self.import_paths(paths, self._drop_folder())

    def scan(self):
        alert(self, "Escanear",
              "O escaneamento pela câmera ou pela webcam chega na etapa 3 da versão para Windows. "
              "Por enquanto, use Importar ou arraste os PDFs para a janela.", [("OK", "default")])

    def change_library(self):
        new = QFileDialog.getExistingDirectory(self, "Escolher a pasta da biblioteca", str(self.lib.root.parent))
        if not new:
            return
        new_root = Path(new)
        if new_root.name != "Prumo PDF" and any(new_root.iterdir()):
            new_root = new_root / "Prumo PDF"
        old = self.lib.root
        if new_root.resolve() == old.resolve():
            return
        if self.jobs.is_busy():
            self.show_error("Espere o OCR terminar antes de mudar a pasta da biblioteca.")
            return
        idx = alert(self, "Mudar a pasta da biblioteca",
                    f"Nova pasta: {new_root}\n\nMover os PDFs atuais para lá? Se escolher “Não mover”, "
                    "os PDFs continuam na pasta antiga e a biblioteca passa a mostrar a nova.",
                    [("Mover os PDFs", "default"), ("Não mover", "cancel"), ("Cancelar", "cancel")])
        if idx is None or idx == 2:
            return

        def run():
            new_root.mkdir(parents=True, exist_ok=True)
            if idx == 0:
                for entry in list(old.iterdir()):
                    target = new_root / entry.name
                    if target.exists():
                        if entry.is_dir() and entry.name == ".prumo":
                            continue
                        raise UserError(f"Já existe “{entry.name}” na nova pasta. Nada foi movido depois dele.")
                    shutil.move(str(entry), str(target))
        if not self.attempt(run, busy="Movendo…"):
            return
        self.set_setting("library_root", str(new_root))
        self._swap_library(str(new_root))
        self.toast("Pasta da biblioteca alterada.")

    def _swap_library(self, root: str):
        from screens import HomeScreen, SettingsScreen
        self.hub.shutdown()
        self.hub.changed.disconnect(self._library_changed)
        self.hub = LibraryHub(Library(root))
        self.hub.changed.connect(self._library_changed)
        self.jobs.hub = self.hub
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.push(HomeScreen(self))
        self.push(SettingsScreen(self))

    # --- OCR ---
    def start_ocr(self, item, quiet=False, allow_signed=False):
        if self.jobs.start(item, allow_signed):
            if not quiet and self.jobs.is_busy() and self.jobs.current and self.jobs.current.item_id != item.id:
                self.toast(f"“{item.name}” entrou na fila do OCR.")
        elif not quiet:
            self.toast("O OCR deste PDF já está em andamento.")
        self.current().refresh()

    def _cancel_ocr(self):
        idx = alert(self, "Cancelar o OCR?", "O arquivo original não muda.",
                    [("Continuar", "cancel"), ("Cancelar OCR", "destructive")])
        if idx == 1:
            self.jobs.cancel_all()

    def _job_progress(self):
        job = self.jobs.current
        if job is None:
            self.banner.hide()
        else:
            self.banner.update_job(job.name, job.stage, job.fraction, len(self.jobs.queue))
        self._place_bottom()

    def _job_finished(self, item_id, status, data):
        item = self.lib.item(item_id)
        name = item.name if item else "PDF"
        if status == "ok":
            result = self.lib.item(data["result_id"])
            review = data.get("review") or []
            msg = f"OCR concluído: {result.name if result else name}"
            if review:
                from pdfops import format_ranges
                msg += f". Revise as páginas {format_ranges(review)}."
            self.toast(msg, "Abrir", (lambda: self.open_document(result.id)) if result else None)
        elif status == "nothing":
            self.toast(f"“{name}”: todas as páginas já têm texto. O OCR não foi necessário.")
        elif status == "signed" and item is not None:
            idx = alert(self, "PDF com assinatura digital",
                        "Fazer OCR cria uma cópia sem a assinatura digital. O arquivo original continua "
                        "assinado e válido. Fazer o OCR mesmo assim?",
                        [("Cancelar", "cancel"), ("Fazer OCR", "default")])
            if idx == 1:
                self.start_ocr(item, allow_signed=True)
        elif status == "error":
            alert(self, f"OCR de “{name}” não concluído", str(data), [("OK", "default")])
        cur = self.current()
        if cur is not None:
            cur.refresh()

    # --- eventos ---
    def _library_changed(self):
        cur = self.current()
        if cur is not None:
            cur.refresh()

    def _theme_changed(self):
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if hasattr(w, "refresh") and w is self.current():
                w.refresh()
            w.update()
        self._job_progress()

    def _place_bottom(self):
        self.banner.reposition() if self.banner.isVisible() else None
        offset = self.banner.height() + 10 if self.banner.isVisible() else 0
        if self.toast_w.isVisible():
            self.toast_w.reposition(offset)
            self.toast_w.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_bottom()

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            # Volta para o Prumo: confere se algo mudou na pasta pelo Explorador.
            self._reload_timer.start()
        super().changeEvent(e)

    def closeEvent(self, e):
        if self.jobs.is_busy():
            idx = alert(self, "OCR em andamento", "Fechar o Prumo PDF cancela o OCR. O arquivo original não muda.",
                        [("Continuar", "cancel"), ("Fechar", "destructive")])
            if idx != 1:
                e.ignore()
                return
            self.jobs.cancel_all()
        self.hub.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()
