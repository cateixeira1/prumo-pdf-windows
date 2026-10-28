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

    def back(self, force=False):
        if self.stack.count() <= 1 or self._overlay_open():
            return
        top = self.stack.currentWidget()
        if not force and hasattr(top, "can_leave") and not top.can_leave():
            return
        if hasattr(top, "closing"):
            top.closing()
        self.stack.removeWidget(top)
        top.deleteLater()
        self.current().on_shown()

    def replace_top(self, screen):
        """Troca a tela de cima por outra (ex.: leitor do original ↔ leitor da cópia com OCR)."""
        top = self.stack.currentWidget()
        if hasattr(top, "closing"):
            top.closing()
        self.stack.removeWidget(top)
        top.deleteLater()
        self.push(screen)

    def _backspace(self):
        from PySide6.QtWidgets import QLineEdit
        if not isinstance(QApplication.focusWidget(), QLineEdit):
            self.back()

    def _overlay_open(self) -> bool:
        from ios_kit import _Overlay
        return any(isinstance(c, _Overlay) and c.isVisible() for c in self.children())

    def _focus_search(self):
        if hasattr(self.current(), "open_search"):   # leitor: abre a barra de busca do documento
            self.current().open_search()
            return
        s = getattr(self.current(), "search", None)
        if s is not None:
            s.edit.setFocus()
            s.edit.selectAll()

    def home(self):
        while self.stack.count() > 1:
            before = self.stack.count()
            self.back()
            if self.stack.count() == before:   # a tela pediu para ficar (ex.: edição não salva)
                break

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
        """Leitor do próprio Prumo. Se houver as duas versões, pergunta qual ler (como no iPhone)."""
        from ios_kit import action_sheet
        from reader import ReaderScreen
        from reader import TextReaderScreen
        lib = self.lib
        ocr = lib.ocr_copy(item)
        if ocr is not None and not item.meta.is_ocr_result:
            idx = action_sheet(self, "Como você quer ler?",
                               "O modo leitor mostra o texto reconhecido pelo OCR em parágrafos, como uma nota. "
                               "Dá para alternar entre os modos a qualquer momento, no alto do leitor.",
                               [("Como foi escaneado", "default", "docs"), ("Com OCR (página com texto)", "default", "textscan"),
                                ("Modo leitor (só o texto)", "default", "text")])
            if idx is None:
                return
            if idx == 2:
                self.push(TextReaderScreen(self, ocr.id))
                return
            item = ocr if idx == 1 else item
        self.push(ReaderScreen(self, item.id))

    def organize(self, item):
        from organize import OrganizeScreen
        if self.jobs.is_busy(item.id):
            self.toast("Espere o OCR deste PDF terminar para organizar as páginas.")
            return
        self.push(OrganizeScreen(self, item.id))

    def pick_and_import(self, folder: str = "", multiple: bool = True):
        """Escolhe PDFs no Windows, copia para a biblioteca e devolve os itens."""
        import convert
        start = self.setting("import_dir", str(Path.home() / "Documents"))
        if multiple:
            files, _ = QFileDialog.getOpenFileNames(self, "Escolher PDFs no computador", start, convert.dialog_filter())
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Escolher PDF no computador", start, convert.dialog_filter())
            files = [f] if f else []
        if not files:
            return []
        self.set_setting("import_dir", str(Path(files[0]).parent))
        converted = []
        others = [f for f in files if convert.is_convertible(f)]
        if others:
            converted = self.convert_files(others, folder, offer_ocr=False)
            files = [f for f in files if f not in others]
        root = self.lib.root.resolve()
        inside, outside = [], []
        for f in files:
            (inside if root in Path(f).resolve().parents else outside).append(f)
        items = []
        for f in inside:   # já está na biblioteca: usa o próprio arquivo
            it = self.lib.item_by_path(self.lib.rel_of(Path(f).resolve()))
            if it:
                items.append(it)
        res = {}
        if outside and self.attempt(lambda: res.setdefault("items", self.lib.import_files(outside, folder)),
                                    busy="Importando…"):
            items.extend(res["items"])
        return items + converted

    # --- converter outros arquivos em PDF ---
    def convert_dialog(self, folder: str = ""):
        import convert
        start = self.setting("import_dir", str(Path.home() / "Documents"))
        flt = convert.dialog_filter().replace("PDF e arquivos para converter", "Arquivos para converter", 1)
        files, _ = QFileDialog.getOpenFileNames(self, "Converter em PDF", start, flt)
        if not files:
            return []
        self.set_setting("import_dir", str(Path(files[0]).parent))
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        if pdfs:
            self.import_paths(pdfs, folder)
        return self.convert_files([f for f in files if not f.lower().endswith(".pdf")], folder)

    def run_with_progress(self, title: str, fn):
        """Roda `fn(progress)` numa linha separada, com o aviso "Convertendo…" na tela."""
        import threading

        from PySide6.QtCore import QEventLoop
        from ios_kit import BusyOverlay

        ov = BusyOverlay(self, title)
        state = {"done": False, "result": None, "error": None, "p": (0, 0, "")}

        def progress(i, total, name):
            state["p"] = (i - 1, total, name)

        def work():
            try:
                state["result"] = fn(progress)
            except BaseException as exc:  # noqa: BLE001
                state["error"] = exc
            finally:
                state["done"] = True

        ov._place()
        ov.show()
        ov.raise_()
        t = threading.Thread(target=work, daemon=True)
        t.start()
        while not state["done"]:
            i, total, name = state["p"]
            ov.set_progress(i, total, f"{i + 1} de {total}: {name}" if total > 1 else name)
            loop = QEventLoop()
            QTimer.singleShot(60, loop.quit)
            loop.exec()
        self.removeEventFilter(ov)
        ov.hide()
        ov.deleteLater()
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    def convert_files(self, paths, folder: str = "", offer_ocr: bool = True) -> list:
        """Converte arquivos em PDF e guarda na biblioteca (na pasta `folder`). Devolve os novos itens."""
        import time as _time

        import convert
        paths = [Path(p) for p in paths if convert.is_convertible(p)]
        if not paths:
            return []
        images = [p for p in paths if convert.kind(p) == "image"]
        combine, name = False, None
        if len(images) > 1:
            idx = alert(self, f"{len(images)} imagens",
                        "Juntar todas num PDF só (uma imagem por página, na ordem escolhida) ou criar um PDF "
                        "para cada imagem?",
                        [("Um PDF só", "default"), ("Um PDF para cada", "default"), ("Cancelar", "cancel")])
            if idx is None or idx == 2:
                return []
            combine = idx == 0
            if combine:
                default = _time.strftime("Imagens %d-%m-%Y %Hh%M")
                ans, text = alert(self, "Nome do PDF", "", [("Cancelar", "cancel"), ("Criar", "default")],
                                  text=default, placeholder="Nome")
                if ans != 1:
                    return []
                name = text.strip() or default
        title = "Convertendo em PDF…"
        try:
            res = self.run_with_progress(title, lambda progress: convert.convert(
                paths, combine_images=combine, combined_name=name, work_dir=self.lib.temp_path().with_suffix(""),
                progress=progress, dewarp_photos=bool(self.setting("dewarp_photos", False))))
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"{type(exc).__name__}: {exc}")
            return []
        items, image_items = [], []
        for tmp, nm, k in zip(res.created, res.names, res.kinds):
            try:
                it = self.lib.adopt(tmp, nm, folder)
            except Exception as exc:  # noqa: BLE001
                res.failed.append((nm, str(exc)))
                continue
            items.append(it)
            if k == "images":
                image_items.append(it)
        if res.failed:
            lines = "\n".join(f"• {n}: {m}" for n, m in res.failed[:6])
            more = f"\n… e mais {len(res.failed) - 6}." if len(res.failed) > 6 else ""
            alert(self, "Alguns arquivos não foram convertidos" if items else "Não foi possível converter",
                  lines + more, [("OK", "default")])
        if not items:
            return []
        msg = (f"PDF criado: {items[0].name}" if len(items) == 1 else f"{len(items)} PDFs criados")
        if res.simplified:
            msg += ". Sem o Word instalado, a conversão foi simplificada: o layout pode mudar."
        if offer_ocr and image_items:
            idx = alert(self, "Usar OCR agora?",
                        "Fotos e imagens viram páginas sem texto selecionável. O OCR cria um novo PDF com o texto "
                        "pesquisável, com “OCR” no nome. O PDF da imagem continua salvo.",
                        [("Mais tarde", "cancel"), ("Sim", "default")])
            for it in image_items:
                if idx == 1:
                    self.start_ocr(it, quiet=True)
                else:
                    self.lib.set_pending_ocr(it, True)
        first = items[0]
        self.toast(msg, "Abrir" if len(items) == 1 else None,
                   (lambda: self.open_document(first.id)) if len(items) == 1 else None)
        return items

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
        import convert
        start = self.setting("import_dir", str(Path.home() / "Documents"))
        files, _ = QFileDialog.getOpenFileNames(self, "Importar PDFs (ou arquivos para converter)", start,
                                                convert.dialog_filter())
        if files:
            self.set_setting("import_dir", str(Path(files[0]).parent))
            self.import_paths(files, folder)

    def import_paths(self, paths, folder: str = ""):
        import convert
        pdfs, others = [], []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                pdfs.extend(sorted(p.glob("*.pdf")))
            elif p.suffix.lower() == ".pdf":
                pdfs.append(p)
            elif convert.is_convertible(p):
                others.append(p)
        if others:
            self.convert_files(others, folder)
        if not pdfs:
            if not others:
                self.toast("Nenhum PDF (ou arquivo que dê para converter) para importar.")
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
        import convert
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") or os.path.isdir(u.toLocalFile())
                                          or convert.is_convertible(u.toLocalFile())
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        self.import_paths(paths, self._drop_folder())

    def change_library(self):
        new = QFileDialog.getExistingDirectory(self, "Escolher a pasta da biblioteca", str(self.lib.root.parent))
        if new:
            self.change_library_to(Path(new))

    def change_library_to(self, new_root: Path):
        """Muda a pasta da biblioteca (por exemplo, para dentro do OneDrive), movendo os PDFs se o usuário quiser."""
        new_root = Path(new_root)
        if new_root.name != "Prumo PDF" and new_root.exists() and any(new_root.iterdir()):
            new_root = new_root / "Prumo PDF"
        old = self.lib.root
        if new_root.resolve() == old.resolve():
            self.toast("A biblioteca já está nessa pasta.")
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
        try:
            self.run_with_progress("Movendo os PDFs…", lambda _p: run())
        except UserError as exc:
            self.show_error(str(exc))
            return
        except OSError as exc:
            self.show_error(f"Não foi possível mover: {exc.strerror or exc}. O arquivo pode estar aberto em outro "
                            "programa.")
            return
        self.set_setting("library_root", str(new_root))
        self._swap_library(str(new_root))
        import backup
        cloud = backup.cloud_of(new_root)
        self.toast(f"Pronto: a biblioteca agora está no {cloud}, com backup na nuvem." if cloud
                   else "Pasta da biblioteca alterada.")

    # --- cópia de segurança ---
    def backup_now(self):
        import backup
        start = self.setting("backup_dir", str(Path.home()))
        dest = QFileDialog.getExistingDirectory(self, "Onde guardar a cópia? (pendrive, HD externo…)", start)
        if not dest:
            return
        try:
            target, n = self.run_with_progress("Fazendo a cópia de segurança…",
                                               lambda _p: backup.make_copy(self.lib.root, Path(dest)))
        except UserError as exc:
            self.show_error(str(exc))
            return
        except OSError as exc:
            self.show_error(f"Não foi possível copiar: {exc.strerror or exc}")
            return
        self.set_setting("backup_dir", dest)
        self.set_setting("last_backup", __import__("time").time())
        self.toast(f"Cópia feita: {n} PDF{'s' if n != 1 else ''} em “{target.name}”.", "Mostrar",
                   lambda: self.reveal(target))
        self.current().refresh()

    def restore_from(self):
        import backup
        idx = alert(self, "Restaurar de uma cópia",
                    "Escolha a pasta da cópia (ou qualquer pasta com PDFs). Os PDFs voltam para a biblioteca nas "
                    "mesmas pastas; os que já estão aqui não são duplicados. Também dá para escolher um arquivo .zip.",
                    [("Escolher pasta", "default"), ("Escolher .zip", "default"), ("Cancelar", "cancel")])
        if idx is None or idx == 2:
            return
        start = self.setting("backup_dir", str(Path.home()))
        if idx == 0:
            src = QFileDialog.getExistingDirectory(self, "Pasta da cópia", start)
        else:
            src, _ = QFileDialog.getOpenFileName(self, "Arquivo .zip da cópia", start, "ZIP (*.zip)")
        if not src:
            return
        try:
            res = self.run_with_progress("Restaurando…", lambda _p: backup.restore(Path(src), self.lib))
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Não foi possível restaurar: {exc}")
            return
        parts = [f"{res.added} PDF{'s' if res.added != 1 else ''} restaurado{'s' if res.added != 1 else ''}"]
        if res.skipped:
            parts.append(f"{res.skipped} já estava{'m' if res.skipped != 1 else ''} na biblioteca")
        self.toast(", ".join(parts) + ".")

    # --- arquivos vindos do Explorador ("Abrir com", botão direito) ---
    def handle_external(self, open_paths=(), convert_paths=()):
        """PDFs abertos pelo Windows: abre no leitor (sem importar duas vezes). Outros arquivos: converte."""
        import backup
        import convert
        self.showNormal()
        self.raise_()
        self.activateWindow()
        pdfs = [Path(p) for p in open_paths if str(p).lower().endswith(".pdf") and Path(p).is_file()]
        others = [Path(p) for p in list(open_paths) + list(convert_paths)
                  if convert.is_convertible(p) and Path(p).is_file()]
        opened = None
        for p in pdfs:
            same = backup.find_same_file(p, self.lib)
            if same is None:
                res = {}
                if self.attempt(lambda: res.setdefault("items", self.lib.import_files([p], ""))) and res["items"]:
                    same = res["items"][0]
            opened = same or opened
        if others:
            made = self.convert_files(others, "")
            if made and opened is None and len(made) == 1:
                opened = made[0]
                return
        if opened is not None and len(pdfs) == 1:
            self.read(opened)
        elif len(pdfs) > 1:
            self.toast(f"{len(pdfs)} PDFs abertos na biblioteca (Sem pasta).")
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
