"""
Barra que aparece ao selecionar texto no leitor, como a minibarra do Word:

    [Destacar ▾] [Copiar] [Desfazer destaque] [Adicionar ao resumo]

Passar o mouse sobre "Destacar" abre as cores; elas ficam abertas enquanto o mouse estiver no
botão ou nas cores, e tudo some ao escolher uma. Um clique no próprio "Destacar" usa a última cor.
"Desfazer destaque" só aparece quando parte do texto selecionado já está destacada.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QPushButton, QWidget

import annotations
from ios_theme import T, font, glyph_icon


def _qcolor(key: str) -> QColor:
    r, g, b = annotations.COLORS.get(key, annotations.COLORS["yellow"])[1]
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class _Panel(QFrame):
    """Fundo arredondado com sombra leve, no estilo dos menus do app."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 34))
        p.drawRoundedRect(r.translated(0, 2), 11, 11)
        p.setBrush(T.color("panel"))
        p.setPen(QPen(T.color("panel_line"), 1))
        p.drawRoundedRect(r, 11, 11)


class _Dot(QAbstractButton):
    def __init__(self, key: str, label: str):
        super().__init__()
        self.key = key
        self.setToolTip(f"Destacar em {label.lower()}")
        self.setAccessibleName(f"Destacar em {label.lower()}")
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("tile_hover"))
            p.drawEllipse(QRectF(self.rect()))
        p.setPen(QPen(QColor(0, 0, 0, 45), 1))
        p.setBrush(_qcolor(self.key))
        p.drawEllipse(QRectF(self.rect()).adjusted(5, 5, -5, -5))


class ColorPopup(_Panel):
    picked = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(2)
        self.dots = []
        for key, (label, _rgb) in annotations.COLORS.items():
            d = _Dot(key, label)
            d.clicked.connect(lambda _c=False, k=key: self.picked.emit(k))
            lay.addWidget(d)
            self.dots.append(d)
        self.setAttribute(Qt.WA_Hover)
        self.hide()


class _BarButton(QPushButton):
    def __init__(self, text: str, glyph: str, color: str, tip: str = ""):
        super().__init__(" " + text)
        self.glyph, self.color_name = glyph, color
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip or text)
        self.setFont(font(13, 500))
        self.setIconSize(QSize(17, 17))
        self.restyle()

    def restyle(self, dot: QColor | None = None):
        c = T.color(self.color_name) if self.isEnabled() else T.color("placeholder")
        self.setIcon(glyph_icon(self.glyph, c, 17))
        extra = f"border-bottom: 3px solid {dot.name()};" if dot is not None else ""
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px 9px; "
            f"color: {T.hex('text')}; {extra} }}"
            f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}"
            f"QPushButton:disabled {{ color: {T.hex('placeholder')}; }}")


class SelectionToolbar(_Panel):
    """A minibarra; `screen` é o leitor (modo Página ou Texto)."""

    def __init__(self, screen: QWidget):
        super().__init__(screen)
        self.screen = screen
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 7)
        lay.setSpacing(2)
        self.mark_btn = _BarButton("Destacar", "highlighter", "orange",
                                   "Destacar (passe o mouse para escolher a cor)")
        self.mark_btn.clicked.connect(lambda: self._pick(None))
        self.copy_btn = _BarButton("Copiar", "copy", "blue", "Copiar (Ctrl+C)")
        self.copy_btn.clicked.connect(self._copy)
        self.unmark_btn = _BarButton("Desfazer destaque", "eraser", "red",
                                     "Tirar o destaque do texto selecionado")
        self.unmark_btn.clicked.connect(self._unmark)
        self.summary_btn = _BarButton("Adicionar ao resumo", "summary", "teal", "Adicionar ao resumo deste PDF")
        self.summary_btn.clicked.connect(self._summary)
        for b in (self.mark_btn, self.copy_btn, self.unmark_btn, self.summary_btn):
            lay.addWidget(b)
        self.popup = ColorPopup(screen)
        self.popup.picked.connect(self._pick)
        self._hover = QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(300)
        self._hover.timeout.connect(self._maybe_close_popup)
        self.mark_btn.installEventFilter(self)
        self.popup.installEventFilter(self)
        T.changed.connect(self._restyle)
        self.hide()

    def _restyle(self):
        self.mark_btn.restyle(_qcolor(self.screen.last_color()))
        for b in (self.copy_btn, self.unmark_btn, self.summary_btn):
            b.restyle()

    # --- cores ao passar o mouse ---
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Enter:
            if obj is self.mark_btn and self.mark_btn.isEnabled():
                self._open_popup()
            elif obj is self.popup:
                self._hover.stop()
        elif t == QEvent.Leave and obj in (self.mark_btn, self.popup):
            self._hover.start()
        return False

    def _over(self, w: QWidget) -> bool:
        return w.isVisible() and w.rect().contains(w.mapFromGlobal(QCursor.pos()))

    def _maybe_close_popup(self):
        if self._over(self.mark_btn) or self._over(self.popup):
            return
        self.popup.hide()

    def _open_popup(self):
        self._hover.stop()
        self.popup.adjustSize()
        host = self.screen
        btn = self.mark_btn.mapTo(host, QPoint(0, 0))
        x = max(6, min(btn.x(), host.width() - self.popup.width() - 6))
        below = self.geometry().bottom() + 3
        y = below if below + self.popup.height() < host.height() - 6 else self.geometry().top() - self.popup.height() - 3
        self.popup.move(x, y)
        self.popup.show()
        self.popup.raise_()

    # --- ações ---
    def _pick(self, key):
        self.dismiss()
        self.screen.highlight_selection(key or self.screen.last_color())

    def _copy(self):
        self.dismiss()
        self.screen.copy_selection()

    def _unmark(self):
        self.dismiss()
        self.screen.unhighlight_selection()

    def _summary(self):
        self.dismiss()
        self.screen.add_to_summary()

    # --- mostrar e esconder ---
    def show_for(self, anchor: QRect, has_marks: bool, editable: bool, bounds: QRect | None = None):
        """`anchor`: retângulo do fim da seleção, em coordenadas do leitor; `bounds`: área do texto."""
        self.mark_btn.setEnabled(editable)
        self.unmark_btn.setVisible(has_marks and editable)
        self._restyle()
        self.popup.hide()
        self.adjustSize()
        host = self.screen
        w, h = self.width(), self.height()
        lo, hi = 8, host.width() - w - 8
        if bounds is not None and bounds.width() >= w + 16:
            lo, hi = max(lo, bounds.left() + 8), min(hi, bounds.right() - w - 8)
        x = max(lo, min(anchor.center().x() - w // 2, hi))
        top_limit = 70   # abaixo da barra do alto
        y = anchor.top() - h - 10
        if y < top_limit:
            y = anchor.bottom() + 12
        y = max(top_limit, min(y, host.height() - h - 8))
        self.move(x, y)
        self.show()
        self.raise_()

    def dismiss(self):
        self._hover.stop()
        self.popup.hide()
        self.hide()
