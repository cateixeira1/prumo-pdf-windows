"""
Retângulo de seleção (clicar e arrastar), como no Explorador de Arquivos.

Funciona por cima de qualquer tela com rolagem: um filtro de eventos olha os cliques dentro do
"host" (o corpo da tela) e, quando o mouse anda alguns pixels com o botão apertado, desenha o
retângulo e informa quais itens ele toca. Perto do alto ou do pé da área visível, a tela rola
sozinha. Ctrl (ou Shift) apertado no começo soma à seleção que já existia.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
                               QLineEdit, QTextEdit, QWidget)

from ios_theme import T

THRESHOLD = 8           # pixels de movimento até virar retângulo
EDGE = 60               # faixa perto da borda que liga a rolagem automática
MAX_SPEED = 24          # pixels por quadro, bem na borda


def rect_in(host: QWidget, w: QWidget) -> QRectF:
    """Retângulo de um widget nas coordenadas do host."""
    return QRectF(QPointF(w.mapTo(host, QPoint(0, 0))), QSizeF(w.size()))


class _Band(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor(T.color("blue"))
        c.setAlpha(46)
        p.fillRect(self.rect(), c)
        c.setAlpha(200)
        p.setPen(QPen(c, 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))


class RubberBand(QObject):
    """
    `items()`: lista de (chave, QRectF nas coordenadas do host).
    `on_start()`: o retângulo começou (bom momento para guardar a seleção anterior).
    `on_select(chaves, somar, fim)`: durante o arraste (fim=False) e ao soltar (fim=True).
    `can_start(widget, pos)`: um clique nesse widget, na posição dada (coordenadas dele), pode começar?
    """

    def __init__(self, host: QWidget, scroll, items, on_select, on_start=None, can_start=None):
        super().__init__(host)
        self.host, self.scroll = host, scroll
        self.items, self.on_select, self.on_start, self.can_start = items, on_select, on_start, can_start
        self.enabled = True
        self.band = _Band(host)
        self._press: QPointF | None = None
        self._origin: QWidget | None = None
        self.active = False
        self.additive = False
        self._last_keys: set = set()
        self._seen = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._auto_scroll)
        QApplication.instance().installEventFilter(self)
        host.destroyed.connect(self._detach)

    def _detach(self, *_):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    # --- eventos ---
    def _inside(self, obj) -> bool:
        if not isinstance(obj, QWidget):
            return False
        try:
            return obj is self.host or self.host.isAncestorOf(obj)
        except RuntimeError:   # o host já foi apagado
            self._detach()
            return False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            return False
        if not self.enabled or not self._inside(obj):
            return False
        # o mesmo evento chega de novo quando passa para o widget pai: trata uma vez só
        key = (int(t), ev.timestamp(), ev.globalPosition().x(), ev.globalPosition().y())
        if key == self._seen:
            return self.active and t != QEvent.MouseButtonPress
        self._seen = key
        if t == QEvent.MouseButtonPress:
            return self._pressed(obj, ev)
        if t == QEvent.MouseMove:
            return self._moved(ev)
        return self._released(ev)

    def _pressed(self, obj, ev) -> bool:
        self._press = None
        if ev.button() != Qt.LeftButton or not self.host.isVisible():
            return False
        if isinstance(obj, (QLineEdit, QTextEdit, QAbstractSpinBox, QComboBox, QAbstractSlider)):
            return False
        local = obj.mapFromGlobal(ev.globalPosition().toPoint())
        if self.can_start is not None and not self.can_start(obj, QPointF(local)):
            return False
        self._press = QPointF(self.host.mapFromGlobal(ev.globalPosition().toPoint()))
        self._origin = obj
        self.additive = bool(ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        return False   # o clique segue normalmente; só vira retângulo se o mouse andar

    def _moved(self, ev) -> bool:
        if self._press is None or not (ev.buttons() & Qt.LeftButton):
            return False
        pos = QPointF(self.host.mapFromGlobal(ev.globalPosition().toPoint()))
        if not self.active:
            if (pos - self._press).manhattanLength() < THRESHOLD:
                return False
            self._begin()
        self._update(pos)
        return True

    def _released(self, ev) -> bool:
        if ev.button() != Qt.LeftButton:
            return False
        was = self.active
        if was:
            self.timer.stop()
            self.band.hide()
            self.active = False
            self.on_select(set(self._last_keys), self.additive, True)
        self._press = None
        self._origin = None
        return was   # depois de um retângulo, o clique não abre nada

    # --- retângulo ---
    def _begin(self):
        self.active = True
        if isinstance(self._origin, QAbstractButton):
            self._origin.setDown(False)
        if self.on_start is not None:
            self.on_start(self.additive)
        self._last_keys = set()
        self.band.raise_()
        self.band.show()
        self.timer.start()

    def _update(self, pos: QPointF):
        r = QRectF(self._press, pos).normalized()
        self.band.setGeometry(r.toAlignedRect() if r.width() >= 1 else QRect(r.toPoint(), r.toPoint()))
        self.band.raise_()
        keys = {k for k, rect in self.items() if rect.intersects(r)}
        if keys != self._last_keys:
            self._last_keys = keys
            self.on_select(set(keys), self.additive, False)

    def _auto_scroll(self):
        if not self.active or self.scroll is None:
            return
        vp = self.scroll.viewport()
        y = vp.mapFromGlobal(QCursor.pos()).y()
        h = vp.height()
        speed = 0.0
        if y < EDGE:
            speed = -MAX_SPEED * min(1.0, (EDGE - y) / EDGE)
        elif y > h - EDGE:
            speed = MAX_SPEED * min(1.0, (y - (h - EDGE)) / EDGE)
        if speed:
            bar = self.scroll.verticalScrollBar()
            before = bar.value()
            bar.setValue(int(before + speed))
            if bar.value() != before:
                self._update(QPointF(self.host.mapFromGlobal(QCursor.pos())))
