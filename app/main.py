"""Prumo PDF - ponto de entrada.

    PrumoPDF.exe                  abre a biblioteca (visual igual ao do iPhone)
    PrumoPDF.exe a.pdf b.pdf      abre a biblioteca e importa os PDFs
    PrumoPDF.exe --classico       abre a tela antiga (OCR em lote, combinar, extrair)
    PrumoPDF.exe --ocr-worker J   uso interno: processo de OCR (sem janela)
"""

from __future__ import annotations

import os
import sys

# Garante que os módulos do app sejam encontrados também em desenvolvimento.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_worker(job_file: str) -> int:
    import ocr_worker  # não importa Qt: o processo de OCR fica leve
    return ocr_worker.main(job_file)


def run_classic(files: list[str]) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                                   QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                                   QVBoxLayout, QWidget)

    import core
    from ui_common import C, app_icon, build_style, icon, settings

    if sys.platform == "win32":
        try:  # ícone próprio na barra de tarefas
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Prumo.PrumoPDF")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(core.APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(build_style())

    from page_extract import ExtractPage
    from page_merge import MergePage
    from page_ocr import OcrPage

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(core.APP_NAME)
            self.setMinimumSize(980, 640)
            central = QWidget()
            lay = QHBoxLayout(central)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)

            side = QFrame()
            side.setObjectName("sidebar")
            side.setFixedWidth(258)
            sl = QVBoxLayout(side)
            sl.setContentsMargins(14, 20, 14, 16)
            sl.setSpacing(4)
            brand_row = QHBoxLayout()
            logo = QLabel()
            logo.setPixmap(app_icon().pixmap(30, 30))
            brand_row.addWidget(logo)
            brand_col = QVBoxLayout()
            brand_col.setSpacing(0)
            b = QLabel(core.APP_NAME)
            b.setObjectName("brand")
            bs = QLabel("OCR · combinar · extrair")
            bs.setObjectName("brandSub")
            brand_col.addWidget(b)
            brand_col.addWidget(bs)
            brand_row.addLayout(brand_col, 1)
            sl.addLayout(brand_row)
            sl.addSpacing(22)

            self.stack = QStackedWidget()
            self.stack.setObjectName("content")
            self.ocr = OcrPage()
            self.merge = MergePage()
            self.extract = ExtractPage()
            self.group = QButtonGroup(self)
            for idx, (name, text, page) in enumerate((
                    ("ocr", "Reconhecer texto (OCR)", self.ocr),
                    ("merge", "Combinar PDFs", self.merge),
                    ("extract", "Extrair páginas", self.extract))):
                btn = QPushButton("  " + text)
                btn.setObjectName("navButton")
                btn.setIcon(icon(name, "#C9D1E0", 18))
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _c=False, i=idx: self.stack.setCurrentIndex(i))
                self.group.addButton(btn, idx)
                sl.addWidget(btn)
                self.stack.addWidget(page)
            sl.addStretch(1)

            tess = core.find_tesseract()
            has_por = core.tessdata_dir() is not None
            if tess and has_por:
                status, color = "● Motor de OCR pronto", C["ok"]
            elif tess:
                status, color = "● Modelo de português ausente", "#E8A13A"
            else:
                status, color = "● Tesseract não encontrado", "#E5675A"
            st = QLabel(status)
            st.setObjectName("engineStatus")
            st.setStyleSheet(f"color: {color};")
            st.setToolTip(str(tess) if tess else "Reinstale o Prumo PDF para instalar o Tesseract.")
            ver = QLabel(f"Versão {core.APP_VERSION} · tudo roda neste computador")
            ver.setObjectName("engineStatus")
            ver.setWordWrap(True)
            sl.addWidget(st)
            sl.addWidget(ver)

            lay.addWidget(side)
            lay.addWidget(self.stack, 1)
            self.setCentralWidget(central)
            self.ocr.busy_changed.connect(self._busy)

            s = settings()
            geo = s.value("geometry")
            if geo is not None:
                self.restoreGeometry(geo)
            else:
                self.resize(1180, 760)
            start = int(s.value("last_page", 0))
            self.group.button(start).setChecked(True)
            self.stack.setCurrentIndex(start)

        def _busy(self, busy: bool):
            self.group.button(0).setText("  Reconhecer texto (OCR)" + ("  ⏳" if busy else ""))

        def closeEvent(self, e):
            if self.ocr.is_busy():
                r = QMessageBox.question(self, "OCR em andamento",
                                         "Há um OCR em andamento. Deseja cancelar e fechar?")
                if r != QMessageBox.Yes:
                    e.ignore()
                    return
            self.ocr.shutdown()
            self.merge.shutdown()
            self.extract.shutdown()
            s = settings()
            s.setValue("geometry", self.saveGeometry())
            s.setValue("last_page", self.stack.currentIndex())
            e.accept()

    w = Window()
    pdfs = [f for f in files if f.lower().endswith(".pdf") and os.path.isfile(f)]
    if pdfs:
        w.group.button(0).setChecked(True)
        w.stack.setCurrentIndex(0)
        w.ocr.add_files(pdfs)
    w.show()
    return app.exec()


def _app_setup():
    from PySide6.QtWidgets import QApplication

    import core
    from ios_theme import T, app_icon

    if sys.platform == "win32":
        try:  # ícone próprio na barra de tarefas
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Prumo.PrumoPDF")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(core.APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    return app, T


def run_gui(files: list[str]) -> int:
    from PySide6.QtCore import QSettings

    app, T = _app_setup()
    from app_window import MainWindow
    from ocr_runner import clean_stale_temp

    clean_stale_temp()
    settings = QSettings("Prumo", "PrumoPDF")
    T.setup(str(settings.value("appearance", "system")))
    w = MainWindow(settings)
    w.show()
    pdfs = [f for f in files if f.lower().endswith(".pdf") and os.path.isfile(f)]
    if pdfs:
        w.import_paths(pdfs)
    return app.exec()


def run_demo(args: list[str]) -> int:
    """Abre a biblioteca de demonstração numa tela e, com --shot, salva a imagem da janela e fecha."""
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QSettings, QTimer

    def arg(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    app, T = _app_setup()
    import demo
    from app_window import MainWindow

    root = Path(arg("--demo"))
    if "--keep" not in args or not root.exists():
        demo.seed(root)
    ini = Path(tempfile.gettempdir()) / "prumo_demo_settings.ini"
    ini.unlink(missing_ok=True)
    settings = QSettings(str(ini), QSettings.IniFormat)
    T.setup("dark" if "--dark" in args else "light")
    from library import Library

    w = MainWindow(settings, Library(root, local_dir=root.parent / (root.name + "_local")))
    width, height = (int(x) for x in arg("--size", "1100x780").split("x"))
    w.resize(width, height)
    w.show()
    demo.apply_screen(w, arg("--screen", "home"))
    shot = arg("--shot")
    if shot:
        delay = int(arg("--wait", "1500"))

        def grab():
            w.grab().save(shot)
            os._exit(0)   # sai mesmo com um diálogo aberto
        QTimer.singleShot(delay, grab)
    return app.exec()


def self_test(report_file: str) -> int:
    """Conferência do pacote, usada pelo script de build: grava um JSON com o resultado."""
    import json
    result = {}
    try:
        import core
        import ocrmypdf
        import ocr_plugin  # noqa: F401
        import pikepdf, pypdf, pypdfium2  # noqa: F401
        from PySide6 import QtSvg, QtWidgets  # noqa: F401
        result["ocrmypdf"] = ocrmypdf.__version__
        result["tessdata"] = str(core.tessdata_dir()) if core.tessdata_dir() else None
        result["tessdata_best"] = str(core.tessdata_dir(True)) if core.tessdata_dir(True) else None
        result["tesseract"] = str(core.find_tesseract()) if core.find_tesseract() else None
        result["ok"] = bool(result["tessdata"])
    except Exception as exc:
        result["ok"] = False
        result["error"] = repr(exc)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return 0 if result["ok"] else 1


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--ocr-worker"] and len(args) >= 2:
        return run_worker(args[1])
    if args[:1] == ["--self-test"] and len(args) >= 2:
        return self_test(args[1])
    import multiprocessing
    multiprocessing.freeze_support()
    if "--demo" in args:
        return run_demo(args)
    if args[:1] in (["--classico"], ["--classic"]):
        return run_classic(args[1:])
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
