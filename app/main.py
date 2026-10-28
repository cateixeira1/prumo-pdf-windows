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


def _server_name() -> str:
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = "usuario"
    return f"PrumoPDF-{user}"


_MUTEX = None


def _is_primary() -> bool:
    """No Windows, só o primeiro processo do usuário consegue o marcador; os outros entregam os arquivos a ele."""
    global _MUTEX
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\" + _server_name())
        return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _send_to_running(message: dict) -> bool:
    """
    Se o Prumo já está aberto, entrega os arquivos para ele (uma janela só) e devolve True.
    Espera a confirmação ("ok") da janela aberta antes de desconectar, para nada se perder.
    """
    import json

    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps(message).encode("utf-8") + b"\n")   # a quebra de linha marca o fim da mensagem
    sock.flush()
    written = sock.waitForBytesWritten(2000) or sock.bytesToWrite() == 0
    reply = bytearray()
    for _ in range(8):                                       # espera a confirmação por até ~1,6 s
        if sock.waitForReadyRead(200):
            reply.extend(bytes(sock.readAll()))
            if b"\n" in reply:
                break
        elif sock.state() != QLocalSocket.ConnectedState:
            break
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.UnconnectedState:
        sock.waitForDisconnected(500)
    return reply.strip() == b"ok" or written


def start_instance_server(window, delay_ms: int = 700):
    """
    Recebe os arquivos abertos depois (Abrir com, botão direito > Converter em PDF). O Windows abre
    um processo por arquivo selecionado: os que chegam juntos são tratados de uma vez.
    """
    import json

    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    if not server.listen(_server_name()):
        QLocalServer.removeServer(_server_name())
        server.listen(_server_name())
    pending = {"open": [], "convert": []}
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.setInterval(delay_ms)

    def flush():
        o, c = pending["open"][:], pending["convert"][:]
        pending["open"].clear()
        pending["convert"].clear()
        if o or c:
            window.handle_external(o, c)
        else:
            window.showNormal()
            window.raise_()
            window.activateWindow()
    timer.timeout.connect(flush)

    def on_connection():
        import time
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            buf = bytearray(bytes(conn.readAll()))
            # A mensagem é pequena e chega logo depois da conexão: espera por ela (no máximo 2 s)
            # em vez de depender do aviso de "dados chegaram", que no Windows pode se perder.
            end = time.monotonic() + 2.0
            while not buf.endswith(b"\n") and time.monotonic() < end:
                if conn.waitForReadyRead(100):
                    buf.extend(bytes(conn.readAll()))
            try:
                msg = json.loads(bytes(buf).decode("utf-8").strip() or "{}")
            except ValueError:
                msg = {}
            if buf.endswith(b"\n"):
                conn.write(b"ok\n")                       # confirma: o outro processo já pode sair
                conn.flush()
                conn.waitForBytesWritten(1000)
            conn.disconnected.connect(conn.deleteLater)
            pending["open"].extend(msg.get("open", []))
            pending["convert"].extend(msg.get("convert", []))
            timer.start()
    server.newConnection.connect(on_connection)
    return server


def run_gui(files: list[str]) -> int:
    from PySide6.QtCore import QSettings

    convert_mode = "--convert" in files
    paths = [os.path.abspath(f) for f in files if not f.startswith("--")]
    message = {"open": [] if convert_mode else paths, "convert": paths if convert_mode else []}
    app, T = _app_setup()
    if _send_to_running(message):
        return 0
    if not _is_primary():
        # Outro processo do Prumo acabou de abrir (vários arquivos ao mesmo tempo): espera a janela dele.
        import time
        for _ in range(30):
            time.sleep(0.2)
            if _send_to_running(message):
                return 0
    from app_window import MainWindow
    from ocr_runner import clean_stale_temp

    clean_stale_temp()
    settings = QSettings("Prumo", "PrumoPDF")
    T.setup(str(settings.value("appearance", "system")))
    w = MainWindow(settings)
    w.show()
    w._instance_server = start_instance_server(w)
    if message["open"] or message["convert"]:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, lambda: w.handle_external(message["open"], message["convert"]))
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
        import convert  # noqa: F401
        import fpdf, img2pdf, mammoth  # noqa: F401, E401
        from PySide6 import QtNetwork  # noqa: F401
        try:
            import pillow_heif  # noqa: F401
            result["heic"] = True
        except Exception as exc:  # noqa: BLE001
            result["heic"] = repr(exc)
        from ios_theme import _icon_file
        result["icon"] = str(_icon_file()) if _icon_file() else None
        import dewarp
        result["dewarp"] = dewarp.available()
        result["version"] = core.APP_VERSION
        result["ok"] = bool(result["tessdata"]) and bool(result["icon"]) and result["heic"] is True and result["dewarp"]
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
