"""
Componentes no estilo do Prumo PDF para iPhone: cartões, busca, barra superior com
botões redondos, grade adaptável, alertas, folhas de opções, avisos e banner de OCR.
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QEventLoop, QObject, QPoint, QPointF, QPropertyAnimation,
                            QRect, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ios_theme import (DOC_TILE_HEIGHT, MARGIN, SPACING, TILE_HEIGHT, TILE_RADIUS, T, font,
                       glyph_icon, paint_glyph, paint_tile_icon)


def elide(text: str, f, width: int) -> str:
    return QFontMetrics(f).elidedText(text, Qt.ElideRight, max(10, width))


def wrap_lines(text: str, f, width: int, max_lines: int) -> list[str]:
    """Quebra o texto em até `max_lines` linhas; a última é cortada com reticências."""
    fm = QFontMetrics(f)
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if fm.horizontalAdvance(cand) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    if lines:
        lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
        lines = [fm.elidedText(l, Qt.ElideRight, width) for l in lines]
    return lines or [""]


def rounded(rect: QRectF, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def paint_badge(p: QPainter, x: float, y: float, text: str, color: QColor, inverted=False) -> float:
    """Selo em cápsula (OCR, Sem OCR, Revisar). Devolve a largura usada."""
    f = font(10, 700)
    w = QFontMetrics(f).horizontalAdvance(text) + 10
    r = QRectF(x, y, w, 15)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("white") if inverted else color)
    p.drawRoundedRect(r, 7.5, 7.5)
    p.setPen(color if inverted else QColor("white"))
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, text)
    return w


# --- Cartões ------------------------------------------------------------------

class TileBase(QAbstractButton):
    """Cartão com destaque ao clicar: o fundo assume a cor do ícone e o texto fica branco."""

    def __init__(self, color: str = "blue", parent=None):
        super().__init__(parent)
        self.color_name = color
        self.selected = False
        self.dimmed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.TabFocus)
        T.changed.connect(self.update)

    def highlighted(self) -> bool:
        return self.isDown() or self.selected

    def text_color(self) -> QColor:
        return QColor("white") if self.highlighted() else T.color("text")

    def secondary_color(self) -> QColor:
        return QColor(255, 255, 255, 230) if self.highlighted() else T.color("secondary")

    def paint_background(self, p: QPainter):
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.highlighted():
            bg = T.color(self.color_name)
        elif self.underMouse() and self.isEnabled():
            bg = T.color("tile_hover")
        else:
            bg = T.color("tile")
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, TILE_RADIUS, TILE_RADIUS)
        if self.hasFocus():
            p.setPen(QPen(T.color("blue"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), TILE_RADIUS - 1, TILE_RADIUS - 1)
        if self.dimmed:
            p.setOpacity(0.45)

    def icon_color(self) -> QColor:
        return QColor(255, 255, 255, 72) if self.highlighted() else T.color(self.color_name)

    def hasHeightForWidth(self):
        return True


class Tile(TileBase):
    """Ícone no alto à esquerda, contador à direita, título embaixo (como na tela do iPhone)."""

    def __init__(self, title: str, icon: str, color: str, count: str | None = None,
                 subtitle: str | None = None, rounded_icon: bool = False, parent=None):
        super().__init__(color, parent)
        self.title, self.icon, self.count, self.subtitle, self.rounded_icon = title, icon, count, subtitle, rounded_icon
        self.setAccessibleName(title)

    def set_content(self, title=None, count=None, subtitle=None):
        if title is not None:
            self.title = title
        self.count, self.subtitle = count, subtitle
        self.update()

    def heightForWidth(self, w):
        return TILE_HEIGHT + (14 if self.subtitle else 0)

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def paintEvent(self, _):
        p = QPainter(self)
        self.paint_background(p)
        paint_tile_icon(p, QRectF(12, 12, 32, 32), self.icon, self.icon_color(), self.rounded_icon)
        w = self.width()
        if self.count is not None:
            p.setFont(font(24, 700, display=True))
            p.setPen(self.text_color())
            p.drawText(QRectF(50, 6, w - 62, 40), Qt.AlignRight | Qt.AlignVCenter, self.count)
        bottom = self.height() - 12
        if self.subtitle:
            f = font(11.5, 500)
            p.setFont(f)
            p.setPen(self.secondary_color())
            p.drawText(QRectF(12, bottom - 15, w - 24, 15), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(self.subtitle, f, w - 24))
            bottom -= 16
        f = font(16, 600)
        p.setFont(f)
        p.setPen(self.text_color())
        p.drawText(QRectF(12, bottom - 21, w - 24, 21), Qt.AlignLeft | Qt.AlignVCenter, elide(self.title, f, w - 24))


class WideTile(TileBase):
    """Cartão de largura total (como "Pastas" na tela inicial)."""

    def __init__(self, title: str, icon: str | None = None, color: str = "gray", count: str | None = None,
                 subtitle: str | None = None, parent=None):
        super().__init__(color, parent)
        self.title, self.icon, self.count, self.subtitle = title, icon, count, subtitle
        self.setAccessibleName(title)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_content(self, title=None, count=None, subtitle=None):
        if title is not None:
            self.title = title
        self.count, self.subtitle = count, subtitle
        self.updateGeometry()
        self.update()

    def heightForWidth(self, w):
        if not self.subtitle:
            return 54
        x = 12 + (40 if self.icon else 2)
        lines = wrap_lines(self.subtitle, font(12, 500), w - x - 60, 2)
        return 40 + 16 * len(lines)

    def sizeHint(self):
        return QSize(300, self.heightForWidth(max(300, self.width())))

    def resizeEvent(self, e):
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        self.paint_background(p)
        w, h = self.width(), self.height()
        x = 14
        if self.icon:
            paint_tile_icon(p, QRectF(14, (h - 28) / 2, 28, 28), self.icon, self.icon_color(), False)
            x = 54
        right = w - 14
        if self.count is not None:
            p.setFont(font(24, 700, display=True))
            p.setPen(self.text_color())
            p.drawText(QRectF(right - 70, 0, 70, h), Qt.AlignRight | Qt.AlignVCenter, self.count)
            right -= 76
        tf = font(16, 600)
        if self.subtitle:
            lines = wrap_lines(self.subtitle, font(12, 500), right - x, 2)
            total = 21 + 2 + 16 * len(lines)
            y = (h - total) / 2
            p.setFont(tf)
            p.setPen(self.text_color())
            p.drawText(QRectF(x, y, right - x, 21), Qt.AlignLeft | Qt.AlignVCenter, elide(self.title, tf, right - x))
            p.setFont(font(12, 500))
            p.setPen(self.secondary_color())
            for i, line in enumerate(lines):
                p.drawText(QRectF(x, y + 23 + 16 * i, right - x, 16), Qt.AlignLeft | Qt.AlignVCenter, line)
        else:
            p.setFont(tf)
            p.setPen(self.text_color())
            p.drawText(QRectF(x, 0, right - x, h), Qt.AlignLeft | Qt.AlignVCenter, elide(self.title, tf, right - x))


class Thumb:
    """Desenha a miniatura da primeira página (ou a indicada), pedindo ao serviço quando faltar."""

    def __init__(self, owner: QWidget, thumbs):
        self.owner, self.thumbs, self.key = owner, thumbs, None
        thumbs.ready.connect(self._ready)
        owner.destroyed.connect(self._disconnect)   # a tela fechou: para de ouvir as miniaturas

    def _disconnect(self, *_):
        try:
            self.thumbs.ready.disconnect(self._ready)
        except (RuntimeError, TypeError):
            pass

    def _ready(self, key):
        if key == self.key:
            try:
                self.owner.update()
            except RuntimeError:   # a tela já foi apagada
                self._disconnect()

    def paint(self, p: QPainter, rect: QRectF, path, version, page=0, radius=4.0):
        dpr = self.owner.devicePixelRatioF()
        px = int(rect.width() * dpr * 1.0)
        img = self.thumbs.get(path, version, page, px)
        self.key = self.thumbs.key(path, version, page, max(16, px))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # sombra leve
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 22))
        p.drawRoundedRect(rect.translated(0, 1), radius, radius)
        clip = rounded(rect, radius)
        p.setClipPath(clip)
        p.fillRect(rect, QColor("white"))
        if img is not None and not img.isNull():
            ir = QRectF(img.rect())
            scale = min(rect.width() / ir.width(), rect.height() / ir.height())
            tw, th = ir.width() * scale, ir.height() * scale
            target = QRectF(rect.x() + (rect.width() - tw) / 2, rect.y() + (rect.height() - th) / 2, tw, th)
            p.drawImage(target, img)
        p.setClipping(False)
        p.setPen(QPen(T.color("thumb_border"), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.restore()


class DocTile(TileBase):
    """
    Cartão de PDF: miniatura, número de páginas, nome e selos. No canto inferior direito,
    a estrela de favorito (vazia ou preenchida) e os três pontos que abrem as opções.
    """

    star_clicked = Signal()
    menu_clicked = Signal()

    ACTION_ROW = 30

    def __init__(self, item, thumbs, needs_ocr=False, show_folder=False, show_actions=True, parent=None):
        super().__init__("blue", parent)
        self.item, self.needs_ocr, self.show_folder = item, needs_ocr, show_folder
        self.show_actions = show_actions
        self.selection: bool | None = None
        self.busy = False
        self.thumb = Thumb(self, thumbs)
        self._hover: str | None = None
        self._press: str | None = None
        self.setMouseTracking(True)
        self.setAccessibleName(item.name)

    def set_selection(self, value: bool | None):
        self.selection = value
        self.selected = bool(value)
        self.update()

    # --- estrela e três pontos ---
    def actions_visible(self) -> bool:
        return self.show_actions and self.selection is None

    def star_rect(self) -> QRectF:
        return QRectF(self.width() - 70, self.height() - 8 - self.ACTION_ROW, 32, self.ACTION_ROW)

    def dots_rect(self) -> QRectF:
        return QRectF(self.width() - 38, self.height() - 8 - self.ACTION_ROW, 30, self.ACTION_ROW)

    def _target(self, pos) -> str | None:
        if not self.actions_visible():
            return None
        pt = QPointF(pos)
        if self.star_rect().contains(pt):
            return "star"
        if self.dots_rect().contains(pt):
            return "dots"
        return None

    def mousePressEvent(self, e):
        t = self._target(e.position()) if e.button() == Qt.LeftButton else None
        if t:
            self._press = t
            self.update()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press:
            t, self._press = self._press, None
            self.update()
            if self._target(e.position()) == t:
                (self.star_clicked if t == "star" else self.menu_clicked).emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        t = self._target(e.position())
        if t != self._hover:
            self._hover = t
            self.setToolTip({"star": "Remover dos favoritos" if self.item.meta.favorite else "Favoritar",
                             "dots": "Opções"}.get(t, ""))
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def _paint_actions(self, p: QPainter):
        light = self.highlighted()
        for key, r in (("star", self.star_rect()), ("dots", self.dots_rect())):
            if self._hover == key or self._press == key:
                c = QColor(255, 255, 255, 60) if light else QColor(T.color("text"))
                if not light:
                    c.setAlpha(40 if self._press == key else 22)
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(r.adjusted(2, 1, -2, -1), 8, 8)
        sr = self.star_rect()
        icon = QRectF(sr.center().x() - 10, sr.center().y() - 10, 20, 20)
        fav = self.item.meta.favorite
        if fav:
            paint_glyph(p, icon, "star", QColor("white") if light else T.color("yellow"), 1.2)
        else:
            paint_glyph(p, icon, "star_line", QColor("white") if light else T.color("secondary"), 1.6)
        dr = self.dots_rect()
        c = QColor("white") if light else T.color("secondary")
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        cx = dr.center().x()
        for dy in (-6, 0, 6):
            p.drawEllipse(QPointF(cx, dr.center().y() + dy), 2.0, 2.0)

    def _badges(self):
        m = self.item.meta
        out = []
        if getattr(m, "locked", False):
            out.append(("Com senha", "purple"))
        if m.is_ocr_result:
            out.append(("OCR", "green"))
        if m.review_pages:
            out.append(("Revisar", "orange"))
        if self.needs_ocr:
            out.append(("Sem OCR", "orange"))
        return out

    def heightForWidth(self, w):
        # A linha de baixo (selos à esquerda, estrela e três pontos à direita) existe sempre,
        # para todos os cartões terem a mesma altura e a estrela ficar sempre no mesmo lugar.
        lines = wrap_lines(self.item.name, font(15, 600), w - 24, 2)
        h = 12 + 44 + 8 + 19 * len(lines) + 4 + self.ACTION_ROW + 8
        return max(DOC_TILE_HEIGHT, h)

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def paintEvent(self, _):
        p = QPainter(self)
        self.paint_background(p)
        w, h = self.width(), self.height()
        self.thumb.paint(p, QRectF(12, 12, 34, 44), self.item.path, self.item.version)
        if getattr(self.item.meta, "locked", False):   # PDF com senha: cadeado sobre a miniatura
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("purple"))
            p.drawEllipse(QRectF(17, 22, 24, 24))
            paint_glyph(p, QRectF(21, 26, 16, 16), "lock", QColor("white"), 1.6)
        # canto superior direito: seleção, número de páginas ou "analisando"
        if self.selection is not None:
            r = QRectF(w - 36, 12, 24, 24)
            p.setPen(Qt.NoPen)
            if self.selection:
                p.setBrush(QColor("white"))
                p.drawEllipse(r)
                paint_glyph(p, r.adjusted(4, 4, -4, -4), "check", T.color("blue"), 3)
            else:
                p.setPen(QPen(T.color("secondary"), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(r.adjusted(1, 1, -1, -1))
        elif self.item.page_count is not None:
            n = self.item.page_count
            p.setFont(font(24, 700, display=True))
            p.setPen(self.text_color())
            p.drawText(QRectF(54, 6, w - 66, 32), Qt.AlignRight | Qt.AlignVCenter, str(n))
            p.setFont(font(10.5, 500))
            p.setPen(self.secondary_color())
            p.drawText(QRectF(54, 36, w - 66, 14), Qt.AlignRight | Qt.AlignVCenter, "página" if n == 1 else "páginas")
        elif getattr(self.item.meta, "locked", False):
            paint_glyph(p, QRectF(w - 34, 14, 22, 22), "lock", self.secondary_color(), 1.6)
        else:
            p.setPen(QPen(self.secondary_color(), 2))
            p.drawArc(QRectF(w - 30, 16, 16, 16), 90 * 16, 270 * 16)
        # linha de baixo: selos e pasta à esquerda; estrela e três pontos à direita
        row_top = h - 8 - self.ACTION_ROW
        limit = w - (74 if self.actions_visible() else 12)
        x = 12.0
        yb = row_top + (self.ACTION_ROW - 15) / 2
        if not self.actions_visible() and self.item.meta.favorite:
            paint_glyph(p, QRectF(x - 1, yb + 1, 13, 13), "star",
                        QColor("white") if self.highlighted() else T.color("yellow"), 1.2)
            x += 15
        for text, color in self._badges():
            bw = QFontMetrics(font(10, 700)).horizontalAdvance(text) + 10
            if x + bw > limit:
                break
            x += paint_badge(p, x, yb, text, T.color(color), self.highlighted()) + 4
        if self.show_folder and limit - x > 24:
            f = font(10.5, 500)
            p.setFont(f)
            p.setPen(self.secondary_color())
            p.drawText(QRectF(x, yb, limit - x, 15), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(self.item.folder_name, f, int(limit - x)))
        if self.actions_visible():
            self._paint_actions(p)
        y_bottom = row_top - 4
        f = font(15, 600)
        lines = wrap_lines(self.item.name, f, w - 24, 2)
        p.setFont(f)
        p.setPen(self.text_color())
        y = y_bottom - 19 * len(lines)
        for i, line in enumerate(lines):
            p.drawText(QRectF(12, y + 19 * i, w - 24, 19), Qt.AlignLeft | Qt.AlignVCenter, line)


class TileCard(QFrame):
    """Área de cartão sem ação (opções, informações)."""

    def __init__(self, parent=None, padding=14):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(8)
        T.changed.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("tile"))
        p.drawRoundedRect(QRectF(self.rect()), TILE_RADIUS, TILE_RADIUS)


class Label(QLabel):
    """Texto com fonte e cor do tema (a cor acompanha o modo claro/escuro)."""

    def __init__(self, text="", px=14, weight=400, role="text", wrap=True, parent=None):
        super().__init__(text, parent)
        self.role = role
        self.setFont(font(px, weight))
        self.setWordWrap(wrap)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self._apply()
        T.changed.connect(self._apply)

    def _apply(self):
        c = T.color(self.role) if self.role in ("text", "secondary", "placeholder") else T.color(self.role)
        self.setStyleSheet(f"color: {c.name()}; background: transparent;")


class SectionTitle(Label):
    def __init__(self, text):
        super().__init__(text.upper(), 13, 600, "secondary", wrap=False)
        self.setContentsMargins(4, 6, 4, 0)


class PrimaryButton(QAbstractButton):
    def __init__(self, title: str, color: str = "blue", parent=None):
        super().__init__(parent)
        self.title, self.color_name = title, color
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        T.changed.connect(self.update)

    def set_title(self, t):
        self.title = t
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(T.color(self.color_name))
        if not self.isEnabled():
            c.setAlpha(90)
        elif self.isDown():
            c = c.darker(115)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setPen(QColor(255, 255, 255, 255 if self.isEnabled() else 200))
        p.setFont(font(17, 600))
        p.drawText(self.rect(), Qt.AlignCenter, self.title)


class EmptyState(QWidget):
    """
    Ícone, título e mensagem centralizados. A mensagem é desenhada aqui mesmo, com a
    altura calculada para a largura disponível: um QLabel com quebra de linha dentro de
    um layout com alinhamento recebia a altura de uma linha só e ficava "esmagado".
    """

    MAX_TEXT = 440

    def __init__(self, icon: str, title: str, message: str):
        super().__init__()
        self.icon, self.title, self.message = icon, title, message
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        T.changed.connect(self.update)

    def _text_width(self, w: int) -> int:
        return max(120, min(self.MAX_TEXT, w - 48))

    def _lines(self, w: int) -> list[str]:
        return wrap_lines(self.message, font(14), self._text_width(w), 8) if self.message else []

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return 40 + 52 + 6 + 28 + 6 + 20 * len(self._lines(w)) + 24

    def sizeHint(self):
        return QSize(400, self.heightForWidth(max(400, self.width())))

    def resizeEvent(self, e):
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        paint_glyph(p, QRectF((w - 44) / 2, 44, 44, 44), self.icon, T.color("placeholder"), 1.9)
        y = 40 + 52 + 6
        p.setPen(T.color("text"))
        p.setFont(font(20, 700))
        p.drawText(QRectF(0, y, w, 28), Qt.AlignCenter, self.title)
        y += 28 + 6
        p.setPen(T.color("secondary"))
        p.setFont(font(14))
        tw = self._text_width(w)
        for line in self._lines(w):
            p.drawText(QRectF((w - tw) / 2, y, tw, 20), Qt.AlignCenter, line)
            y += 20


# --- Grade adaptável ----------------------------------------------------------

class FlowGrid(QWidget):
    """Grade de cartões: 2 colunas numa janela estreita (como no iPhone), mais colunas numa janela larga."""

    def __init__(self, min_col: int = 200, max_cols: int = 6, parent=None):
        super().__init__(parent)
        self.min_col, self.max_cols = min_col, max_cols
        self.items: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def add(self, w: QWidget):
        w.setParent(self)
        w.show()
        self.items.append(w)
        self._relayout()

    def clear(self):
        for w in self.items:
            w.setParent(None)
            w.deleteLater()
        self.items = []
        self._relayout()

    def columns(self, width: int) -> int:
        cols = max(2, min(self.max_cols, (width + SPACING) // (self.min_col + SPACING)))
        if self.max_cols == 4 and cols == 3:
            cols = 2   # a tela inicial fica com linhas completas
        return cols

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(width, apply=False)

    def sizeHint(self):
        return QSize(400, self._layout(max(400, self.width()), apply=False))

    def resizeEvent(self, e):
        self._relayout()

    def _relayout(self):
        h = self._layout(self.width(), apply=True)
        if self.minimumHeight() != h:
            self.setFixedHeight(h)

    def _layout(self, width: int, apply: bool) -> int:
        visible = [w for w in self.items if not w.isHidden()]
        if not visible or width <= 0:
            return 0
        cols = self.columns(width)
        cw = (width - SPACING * (cols - 1)) / cols
        y = 0
        for r in range(0, len(visible), cols):
            row = visible[r:r + cols]
            rh = max(w.heightForWidth(int(cw)) if w.hasHeightForWidth() else w.sizeHint().height() for w in row)
            if apply:
                for i, w in enumerate(row):
                    w.setGeometry(QRect(round(i * (cw + SPACING)), y, round(cw), rh))
            y += rh + SPACING
        return y - SPACING


# --- Busca --------------------------------------------------------------------

class SearchField(QWidget):
    textChanged = Signal(str)
    debounced = Signal(str)

    def __init__(self, placeholder="Buscar", parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(38, 0, 6, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(font(17))
        self.edit.setFrame(False)
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(lambda: self.debounced.emit(self.edit.text()))
        self.edit.textChanged.connect(self.textChanged)
        self.edit.textChanged.connect(lambda _t: self.timer.start())
        self._apply()
        T.changed.connect(self._apply)

    def _apply(self):
        self.edit.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; padding: 0; "
                                f"color: {T.hex('text')}; font-size: 17px; }}")
        pal = self.edit.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, T.color("placeholder"))
        self.edit.setPalette(pal)
        self.update()

    def text(self) -> str:
        return self.edit.text()

    def setText(self, t: str):
        self.edit.setText(t)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("search"))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)
        paint_glyph(p, QRectF(11, 10, 20, 20), "search", T.color("text"), 2)

    def mousePressEvent(self, e):
        self.edit.setFocus()


# --- Barra superior -----------------------------------------------------------

class CircleButton(QAbstractButton):
    """Botão redondo da barra superior (voltar, ajustes, mais opções)."""

    def __init__(self, glyph: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setAttribute(Qt.WA_Hover)
        T.changed.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("shadow"))
        p.drawEllipse(r.translated(0, 1))
        bg = QColor(T.color("panel"))
        if self.isDown():
            bg = bg.darker(110)
        elif self.underMouse():
            bg = bg.darker(104) if not T.dark else bg.lighter(120)
        p.setBrush(bg)
        p.drawEllipse(r)
        paint_glyph(p, r.adjusted(10, 10, -10, -10), self.glyph, T.color("text"), 2)


class TextButton(QAbstractButton):
    """Botão de texto da barra (OK, Cancelar) no formato de cápsula."""

    def __init__(self, title: str, bold=False, parent=None):
        super().__init__(parent)
        self.title, self.bold = title, bold
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        T.changed.connect(self.update)
        self._resize()

    def set_title(self, t):
        self.title = t
        self._resize()
        self.update()

    def _resize(self):
        self.setFixedWidth(QFontMetrics(font(16, 600)).horizontalAdvance(self.title) + 32)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("shadow"))
        p.drawRoundedRect(r.translated(0, 1), r.height() / 2, r.height() / 2)
        bg = QColor(T.color("panel"))
        p.setBrush(bg.darker(110) if self.isDown() else bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        c = QColor(T.color("blue") if self.isEnabled() else T.color("placeholder"))
        p.setPen(c)
        p.setFont(font(16, 600 if self.bold else 500))
        p.drawText(r, Qt.AlignCenter, self.title)


class NavBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(MARGIN, 8, MARGIN, 8)
        self.lay.setSpacing(10)
        self.left = QHBoxLayout()
        self.right = QHBoxLayout()
        self.right.setSpacing(10)
        self.title = Label("", 17, 600, wrap=False)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addLayout(self.left)
        self.lay.addWidget(self.title, 1)
        self.lay.addLayout(self.right)

    def set_title(self, t: str):
        self.title.setText(t)


# --- Tela base ----------------------------------------------------------------

class Screen(QWidget):
    """Tela com barra superior, título grande opcional e conteúdo com rolagem."""

    title = ""
    large_title = True

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("screen")
        self.setAttribute(Qt.WA_StyledBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.nav = NavBar()
        outer.addWidget(self.nav)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("scrollBody")
        self.body.setAttribute(Qt.WA_StyledBackground)
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(MARGIN, 0, MARGIN, 110)
        self.content.setSpacing(SPACING)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self.big_title = Label("", 34, 700, wrap=False)
        self.big_title.setFont(font(34, 700, display=True))
        self.big_title.setContentsMargins(0, 0, 0, 2)
        self.content.addWidget(self.big_title)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)

    def set_title(self, t: str):
        self.title = t
        self.big_title.setText(t)
        self.big_title.setVisible(self.large_title)
        self._scrolled(self.scroll.verticalScrollBar().value())

    def _scrolled(self, v: int):
        # Como no iOS: o título pequeno aparece quando o título grande sai da tela.
        show = (not self.large_title) or v > 40
        self.nav.set_title(self.title if show else "")

    def add_back(self):
        b = CircleButton("back", "Voltar (Alt+←)")
        b.clicked.connect(self.app.back)
        self.nav.left.addWidget(b)

    def finish_content(self):
        self.content.addStretch(1)

    def refresh(self):
        """Redesenha a tela com os dados atuais da biblioteca."""

    def on_shown(self):
        self.refresh()

    def clear_after_title(self, keep: int = 1):
        """Remove os widgets do conteúdo depois dos `keep` primeiros (título, busca)."""
        while self.content.count() > keep:
            it = self.content.takeAt(keep)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()


# --- Diálogos (alerta, folha de opções, campo de texto) ----------------------

class _Overlay(QWidget):
    """Camada escura sobre a janela, com um painel no centro (como os alertas do iOS)."""

    def __init__(self, window: QWidget, panel_width=300):
        super().__init__(window)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setGeometry(window.rect())
        self.panel = QFrame(self)
        self.panel.setObjectName("alertPanel")
        self.panel.setFixedWidth(panel_width)
        self.panel.setStyleSheet(f"#alertPanel {{ background: {T.hex('panel')}; border-radius: 16px; }}")
        sh = QGraphicsDropShadowEffect(self.panel)
        sh.setBlurRadius(40)
        sh.setOffset(0, 8)
        sh.setColor(QColor(0, 0, 0, 90))
        self.panel.setGraphicsEffect(sh)
        self.lay = QVBoxLayout(self.panel)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.result = None
        self.loop = QEventLoop()
        window.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
            self._place()
        return False

    def _place(self):
        self.panel.adjustSize()
        self.panel.move((self.width() - self.panel.width()) // 2, (self.height() - self.panel.height()) // 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), T.color("dim"))

    def mousePressEvent(self, e):
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.done(None)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.done(None)
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and getattr(self, "default", None) is not None:
            self.done(self.default)
        else:
            super().keyPressEvent(e)

    def done(self, value):
        self.result = value
        self.loop.quit()

    def run(self):
        self._place()
        self.show()
        self.raise_()
        self.setFocus()
        focus = getattr(self, "focus_widget", None)
        if focus is not None:
            focus.setFocus()
        self.loop.exec()
        self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()
        return self.result


def _alert_button(text: str, role: str, bold: bool) -> QPushButton:
    b = QPushButton(text)
    color = T.color("red") if role == "destructive" else T.color("blue")
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(46)
    b.setFont(font(17, 600 if bold else 400))
    b.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {color.name()}; padding: 0 10px; }}"
                    f"QPushButton:hover {{ background: {T.hex('tile')}; }}"
                    f"QPushButton:pressed {{ background: {T.hex('tile_hover')}; }}")
    return b


def _line(vertical=False) -> QFrame:
    f = QFrame()
    if vertical:
        f.setFixedWidth(1)
    else:
        f.setFixedHeight(1)
    f.setStyleSheet(f"background: {T.hex('panel_line')};")
    return f


def alert(window: QWidget, title: str, message: str = "", buttons=(("OK", "default"),),
          text: str | None = None, placeholder: str = "", validator=None, secret: bool = False):
    """
    Alerta no estilo iOS. `buttons` é uma lista de (texto, papel), com papel
    "cancel", "default" ou "destructive". Devolve o índice do botão (ou None se fechar),
    e, com `text`, o par (índice, texto digitado).
    """
    ov = _Overlay(window.window(), 300)
    head = QVBoxLayout()
    head.setContentsMargins(18, 20, 18, 16)
    head.setSpacing(4)
    t = QLabel(title)
    t.setFont(font(17, 600))
    t.setWordWrap(True)
    t.setAlignment(Qt.AlignCenter)
    t.setStyleSheet(f"color: {T.hex('text')}; background: transparent;")
    head.addWidget(t)
    if message:
        m = QLabel(message)
        m.setFont(font(13))
        m.setWordWrap(True)
        m.setAlignment(Qt.AlignCenter)
        m.setStyleSheet(f"color: {T.hex('text')}; background: transparent;")
        head.addWidget(m)
    edit = None
    if text is not None:
        edit = QLineEdit(text)
        edit.setPlaceholderText(placeholder)
        if secret:
            edit.setEchoMode(QLineEdit.Password)   # senha: mostra só pontinhos
        edit.setFont(font(15))
        edit.setStyleSheet(f"QLineEdit {{ background: {T.hex('bg')}; border: 1px solid {T.hex('panel_line')}; "
                           f"border-radius: 8px; padding: 7px 9px; font-size: 15px; color: {T.hex('text')}; }}")
        edit.selectAll()
        head.addSpacing(10)
        head.addWidget(edit)
        ov.focus_widget = edit
    ov.lay.addLayout(head)
    ov.lay.addWidget(_line())
    horizontal = len(buttons) == 2 and all(len(b[0]) <= 14 for b in buttons)
    row = QHBoxLayout() if horizontal else QVBoxLayout()
    row.setSpacing(0)
    btns = []
    default_index = None
    for i, (label, role) in enumerate(buttons):
        b = _alert_button(label, role, role in ("default",) or (role == "destructive" and len(buttons) == 1))
        if role == "default" and default_index is None:
            default_index = i
        b.clicked.connect(lambda _c=False, i=i: ov.done(i))
        if i and horizontal:
            row.addWidget(_line(True))
        elif i:
            row.addWidget(_line())
        row.addWidget(b, 1)
        btns.append((b, role))
    ov.lay.addLayout(row)
    ov.default = default_index
    if edit is not None:
        def check(_=None):
            ok = validator(edit.text()) if validator else bool(edit.text().strip())
            for b, role in btns:
                if role != "cancel":
                    b.setEnabled(ok)
        edit.textChanged.connect(check)
        check()
        edit.returnPressed.connect(lambda: ov.done(default_index) if (validator(edit.text()) if validator
                                                                      else edit.text().strip()) else None)
    result = ov.run()
    if text is not None:
        return result, (edit.text() if edit is not None else "")
    return result


def action_sheet(window: QWidget, title: str, message: str = "", actions=(), cancel="Cancelar"):
    """
    Lista de opções (como o confirmationDialog do iOS). `actions` é uma lista de
    (texto, papel, glifo opcional). Devolve o índice escolhido ou None.
    """
    ov = _Overlay(window.window(), 340)
    if title or message:
        head = QVBoxLayout()
        head.setContentsMargins(18, 16, 18, 14)
        head.setSpacing(4)
        if title:
            t = QLabel(title)
            t.setFont(font(14, 600))
            t.setAlignment(Qt.AlignCenter)
            t.setWordWrap(True)
            t.setStyleSheet(f"color: {T.hex('secondary')}; background: transparent;")
            head.addWidget(t)
        if message:
            m = QLabel(message)
            m.setFont(font(13))
            m.setAlignment(Qt.AlignCenter)
            m.setWordWrap(True)
            m.setStyleSheet(f"color: {T.hex('secondary')}; background: transparent;")
            head.addWidget(m)
        ov.lay.addLayout(head)
    for i, a in enumerate(actions):
        label, role = a[0], a[1]
        ov.lay.addWidget(_line())
        b = _alert_button(label, role, False)
        b.setMinimumHeight(52)
        b.setFont(font(17, 400))
        if len(a) > 2 and a[2]:
            color = T.color("red") if role == "destructive" else T.color("blue")
            b.setIcon(glyph_icon(a[2], color, 20))
            b.setIconSize(QSize(20, 20))
        b.clicked.connect(lambda _c=False, i=i: ov.done(i))
        ov.lay.addWidget(b)
    if cancel:
        ov.lay.addWidget(_line())
        c = _alert_button(cancel, "cancel", True)
        c.setMinimumHeight(52)
        c.clicked.connect(lambda: ov.done(None))
        ov.lay.addWidget(c)
    return ov.run()


class BusyOverlay(_Overlay):
    """Aviso de trabalho em andamento (ex.: "Convertendo 2 de 5…"), sem botões."""

    def __init__(self, window: QWidget, title: str):
        super().__init__(window.window(), 320)
        box = QVBoxLayout()
        box.setContentsMargins(22, 22, 22, 22)
        box.setSpacing(12)
        self.title = QLabel(title)
        self.title.setFont(font(16, 600))
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"color: {T.hex('text')}; background: transparent;")
        self.detail = QLabel("")
        self.detail.setFont(font(13))
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {T.hex('secondary')}; background: transparent;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)   # indeterminada até saber o total
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        box.addWidget(self.title)
        box.addWidget(self.detail)
        box.addWidget(self.bar)
        self.lay.addLayout(box)

    def mousePressEvent(self, e):
        pass   # não fecha ao clicar fora

    def keyPressEvent(self, e):
        pass   # nem com Esc: o trabalho está rodando

    def set_progress(self, done: int, total: int, detail: str):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.detail.setText(detail)
        self._place()


class LockOverlay(QWidget):
    """Tela de trava: cobre a janela inteira até a senha certa ser digitada."""

    unlocked = Signal()

    def __init__(self, window: QWidget, verify, on_forgot):
        super().__init__(window)
        self.verify = verify
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setGeometry(window.rect())
        box = QFrame(self)
        box.setObjectName("lockBox")
        box.setFixedWidth(340)
        box.setStyleSheet(f"#lockBox {{ background: {T.hex('panel')}; border-radius: 18px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(26, 26, 26, 22)
        lay.setSpacing(12)
        from ios_theme import app_icon
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(72, 72))
        logo.setAlignment(Qt.AlignCenter)
        padlock = QLabel()
        padlock.setPixmap(glyph_icon("lock", T.color("purple"), 30).pixmap(30, 30))
        padlock.setAlignment(Qt.AlignCenter)
        title = QLabel("Prumo PDF está bloqueado")
        title.setFont(font(18, 700))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {T.hex('text')}; background: transparent;")
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.Password)
        self.field.setPlaceholderText("Senha do Prumo")
        self.field.setFont(font(16))
        self.field.returnPressed.connect(self._try)
        self.error = QLabel("")
        self.error.setFont(font(13, 500))
        self.error.setAlignment(Qt.AlignCenter)
        self.error.setStyleSheet(f"color: {T.color('red').name()}; background: transparent;")
        button = PrimaryButton("Desbloquear", "blue")
        button.clicked.connect(self._try)
        forgot = QPushButton("Esqueci a senha")
        forgot.setCursor(Qt.PointingHandCursor)
        forgot.setFont(font(13, 500))
        forgot.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {T.color('blue').name()}; }}")
        forgot.clicked.connect(on_forgot)
        for w in (logo, padlock, title, self.field, self.error, button, forgot):
            lay.addWidget(w)
        self.box = box
        self.credit = QLabel("Color Software", self)
        self.credit.setFont(font(12, 600))
        self.credit.setAlignment(Qt.AlignCenter)
        self.credit.setStyleSheet(f"color: {T.hex('secondary')}; background: transparent;")
        window.installEventFilter(self)
        self._place()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
            self._place()
        return False

    def _place(self):
        """O conjunto fica abaixo do meio da janela (sem encostar no crédito do pé)."""
        self.box.adjustSize()
        free = self.height() - self.box.height() - 60
        top = max(16, int(free * 0.68)) if free > 0 else max(0, (self.height() - self.box.height()) // 2)
        self.box.move((self.width() - self.box.width()) // 2, top)
        self.credit.setGeometry(0, self.height() - 44, self.width(), 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), T.color("bg"))

    def mousePressEvent(self, e):
        self.field.setFocus()

    def show_lock(self):
        self.field.clear()
        self.error.setText("")
        self.setGeometry(self.parentWidget().rect())
        self._place()
        self.show()
        self.raise_()
        self.field.setFocus()

    def _try(self):
        if self.verify(self.field.text()):
            self.hide()
            self.field.clear()
            self.unlocked.emit()
        else:
            self.error.setText("Senha incorreta.")
            self.field.selectAll()


class SheetOverlay(_Overlay):
    """Painel maior (tela modal), para escolher pasta, dividir etc."""

    def __init__(self, window: QWidget, width=420, max_height=None):
        super().__init__(window.window(), width)
        self.max_height = max_height

    def _place(self):
        self.panel.adjustSize()
        h = self.panel.sizeHint().height()
        limit = int(self.height() * 0.86) if self.max_height is None else min(self.max_height, int(self.height() * 0.86))
        self.panel.setFixedHeight(min(h, limit))
        self.panel.move((self.width() - self.panel.width()) // 2, (self.height() - self.panel.height()) // 2)


def sheet_header(ov: SheetOverlay, title: str, cancel="Cancelar", confirm: str | None = None):
    """Cabeçalho com Cancelar à esquerda, título no meio e confirmação à direita."""
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(10, 10, 10, 6)
    c = QPushButton(cancel)
    c.setCursor(Qt.PointingHandCursor)
    c.setFont(font(16))
    c.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {T.color('blue').name()}; padding: 6px; }}")
    c.clicked.connect(lambda: ov.done(None))
    t = QLabel(title)
    t.setFont(font(16, 600))
    t.setAlignment(Qt.AlignCenter)
    t.setStyleSheet(f"color: {T.hex('text')}; background: transparent;")
    lay.addWidget(c)
    lay.addWidget(t, 1)
    ok = None
    if confirm:
        ok = QPushButton(confirm)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFont(font(16, 600))
        ok.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {T.color('blue').name()}; padding: 6px; }}"
                         f"QPushButton:disabled {{ color: {T.hex('placeholder')}; }}")
        lay.addWidget(ok)
    else:
        sp = QWidget()
        sp.setFixedWidth(c.sizeHint().width())
        lay.addWidget(sp)
    ov.lay.addWidget(bar)
    return ok


# --- Avisos na parte de baixo -------------------------------------------------

class Toast(QFrame):
    """Aviso rápido no pé da janela, com ação opcional (Abrir, Ver)."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        lay.setSpacing(12)
        self.text = QLabel()
        self.text.setFont(font(14, 500))
        self.text.setWordWrap(True)
        self.action = QPushButton()
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.setFont(font(14, 700))
        lay.addWidget(self.text, 1)
        lay.addWidget(self.action)
        self._cb = None
        self.action.clicked.connect(self._act)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def _act(self):
        cb, self._cb = self._cb, None
        self.hide()
        if cb:
            cb()

    def show_message(self, text: str, action: str | None = None, callback=None, ms: int = 4500):
        dark_bg = "rgba(40,40,42,235)" if not T.dark else "rgba(230,230,232,240)"
        fg = "white" if not T.dark else "#1c1c1e"
        self.setStyleSheet(f"#toast {{ background: {dark_bg}; border-radius: 14px; }}"
                           f"QLabel {{ color: {fg}; background: transparent; }}"
                           f"QPushButton {{ color: {'#6FB1FF' if not T.dark else '#0A60D8'}; background: transparent; border: none; padding: 4px 8px; }}")
        self.text.setText(text)
        self.action.setVisible(bool(action))
        self.action.setText(action or "")
        self._cb = callback
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start(ms + (2500 if action else 0))

    def reposition(self, bottom_offset: int = 0):
        w = self.parentWidget()
        width = min(560, w.width() - 2 * MARGIN)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move((w.width() - width) // 2, w.height() - self.height() - 18 - bottom_offset)


class JobBanner(QFrame):
    """Banner do OCR em andamento (nome do PDF, etapa e barra de progresso)."""

    cancel_requested = Signal()

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(30, 30)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel()
        self.title.setFont(font(14, 600))
        self.detail = QLabel()
        self.detail.setFont(font(12))
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        col.addWidget(self.bar)
        self.stop = QPushButton("Cancelar")
        self.stop.setCursor(Qt.PointingHandCursor)
        self.stop.setFont(font(14, 600))
        self.stop.clicked.connect(self.cancel_requested)
        lay.addWidget(self.icon)
        lay.addLayout(col, 1)
        lay.addWidget(self.stop)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(24)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(sh)
        self.hide()

    def update_job(self, name: str, stage: str, fraction: float, queued: int):
        self.setStyleSheet(f"#banner {{ background: {T.hex('panel')}; border-radius: 14px; }}"
                           f"QLabel {{ background: transparent; color: {T.hex('text')}; }}"
                           f"QPushButton {{ background: transparent; border: none; color: {T.color('red').name()}; padding: 4px 8px; }}")
        pm = glyph_icon("textscan", QColor("white"), 18).pixmap(18, 18)
        from PySide6.QtGui import QPixmap
        base = QPixmap(60, 60)
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.Antialiasing)
        paint_tile_icon(p, QRectF(0, 0, 60, 60), "textscan", T.color("orange"), True)
        p.end()
        base.setDevicePixelRatio(2)
        self.icon.setPixmap(base)
        self.title.setText(f"OCR: {name}")
        extra = f" · mais {queued} na fila" if queued else ""
        self.detail.setText(f"{stage}{extra}")
        self.detail.setStyleSheet(f"color: {T.hex('secondary')}; background: transparent;")
        self.bar.setValue(int(fraction * 1000))
        self.reposition()
        self.show()
        self.raise_()

    def reposition(self):
        w = self.parentWidget()
        width = min(560, w.width() - 2 * MARGIN)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move((w.width() - width) // 2, w.height() - self.height() - 18)


class WheelGuard(QObject):
    """
    A roda do mouse rola a tela e não muda caixas de seleção ou números por onde o cursor passa
    (no Qt, girar a roda sobre uma caixa troca o item escolhido). A caixa só responde à roda
    depois de clicada.
    """

    def eventFilter(self, obj, ev):
        from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox
        if ev.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox)):
            if obj.focusPolicy() == Qt.WheelFocus:
                obj.setFocusPolicy(Qt.StrongFocus)
            if not obj.hasFocus():
                area = obj.parentWidget()
                while area is not None and not isinstance(area, QAbstractScrollArea):
                    area = area.parentWidget()
                if area is not None:
                    QApplication.sendEvent(area.verticalScrollBar(), ev)
                return True
        return False


def install_wheel_guard(app) -> "WheelGuard":
    guard = getattr(app, "_prumo_wheel_guard", None)
    if guard is None:
        guard = WheelGuard(app)
        app.installEventFilter(guard)
        app._prumo_wheel_guard = guard
    return guard


def styled_menu(parent: QWidget) -> QMenu:
    m = QMenu(parent)
    m.setAttribute(Qt.WA_TranslucentBackground, False)
    return m


def menu_action(menu: QMenu, text: str, glyph: str | None = None, cb=None, destructive=False, checked=None):
    color = T.color("red") if destructive else T.color("text")
    act = menu.addAction(glyph_icon(glyph, color, 18) if glyph else glyph_icon("check", QColor(0, 0, 0, 0), 18), text)
    if checked is not None:
        act.setCheckable(True)
        act.setChecked(checked)
        if checked:
            act.setIcon(glyph_icon("check", T.color("blue"), 18))
    if cb:
        act.triggered.connect(lambda _c=False: cb())
    return act
