"""
Ver uma página grande sem sair da tela (Organizar, Remover e Extrair páginas).

A página aparece por cima da janela, ajustada ao tamanho dela e com o giro que ainda não foi
salvo. Setas (ou ← →, Page Up / Page Down) passam para a anterior e a próxima, na ordem atual;
Ctrl+roda, + e − ampliam; arrastar move a página ampliada; Esc, Espaço ou clique fora fecham.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ios_theme import T, font, glyph_icon

ZOOMS = [1.0, 1.5, 2.0, 3.0, 4.0]


def _round_button(glyph: str, tip: str, size: int = 40) -> QPushButton:
    b = QPushButton()
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(size, size)
    b.setIcon(glyph_icon(glyph, QColor("white"), 20))
    b.setStyleSheet(f"QPushButton {{ background: rgba(255,255,255,38); border: none; border-radius: {size // 2}px; }}"
                    "QPushButton:hover { background: rgba(255,255,255,70); }"
                    "QPushButton:disabled { background: rgba(255,255,255,14); }")
    return b


class PagePreviewOverlay(QWidget):
    """
    `pages`: lista de (página no arquivo começando em 0, giro extra em graus), na ordem mostrada.
    `label(i)`: texto do alto para a posição i (ex.: "Página 3 de 12 · era 5").
    """

    closed = Signal()

    def __init__(self, window: QWidget, path, pages: list[tuple[int, int]], start: int = 0,
                 label=None, password: str | None = None, on_open_reader=None):
        super().__init__(window)
        from reader import PageCache, page_sizes

        self.pages = list(pages)
        try:
            self.sizes = page_sizes(path, password)
        except Exception:  # noqa: BLE001 - sem tamanhos, usa A4 até a imagem chegar
            self.sizes = []
        self.index = max(0, min(len(self.pages) - 1, start))
        self.label = label or (lambda i: f"Página {i + 1} de {len(self.pages)}")
        self.on_open_reader = on_open_reader
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._drag_from: QPointF | None = None
        self.cache = PageCache(path, limit=6, password=password)
        self.cache.ready.connect(lambda _p: self.update())
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self.bar = QWidget(self)
        lay = QHBoxLayout(self.bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)
        self.prev_b = _round_button("back", "Página anterior (←)")
        self.next_b = _round_button("back", "Próxima página (→)")
        self.next_b.setIcon(glyph_icon("back", QColor("white"), 20).pixmap(20, 20).transformed(QTransform().rotate(180)))
        self.out_b = _round_button("zoom_out", "Diminuir (−)")
        self.in_b = _round_button("zoom_in", "Ampliar (+)")
        self.close_b = _round_button("x", "Fechar (Esc)")
        self.prev_b.clicked.connect(lambda: self.step(-1))
        self.next_b.clicked.connect(lambda: self.step(1))
        self.out_b.clicked.connect(lambda: self.step_zoom(-1))
        self.in_b.clicked.connect(lambda: self.step_zoom(1))
        self.close_b.clicked.connect(self.close_preview)
        for b in (self.prev_b, self.next_b):
            lay.addWidget(b)
        lay.addStretch(1)
        lay.addWidget(self.out_b)
        lay.addWidget(self.in_b)
        if on_open_reader is not None:
            self.reader_b = QPushButton("Abrir no leitor")
            self.reader_b.setCursor(Qt.PointingHandCursor)
            self.reader_b.setFont(font(14, 600))
            self.reader_b.setStyleSheet("QPushButton { background: rgba(255,255,255,38); border: none; border-radius: 20px;"
                                        " color: white; padding: 0 16px; min-height: 40px; }"
                                        "QPushButton:hover { background: rgba(255,255,255,70); }")
            self.reader_b.clicked.connect(self._open_reader)
            lay.addWidget(self.reader_b)
        lay.addWidget(self.close_b)
        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self._sync_buttons()

    # --- navegação ---
    def step(self, d: int):
        j = max(0, min(len(self.pages) - 1, self.index + d))
        if j != self.index:
            self.index = j
            self.zoom, self.offset = 1.0, QPointF(0, 0)
            self._sync_buttons()
            self.update()

    def step_zoom(self, d: int):
        if d > 0:
            z = next((z for z in ZOOMS if z > self.zoom + 1e-6), ZOOMS[-1])
        else:
            z = next((z for z in reversed(ZOOMS) if z < self.zoom - 1e-6), ZOOMS[0])
        self.zoom = z
        if z == 1.0:
            self.offset = QPointF(0, 0)
        self._clamp()
        self._sync_buttons()
        self.update()

    def _sync_buttons(self):
        self.prev_b.setEnabled(self.index > 0)
        self.next_b.setEnabled(self.index < len(self.pages) - 1)
        self.out_b.setEnabled(self.zoom > ZOOMS[0])
        self.in_b.setEnabled(self.zoom < ZOOMS[-1])

    def _open_reader(self):
        page, _rot = self.pages[self.index]
        cb = self.on_open_reader
        self.close_preview()
        if cb:
            cb(page)

    def close_preview(self):
        self.parent().removeEventFilter(self)
        self.cache.shutdown()
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def open(self):
        self.show()
        self.raise_()
        self.setFocus()

    # --- geometria ---
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def resizeEvent(self, e):
        self.bar.setGeometry(0, 0, self.width(), 60)
        super().resizeEvent(e)

    def _area(self) -> QRectF:
        return QRectF(24, 68, max(50, self.width() - 48), max(50, self.height() - 68 - 40))

    def _page_rect(self) -> tuple[QRectF, int]:
        """Retângulo da página na tela (já girada) e o giro."""
        page, rot = self.pages[self.index]
        w, h = self.sizes[page] if 0 <= page < len(self.sizes) else (595, 842)
        if rot % 180:
            w, h = h, w
        area = self._area()
        fit = min(area.width() / w, area.height() / h)
        s = fit * self.zoom
        tw, th = w * s, h * s
        r = QRectF(area.center().x() - tw / 2 + self.offset.x(), area.center().y() - th / 2 + self.offset.y(), tw, th)
        return r, rot

    def _clamp(self):
        r, _ = self._page_rect()
        area = self._area()
        dx = max(0.0, (r.width() - area.width()) / 2)
        dy = max(0.0, (r.height() - area.height()) / 2)
        self.offset = QPointF(max(-dx, min(dx, self.offset.x())), max(-dy, min(dy, self.offset.y())))

    # --- desenho ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(16, 16, 18, 246))
        p.setPen(QColor("white"))
        p.setFont(font(15, 600))
        p.drawText(QRectF(0, 0, self.width(), 60), Qt.AlignCenter, self.label(self.index))
        r, rot = self._page_rect()
        page, _ = self.pages[self.index]
        dpr = self.devicePixelRatioF()
        need = (r.height() if rot % 180 else r.width()) * dpr
        img = self.cache.get(page, need)
        p.save()
        p.setClipRect(self._area().adjusted(-24, -8, 24, 40))
        p.translate(r.center())
        p.rotate(rot)
        w, h = (r.height(), r.width()) if rot % 180 else (r.width(), r.height())
        target = QRectF(-w / 2, -h / 2, w, h)
        p.fillRect(target, QColor("white"))
        if img is not None and not img.isNull():
            p.drawImage(target, img)
        else:
            p.setPen(QColor(150, 150, 150))
            p.setFont(font(14))
            p.drawText(target, Qt.AlignCenter, "Carregando…")
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(target)
        p.restore()
        if self.zoom > 1.0:
            p.setPen(QColor(255, 255, 255, 180))
            p.setFont(font(12, 600))
            p.drawText(QRectF(0, self.height() - 34, self.width(), 24), Qt.AlignCenter,
                       f"{round(self.zoom * 100)}% · arraste para mover")

    # --- mouse e teclado ---
    def mousePressEvent(self, e):
        r, _ = self._page_rect()
        if e.button() == Qt.LeftButton and r.contains(e.position()):
            if self.zoom > 1.0:
                self._drag_from = e.position()
                self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton and e.position().y() > 60:
            self.close_preview()

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self.offset += e.position() - self._drag_from
            self._drag_from = e.position()
            self._clamp()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            self._drag_from = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, e):
        r, _ = self._page_rect()
        if r.contains(e.position()):
            self.zoom = 1.0 if self.zoom > 1.0 else 2.0
            self.offset = QPointF(0, 0)
            self._sync_buttons()
            self.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.step_zoom(1 if e.angleDelta().y() > 0 else -1)
        elif self.zoom > 1.0:
            self.offset += QPointF(e.angleDelta().x() / 2, e.angleDelta().y() / 2)
            self._clamp()
            self.update()
        else:
            self.step(-1 if e.angleDelta().y() > 0 else 1)
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_Space):
            self.close_preview()
        elif k in (Qt.Key_Left, Qt.Key_PageUp, Qt.Key_Up):
            self.step(-1)
        elif k in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Down):
            self.step(1)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.step_zoom(1)
        elif k == Qt.Key_Minus:
            self.step_zoom(-1)
        elif k == Qt.Key_Home:
            self.step(-len(self.pages))
        elif k == Qt.Key_End:
            self.step(len(self.pages))
        else:
            super().keyPressEvent(e)
