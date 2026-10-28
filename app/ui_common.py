"""Estilo, ícones e componentes reutilizados pelas telas do Prumo PDF."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget, QFileDialog)

# --- Paleta -------------------------------------------------------------------
C = {
    "sidebar": "#1C2230",
    "sidebar_hover": "#283044",
    "sidebar_active": "#323C55",
    "sidebar_text": "#C9D1E0",
    "bg": "#F6F5F2",
    "surface": "#FFFFFF",
    "border": "#E3E1DC",
    "border_strong": "#CFCBC3",
    "text": "#1F2328",
    "muted": "#636B78",
    "accent": "#0E7C74",
    "accent_hover": "#0B6A63",
    "accent_soft": "#E3F2F0",
    "warn": "#B45309",
    "warn_soft": "#FDF3E4",
    "error": "#B42318",
    "error_soft": "#FCEBEA",
    "ok": "#15803D",
    "ok_soft": "#E7F5EC",
}

STYLE_TEMPLATE = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans", sans-serif; font-size: 10pt; color: {C['text']}; }}
QMainWindow, #content {{ background: {C['bg']}; }}
#sidebar {{ background: {C['sidebar']}; }}
#brand {{ color: #FFFFFF; font-size: 15pt; font-weight: 600; }}
#brandSub {{ color: #8C97AD; font-size: 8.5pt; }}
#navButton {{ background: transparent; border: none; border-radius: 8px; color: {C['sidebar_text']};
              text-align: left; padding: 10px 12px; font-size: 10.5pt; }}
#navButton:hover {{ background: {C['sidebar_hover']}; color: #FFFFFF; }}
#navButton:checked {{ background: {C['sidebar_active']}; color: #FFFFFF; font-weight: 600; }}
#engineStatus {{ color: #8C97AD; font-size: 8.5pt; }}
#pageTitle {{ font-size: 17pt; font-weight: 600; }}
#pageSubtitle {{ color: {C['muted']}; }}
#card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
#sectionLabel {{ color: {C['muted']}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
#dropZone {{ background: {C['surface']}; border: 2px dashed {C['border_strong']}; border-radius: 12px; }}
#dropZone[active="true"] {{ background: {C['accent_soft']}; border-color: {C['accent']}; }}
#dropTitle {{ font-size: 11.5pt; font-weight: 600; }}
#dropHint {{ color: {C['muted']}; }}
QPushButton {{ background: {C['surface']}; border: 1px solid {C['border_strong']}; border-radius: 7px;
               padding: 7px 14px; }}
QPushButton:hover {{ border-color: {C['accent']}; color: {C['accent']}; }}
QPushButton:disabled {{ color: #A3A8B0; border-color: {C['border']}; background: #FAFAF8; }}
QPushButton#primary {{ background: {C['accent']}; border: 1px solid {C['accent']}; color: #FFFFFF; font-weight: 600;
                       padding: 8px 20px; }}
QPushButton#primary:hover {{ background: {C['accent_hover']}; border-color: {C['accent_hover']}; color: #FFFFFF; }}
QPushButton#primary:disabled {{ background: #9CC9C4; border-color: #9CC9C4; color: #FFFFFF; }}
QPushButton#danger:hover {{ border-color: {C['error']}; color: {C['error']}; }}
QPushButton#link {{ background: transparent; border: none; color: {C['accent']}; padding: 2px 4px; font-weight: 600; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QTreeWidget, QListWidget, QTableWidget {{ background: {C['surface']}; border: 1px solid {C['border']};
               border-radius: 8px; alternate-background-color: #FAF9F7; outline: 0; }}
QTreeWidget::item, QTableWidget::item {{ padding: 5px 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{
               background: {C['accent_soft']}; color: {C['text']}; }}
QListWidget#pagesGrid::item {{ border-radius: 6px; padding: 4px; margin: 2px; }}
QListWidget#pagesGrid::item:selected {{ background: {C['accent_soft']}; border: 2px solid {C['accent']}; }}
QHeaderView::section {{ background: #F1EFEB; border: none; border-bottom: 1px solid {C['border']};
               padding: 6px 6px; color: {C['muted']}; font-weight: 600; font-size: 9pt; }}
QLineEdit, QComboBox {{ background: {C['surface']}; border: 1px solid {C['border_strong']};
               border-radius: 6px; padding: 5px 8px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url(@CHEVRON@); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {C['surface']}; border: 1px solid {C['border_strong']};
               selection-background-color: {C['accent_soft']}; selection-color: {C['text']}; outline: 0; padding: 4px; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QProgressBar {{ background: #ECEAE5; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}
QToolTip {{ background: {C['sidebar']}; color: #FFFFFF; border: none; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CFCBC3; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
#messageBar {{ border-radius: 8px; }}
"""

def build_style() -> str:
    """Folha de estilo final. Chamar depois de criar a QApplication."""
    import tempfile
    d = Path(tempfile.gettempdir()) / "prumo_ui"
    d.mkdir(exist_ok=True)
    chevron = d / "chevron.png"
    if not chevron.exists():
        icon("down_small", C["muted"], 12).pixmap(24, 24).save(str(chevron))
    return STYLE_TEMPLATE.replace("@CHEVRON@", chevron.as_posix())


# --- Ícones (SVG simples, cor aplicada em tempo de execução) -----------------
_SVG = {
    "ocr": '<path d="M4 7V5a1 1 0 0 1 1-1h2M17 4h2a1 1 0 0 1 1 1v2M20 17v2a1 1 0 0 1-1 1h-2M7 20H5a1 1 0 0 1-1-1v-2"/>'
           '<path d="M8 9h8M8 12h8M8 15h5"/>',
    "merge": '<rect x="4" y="3" width="10" height="13" rx="1.5"/><rect x="10" y="8" width="10" height="13" rx="1.5"/>',
    "extract": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 14h6M12 11v6"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down_small": '<path d="M6 9l6 6 6-6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "trash": '<path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/>',
    "folder": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "check": '<path d="M5 12l4 4 10-10"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    "plumb": '<path d="M12 1.5v5"/><path d="M8.2 7.5h7.6c0 4.2-1.6 9-3.8 14.5C9.8 16.5 8.2 11.7 8.2 7.5z" fill="currentFill"/>',
}


def icon(name: str, color: str = C["text"], size: int = 20) -> QIcon:
    body = _SVG[name].replace("currentFill", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(QSize(size * 2, size * 2))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


def app_icon() -> QIcon:
    """Ícone do aplicativo: prumo branco sobre quadrado verde-petróleo (o mesmo .ico da tela nova)."""
    try:
        from ios_theme import _icon_file
        f = _icon_file()
        if f is not None:
            ic = QIcon(str(f))
            if not ic.isNull() and ic.availableSizes():
                return ic
    except Exception:
        pass
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(C["accent"]))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(8, 8, 240, 240, 52, 52)
    body = _SVG["plumb"].replace("currentFill", "#FFFFFF")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
           'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + body + '</svg>')
    QSvgRenderer(QByteArray(svg.encode())).render(p, pm.rect().adjusted(44, 36, -44, -36))
    p.end()
    return QIcon(pm)


# --- Componentes ----------------------------------------------------------------

def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def section_label(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("sectionLabel")
    return lab


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        s = QLabel(subtitle)
        s.setObjectName("pageSubtitle")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)


def pdf_paths_from_mime(mime) -> list[str]:
    out = []
    if mime.hasUrls():
        for url in mime.urls():
            p = url.toLocalFile()
            if p and p.lower().endswith(".pdf") and os.path.isfile(p):
                out.append(p)
            elif p and os.path.isdir(p):
                out.extend(str(x) for x in sorted(Path(p).glob("*.pdf")))
    return out


class DropZone(QFrame):
    """Área para arrastar PDFs ou clicar e escolher."""

    files_dropped = Signal(list)

    def __init__(self, title: str, hint: str, multiple: bool = True, compact: bool = False):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.multiple = multiple
        lay = QHBoxLayout(self) if compact else QVBoxLayout(self)
        lay.setContentsMargins(20, 14 if compact else 26, 20, 14 if compact else 26)
        lay.setSpacing(12 if compact else 6)
        ic = QLabel()
        ic.setPixmap(icon("upload", C["accent"], 26 if compact else 34).pixmap(26 if compact else 34))
        ic.setAlignment(Qt.AlignCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("dropTitle")
        h = QLabel(hint)
        h.setObjectName("dropHint")
        if compact:
            lay.addWidget(ic)
            texts.addWidget(t)
            texts.addWidget(h)
            lay.addLayout(texts, 1)
        else:
            for w in (ic, t, h):
                w.setAlignment(Qt.AlignCenter)
                lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if pdf_paths_from_mime(e.mimeData()):
            e.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, e):
        self._set_active(False)

    def dropEvent(self, e):
        self._set_active(False)
        files = pdf_paths_from_mime(e.mimeData())
        if files:
            self.files_dropped.emit(files if self.multiple else files[:1])

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            start = last_dir()
            if self.multiple:
                files, _ = QFileDialog.getOpenFileNames(self, "Escolher PDFs", start, "PDF (*.pdf)")
            else:
                f, _ = QFileDialog.getOpenFileName(self, "Escolher PDF", start, "PDF (*.pdf)")
                files = [f] if f else []
            if files:
                remember_dir(files[0])
                self.files_dropped.emit(files)


class MessageBar(QFrame):
    """Faixa de aviso com ações (Abrir arquivo, Mostrar na pasta)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("messageBar")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 10, 10)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(self.icon)
        self.lay.addWidget(self.text, 1)
        self.buttons: list[QPushButton] = []
        close = QPushButton("✕")
        close.setObjectName("link")
        close.setToolTip("Fechar aviso")
        close.clicked.connect(self.hide)
        self.close_btn = close
        self.lay.addWidget(close)
        self.hide()

    def show_message(self, kind: str, text: str, path: str | None = None, folder_only: bool = False):
        colors = {"ok": (C["ok_soft"], C["ok"], "check"), "warn": (C["warn_soft"], C["warn"], "alert"),
                  "error": (C["error_soft"], C["error"], "alert"), "info": (C["accent_soft"], C["accent"], "check")}
        bg, fg, ic = colors[kind]
        self.setStyleSheet(f"#messageBar {{ background: {bg}; border: 1px solid {fg}33; }}")
        self.icon.setPixmap(icon(ic, fg, 18).pixmap(18))
        self.text.setText(text)
        for b in self.buttons:
            b.deleteLater()
        self.buttons = []
        if path:
            if not folder_only:
                b1 = QPushButton("Abrir")
                b1.setObjectName("link")
                b1.clicked.connect(lambda: open_path(path))
                self.buttons.append(b1)
            b2 = QPushButton("Mostrar na pasta")
            b2.setObjectName("link")
            b2.clicked.connect(lambda: reveal_in_folder(path))
            self.buttons.append(b2)
        for b in self.buttons:
            self.lay.insertWidget(self.lay.count() - 1, b)
        self.show()


# --- Utilidades -------------------------------------------------------------------

def open_path(path: str):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def reveal_in_folder(path: str):
    p = os.path.normpath(path)
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.path.isdir(p):
            subprocess.Popen(["explorer", p], creationflags=flags)
        else:
            subprocess.Popen(["explorer", "/select,", p], creationflags=flags)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(p if os.path.isdir(p) else os.path.dirname(p)))


_settings = None


def settings():
    global _settings
    if _settings is None:
        from PySide6.QtCore import QSettings
        _settings = QSettings("Prumo", "PrumoPDF")
    return _settings


def last_dir() -> str:
    return settings().value("last_dir", str(Path.home() / "Documents"))


def remember_dir(path: str):
    settings().setValue("last_dir", str(Path(path).parent if os.path.isfile(path) else path))


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


def debounce(widget: QWidget, ms: int, fn):
    t = QTimer(widget)
    t.setSingleShot(True)
    t.setInterval(ms)
    t.timeout.connect(fn)
    return t
