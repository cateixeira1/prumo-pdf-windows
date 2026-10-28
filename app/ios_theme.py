"""
Tema visual igual ao do Prumo PDF para iPhone: fundo cinza-claro, cartões cinza
com ícone colorido, contadores em negrito. Claro e escuro, seguindo o Windows.

Os ícones são desenhos próprios (SVG) no estilo dos símbolos do iOS; os
símbolos da Apple (SF Symbols) não podem ser usados fora das plataformas Apple.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _c(r, g=None, b=None) -> QColor:
    return QColor(r, r, r) if g is None else QColor(r, g, b)


ACCENTS = {
    "yellow": QColor(246, 207, 70),
    "red": QColor(227, 69, 59),
    "blue": QColor(41, 120, 245),
    "green": QColor(64, 184, 92),
    "orange": QColor(245, 148, 41),
    "purple": QColor(140, 97, 219),
    "indigo": QColor(84, 92, 209),
    "teal": QColor(13, 140, 135),
    "gray": QColor(92, 99, 110),
    "pink": QColor(235, 84, 135),
    "brown": QColor(158, 115, 77),
}

LIGHT = {
    "bg": _c(233), "tile": _c(208), "tile_hover": _c(199), "search": _c(220),
    "text": _c(60), "secondary": _c(107), "placeholder": _c(140),
    "panel": _c(246), "panel_line": _c(214), "shadow": QColor(0, 0, 0, 40),
    "dim": QColor(0, 0, 0, 90), "thumb_border": QColor(0, 0, 0, 38),
}
DARK = {
    "bg": _c(18), "tile": _c(43), "tile_hover": _c(52), "search": _c(36),
    "text": _c(235), "secondary": _c(158), "placeholder": _c(128),
    "panel": _c(38), "panel_line": _c(58), "shadow": QColor(0, 0, 0, 120),
    "dim": QColor(0, 0, 0, 140), "thumb_border": QColor(255, 255, 255, 30),
}

TILE_RADIUS = 14
TILE_HEIGHT = 86
DOC_TILE_HEIGHT = 118
SPACING = 12
MARGIN = 16


class _Theme(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "system"     # system, light, dark
        self.dark = False

    def setup(self, mode: str = "system") -> None:
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._update())
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._update()

    def _update(self) -> None:
        if self.mode == "system":
            hints = QGuiApplication.styleHints()
            dark = hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = self.mode == "dark"
        self.dark = dark
        app = QGuiApplication.instance()
        if app is not None and hasattr(app, "setStyleSheet"):
            app.setFont(font(14))
            app.setStyleSheet(stylesheet())
        self.changed.emit()

    def color(self, name: str) -> QColor:
        if name in ACCENTS:
            return ACCENTS[name]
        return (DARK if self.dark else LIGHT)[name]

    def hex(self, name: str) -> str:
        c = self.color(name)
        return c.name(QColor.HexArgb) if c.alpha() < 255 else c.name()


T = _Theme()


# --- Fontes -------------------------------------------------------------------

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"]


def font(px: float, weight: int = 400, display: bool = False) -> QFont:
    """Fonte em pixels, como os tamanhos em pontos do iOS (16 pt no iPhone = 16 px aqui)."""
    f = QFont()
    f.setFamilies(DISPLAY_FAMILIES if display or px >= 20 else UI_FAMILIES)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def _chevron_file(color: str, up: bool = False) -> str:
    """Seta das caixas de seleção, gravada uma vez como SVG (o Qt só lê imagens de arquivo no estilo)."""
    import tempfile
    from pathlib import Path

    name = f"prumo_chevron_{'up' if up else 'down'}_{color.strip('#')}.svg"
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        d = "M6 15l6-6 6 6" if up else "M6 9l6 6 6-6"
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                        f'stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
                        f'<path d="{d}"/></svg>', encoding="utf-8")
    return path.as_posix()


def stylesheet() -> str:
    t = T.hex
    down = _chevron_file(t('secondary'))
    up = _chevron_file(t('secondary'), up=True)
    return f"""
QWidget {{ color: {t('text')}; }}
QMainWindow, #screen, #scrollBody {{ background: {t('bg')}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {t('placeholder')}; border-radius: 3px; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {t('placeholder')}; border-radius: 3px; min-width: 40px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QLineEdit {{ background: {t('search')}; border: none; border-radius: 10px; padding: 8px 12px;
             selection-background-color: {ACCENTS['blue'].name()}; selection-color: white; }}
QMenu {{ background: {t('panel')}; border: 1px solid {t('panel_line')}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: 7px; }}
QMenu::item:selected {{ background: {t('tile')}; }}
QMenu::item:disabled {{ color: {t('placeholder')}; }}
QMenu::separator {{ height: 1px; background: {t('panel_line')}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QToolTip {{ background: {t('panel')}; color: {t('text')}; border: 1px solid {t('panel_line')}; padding: 5px 8px; border-radius: 6px; }}
QCheckBox {{ spacing: 10px; }}
QComboBox {{ background: {t('search')}; border: none; border-radius: 10px; padding: 7px 34px 7px 12px; }}
QComboBox::drop-down {{ border: none; width: 30px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t('panel')}; border: 1px solid {t('panel_line')}; selection-background-color: {t('tile')}; selection-color: {t('text')}; outline: 0; }}
QSpinBox {{ background: {t('search')}; border: none; border-radius: 10px; padding: 7px 30px 7px 12px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 26px; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: url("{up}"); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QProgressBar {{ background: {t('search')}; border: none; border-radius: 3px; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENTS['blue'].name()}; border-radius: 3px; }}
"""


# --- Ícones -------------------------------------------------------------------

_CORNERS = ('<path d="M3.5 8V5.5a2 2 0 0 1 2-2H8M16 3.5h2.5a2 2 0 0 1 2 2V8M20.5 16v2.5a2 2 0 0 1-2 2H16'
            'M8 20.5H5.5a2 2 0 0 1-2-2V16"/>')

GLYPHS = {
    "scan": _CORNERS + '<rect x="7.5" y="6.5" width="9" height="11" rx="1.2"/><path d="M10 10h4M10 13h4"/>',
    "import": '<path d="M12 3.5v10.5M7.5 9.5L12 14l4.5-4.5"/><path d="M4.5 14v3.5a2.5 2.5 0 0 0 2.5 2.5h10a2.5 2.5 0 0 0 2.5-2.5V14"/>',
    "docs": '<path d="M9 6.5V5a1.5 1.5 0 0 1 1.5-1.5h7A1.5 1.5 0 0 1 19 5v10a1.5 1.5 0 0 1-1.5 1.5H16"/>'
            '<rect x="5" y="7" width="11" height="14" rx="1.8" fill="#FG"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2.2"/>',
    "textscan": _CORNERS + '<path d="M8 9h8M8 12h8M8 15h5"/>',
    "check": '<path d="M6.5 12.5l3.5 3.5 7.5-8.2" stroke-width="2.6"/>',
    "star": '<path d="M12 3.6l2.5 5.3 5.8.7-4.3 4 1.1 5.8L12 16.6l-5.1 2.8 1.1-5.8-4.3-4 5.8-.7z" fill="#FG" stroke-width="1.2"/>',
    "stack": '<path d="M12 4l8 4-8 4-8-4z" fill="#FG"/><path d="M4 12.2l8 4 8-4M4 16.2l8 4 8-4"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" fill="#FG"/>',
    "folder_line": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "folderplus": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>',
    "tray": '<path d="M3.5 13l2.8-7.5h11.4l2.8 7.5v5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M3.5 13h5l1 2h5l1-2h5"/>',
    "book": '<path d="M12 6.5C10 5 7 4.5 4 5v13c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5V5c-3-.5-6 0-8 1.5zM12 6.5v13"/>',
    "share": '<path d="M12 3.5v11M8 7.5l4-4 4 4"/><path d="M8 10.5H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-1"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.6" fill="#FG"/><rect x="13" y="4" width="7" height="7" rx="1.6" fill="#FG"/>'
            '<rect x="4" y="13" width="7" height="7" rx="1.6" fill="#FG"/><rect x="13" y="13" width="7" height="7" rx="1.6" fill="#FG"/>',
    "plusrect": '<path d="M7.5 4h10a2.5 2.5 0 0 1 2.5 2.5v10"/><rect x="4" y="7.5" width="12.5" height="12.5" rx="2"/><path d="M10.2 10.8v6M7.2 13.8h6"/>',
    "minusrect": '<rect x="3.5" y="5.5" width="17" height="13" rx="2.2"/><path d="M8.5 12h7"/>',
    "scissors": '<circle cx="6.5" cy="7" r="2.6"/><circle cx="6.5" cy="17" r="2.6"/><path d="M8.7 8.4L20 17.5M8.7 15.6L20 6.5"/>',
    "docplus": '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/><path d="M12 11v6M9 14h6"/>',
    "pencil": '<path d="M5 19l1-4.2L16.2 4.6a1.8 1.8 0 0 1 2.6 0l.6.6a1.8 1.8 0 0 1 0 2.6L9.2 18z"/><path d="M14.5 6.3l3.2 3.2"/>',
    "duplicate": '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2h-7.5a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/><path d="M14.5 11.5v6M11.5 14.5h6"/>',
    "undo": '<path d="M9 14.5L4 9.5l5-5"/><path d="M4 9.5h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "trash": '<path d="M4.5 7h15M10 7V4.5h4V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5"/>',
    "trash_fill": '<path d="M10 6.5V4.5h4v2" /><path d="M4.5 6.5h15"/><path d="M6.5 8h11l-1 12h-9z" fill="#FG"/>',
    "gear": '<path d="M19.17 10.18 L21.47 10.45 L21.47 13.55 L19.17 13.82 L18.36 15.79 L19.79 17.60 L17.60 19.79 L15.79 18.36 L13.82 19.17 L13.55 21.47 L10.45 21.47 L10.18 19.17 L8.21 18.36 L6.40 19.79 L4.21 17.60 L5.64 15.79 L4.83 13.82 L2.53 13.55 L2.53 10.45 L4.83 10.18 L5.64 8.21 L4.21 6.40 L6.40 4.21 L8.21 5.64 L10.18 4.83 L10.45 2.53 L13.55 2.53 L13.82 4.83 L15.79 5.64 L17.60 4.21 L19.79 6.40 L18.36 8.21 Z"/><circle cx="12" cy="12" r="3.1"/>',
    "back": '<path d="M14.5 5l-7 7 7 7" stroke-width="2.4"/>',
    "ellipsis": '<circle cx="6" cy="12" r="1.7" fill="#FG" stroke="none"/><circle cx="12" cy="12" r="1.7" fill="#FG" stroke="none"/><circle cx="18" cy="12" r="1.7" fill="#FG" stroke="none"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20.5 20.5" stroke-width="2.2"/>',
    "warning": '<path d="M12 3.8L21.5 20h-19z" fill="#FG"/>',
    "seal": '<path d="M12 2.8l2.2 1.7 2.8-.3 1 2.6 2.5 1.3-.5 2.8 1.3 2.5-2 2 .2 2.8-2.7.8-1.5 2.4-2.7-.9L12 21.2l-2.2-1.7-2.7.9-1.5-2.4-2.7-.8.2-2.8-2-2 1.3-2.5-.5-2.8 2.5-1.3 1-2.6 2.8.3z" fill="#FG"/>',
    "explorer": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M14 12.5h4M16 10.5l2 2-2 2"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2h-7.5a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
    "export": '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/><path d="M12 17v-6.5M9.5 13l2.5-2.5 2.5 2.5"/>',
    "open": '<path d="M13 4.5h6.5V11M19.5 4.5L11 13"/><path d="M17 14v4.5a2 2 0 0 1-2 2H6.5a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2H11"/>',
    "select": '<circle cx="12" cy="12" r="8.5"/><path d="M8.2 12.3l2.6 2.6 5-5.4"/>',
    "sort": '<path d="M7 4.5v15M3.8 16.3L7 19.5l3.2-3.2M14 6h6.5M14 11h5M14 16h3.5"/>',
    "text": '<path d="M4.5 6h15M4.5 10h15M4.5 14h15M4.5 18h9"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2" fill="#FG"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2" stroke-width="2.2"/>',
    "x": '<path d="M7 7l10 10M17 7L7 17" stroke-width="2.2"/>',
    "plus": '<path d="M12 5v14M5 12h14" stroke-width="2.2"/>',
    "drag": '<path d="M5 8h14M5 12h14M5 16h14"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
    "star_line": '<path d="M12 3.6l2.5 5.3 5.8.7-4.3 4 1.1 5.8L12 16.6l-5.1 2.8 1.1-5.8-4.3-4 5.8-.7z"/>',
    "rotate_left": '<path d="M4.5 4.5v5h5"/><path d="M5 9.5a7.5 7.5 0 1 1 1.6 7.6"/>',
    "rotate_right": '<path d="M19.5 4.5v5h-5"/><path d="M19 9.5a7.5 7.5 0 1 0-1.6 7.6"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20.5 20.5M8 10.5h5M10.5 8v5"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20.5 20.5M8 10.5h5"/>',
    "convert": '<path d="M5 3.5h6l3 3v6"/><path d="M11 3.5v3h3"/><path d="M13 13.5h6.5M17 11l2.5 2.5L17 16"/>'
               '<rect x="5" y="15" width="8" height="5.5" rx="1"/><path d="M7 17.8h4"/>',
    "computer": '<rect x="3" y="4.5" width="18" height="12" rx="1.8"/><path d="M9 20h6M12 16.5V20"/>',
    "library": '<rect x="4" y="4" width="4" height="16" rx="1"/><rect x="10" y="4" width="4" height="16" rx="1"/>'
               '<path d="M16.2 5.2l3.6-.9 3 15.2-3.6.9z" transform="translate(-2 0)"/>',
}


def svg(name: str, color: QColor | str, stroke: float = 1.9) -> str:
    c = color.name() if isinstance(color, QColor) else color
    body = GLYPHS[name].replace("#FG", c)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


_renderers: dict[str, QSvgRenderer] = {}


def paint_glyph(p: QPainter, rect: QRectF, name: str, color: QColor, stroke: float = 1.9) -> None:
    key = f"{name}|{color.name(QColor.HexArgb)}|{stroke}"
    r = _renderers.get(key)
    if r is None:
        r = QSvgRenderer(QByteArray(svg(name, color, stroke).encode()))
        _renderers[key] = r
    r.render(p, rect)


def glyph_icon(name: str, color: QColor | None = None, size: int = 20) -> QIcon:
    color = color or T.color("text")
    pm = QPixmap(size * 3, size * 3)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    paint_glyph(p, QRectF(0, 0, size * 3, size * 3), name, color)
    p.end()
    pm.setDevicePixelRatio(3.0)
    return QIcon(pm)


def paint_tile_icon(p: QPainter, rect: QRectF, name: str, color: QColor, rounded: bool) -> None:
    """Ícone dos cartões: símbolo branco sobre círculo ou quadrado arredondado colorido."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    if rounded:
        r = rect.width() * 0.24
        p.drawRoundedRect(rect, r, r)
    else:
        p.drawEllipse(rect)
    inset = rect.width() * 0.2
    paint_glyph(p, rect.adjusted(inset, inset, -inset, -inset), name, QColor("white"), 2.1)
    p.restore()


def _icon_file():
    """O PrumoPDF.ico (16 a 256 px), dentro do pacote instalado ou na pasta assets do código."""
    import sys
    from pathlib import Path

    bases = []
    if getattr(sys, "_MEIPASS", None):
        bases.append(Path(sys._MEIPASS))
    bases.append(Path(__file__).resolve().parent.parent)
    for b in bases:
        f = b / "assets" / "PrumoPDF.ico"
        if f.exists():
            return f
    return None


def app_icon() -> QIcon:
    """
    Ícone do aplicativo: prumo branco sobre quadrado verde-petróleo (igual ao do iPhone).
    Usa o .ico com todos os tamanhos, para a barra de tarefas (16 a 32 px) mostrar o
    desenho nítido; se o arquivo faltar, desenha o mesmo ícone na hora.
    """
    f = _icon_file()
    if f is not None:
        ic = QIcon(str(f))
        if not ic.isNull() and ic.availableSizes():
            return ic
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(14, 124, 116))
    p.drawRoundedRect(8, 8, 240, 240, 54, 54)
    plumb = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
             'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1.5v5"/>'
             '<path d="M8.2 7.5h7.6c0 4.2-1.6 9-3.8 14.5C9.8 16.5 8.2 11.7 8.2 7.5z" fill="#FFFFFF"/></svg>')
    QSvgRenderer(QByteArray(plumb.encode())).render(p, QRectF(44, 36, 168, 184))
    p.end()
    return QIcon(pm)
