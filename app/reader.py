"""
Leitor de PDF do próprio Prumo: páginas em rolagem contínua, zoom e troca rápida
entre o original e a cópia com OCR. Simples de propósito (o modo leitor e a busca no
texto chegam na etapa 3), mas evita abrir outro programa só para ler.

Atalhos: Ctrl+roda do mouse ou Ctrl+ / Ctrl- para zoom, Ctrl+0 ajusta à largura,
Page Up / Page Down e as setas rolam, Home / End vão ao começo e ao fim.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

import core
from ios_kit import CircleButton, EmptyState, Label, Screen, menu_action, styled_menu
from ios_theme import MARGIN, T, font

GAP = 14
MAX_W = 900            # largura da página com zoom 100%, se a janela couber
ZOOMS = [0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]


def page_sizes(path) -> list[tuple[float, float]]:
    import pypdfium2 as pdfium

    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return [tuple(pdf.get_page_size(i)) for i in range(len(pdf))]
        finally:
            pdf.close()


class _Signals(QObject):
    done = Signal(int, int, object)


class _Render(QRunnable):
    def __init__(self, path, page, px, signals):
        super().__init__()
        self.path, self.page, self.px, self.signals = path, page, px, signals

    def run(self):
        from services import render_page
        img = render_page(self.path, self.page, self.px)
        self.signals.done.emit(self.page, self.px, img if img is not None else QImage())


class PageCache(QObject):
    """Páginas renderizadas sob demanda, com poucas na memória (páginas grandes ocupam muito)."""

    ready = Signal(int)

    def __init__(self, path, limit=14):
        super().__init__()
        self.path, self.limit = str(path), limit
        self.mem: OrderedDict[tuple[int, int], QImage] = OrderedDict()
        self.best: dict[int, QImage] = {}
        self.pending: set[tuple[int, int]] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.signals = _Signals()
        self.signals.done.connect(self._done)

    def get(self, page: int, px: int) -> QImage | None:
        px = max(64, int(px) // 32 * 32 + 32)   # arredonda: zoom pequeno não pede página nova
        key = (page, px)
        img = self.mem.get(key)
        if img is not None:
            self.mem.move_to_end(key)
            return img
        if key not in self.pending:
            self.pending.add(key)
            self.pool.start(_Render(self.path, page, px, self.signals))
        return self.best.get(page)   # enquanto isso, a melhor versão que já existe (ampliada)

    def _done(self, page, px, img):
        self.pending.discard((page, px))
        if img.isNull():
            return
        self.mem[(page, px)] = img
        self.best[page] = img
        while len(self.mem) > self.limit:
            (old_page, _), _img = self.mem.popitem(last=False)
            if self.best.get(old_page) is _img:
                self.best.pop(old_page, None)
        self.ready.emit(page)

    def shutdown(self):
        self.pool.clear()
        self.pool.waitForDone(2000)


class PagesView(QWidget):
    page_changed = Signal(int)

    def __init__(self, screen, path):
        super().__init__()
        self.screen = screen
        self.sizes = page_sizes(path)
        self.cache = PageCache(path)
        self.cache.ready.connect(lambda _p: self.update())
        self.zoom = 1.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        T.changed.connect(self.update)

    def avail(self) -> float:
        return max(200.0, self.screen.scroll.viewport().width() - 2 * MARGIN)

    def base_width(self) -> float:
        return min(self.avail(), MAX_W)

    def _layout(self):
        """Topo e altura de cada página para a largura atual (recalcula só quando a largura muda)."""
        bw = self.base_width() * self.zoom
        if getattr(self, "_layout_key", None) != bw:
            tops, y = [], 0.0
            for w, h in self.sizes:
                tops.append((y, bw * h / max(1, w)))
                y += bw * h / max(1, w) + GAP
            self._tops, self._layout_key, self._total = tops, bw, max(0.0, y - GAP)
        return bw

    def page_rect(self, i: int) -> QRectF:
        bw = self._layout()
        top, h = self._tops[i]
        return QRectF(max(0.0, (self.width() - bw) / 2), top, bw, h)

    def total_height(self) -> int:
        self._layout()
        return int(self._total)

    def relayout(self):
        bw = self.base_width() * self.zoom
        self.setMinimumWidth(int(bw) if bw > self.avail() else 0)
        self.setFixedHeight(max(1, self.total_height()))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        exposed = QRectF(ev.rect())
        dpr = self.devicePixelRatioF()
        for i in range(len(self.sizes)):
            r = self.page_rect(i)
            if r.bottom() < exposed.top():
                continue
            if r.top() > exposed.bottom():
                break
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 30))
            p.drawRect(r.translated(0, 2))
            p.fillRect(r, QColor("white"))
            img = self.cache.get(i, r.width() * dpr)
            if img is not None and not img.isNull():
                p.drawImage(r, img)
            else:
                p.setPen(QColor(150, 150, 150))
                p.setFont(font(13))
                p.drawText(r, Qt.AlignCenter, f"Página {i + 1}")
            p.setPen(QPen(T.color("thumb_border"), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)

    def current_page(self) -> int:
        top = self.screen.scroll.verticalScrollBar().value() - self.y()
        mid = top + self.screen.scroll.viewport().height() * 0.35
        for i in range(len(self.sizes)):
            if self.page_rect(i).bottom() + GAP / 2 >= mid:
                return i
        return len(self.sizes) - 1

    def go_to(self, i: int):
        i = max(0, min(len(self.sizes) - 1, i))
        self.screen.scroll.verticalScrollBar().setValue(int(self.y() + self.page_rect(i).top()))

    def set_zoom(self, z: float):
        page = self.current_page()
        sb = self.screen.scroll.verticalScrollBar()
        r = self.page_rect(page)
        frac = (sb.value() - self.y() - r.top()) / max(1.0, r.height())
        self.zoom = max(ZOOMS[0], min(ZOOMS[-1], z))
        self.relayout()
        r = self.page_rect(page)
        sb.setValue(int(self.y() + r.top() + frac * r.height()))

    def step_zoom(self, direction: int):
        if direction > 0:
            nxt = next((z for z in ZOOMS if z > self.zoom + 1e-6), ZOOMS[-1])
        else:
            nxt = next((z for z in reversed(ZOOMS) if z < self.zoom - 1e-6), ZOOMS[0])
        self.set_zoom(nxt)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.step_zoom(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
        else:
            e.ignore()


class Segmented(QWidget):
    """Dois botões lado a lado (Original | Com OCR), como o controle segmentado do iOS."""

    def __init__(self, labels, current, on_pick):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.setFixedHeight(38)
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(font(14, 600 if i == current else 500))
            sel = i == current
            b.setStyleSheet(
                f"QPushButton {{ border: none; border-radius: 8px; padding: 5px 18px; color: {T.hex('text')};"
                f" background: {T.hex('panel') if sel else 'transparent'}; }}")
            b.clicked.connect(lambda _c=False, i=i: on_pick(i))
            lay.addWidget(b)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("search"))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)


class PageCounter(QWidget):
    """Cápsula escura com "Página X de N", no pé do leitor."""

    def __init__(self, parent):
        super().__init__(parent)
        self.text = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_text(self, t):
        from PySide6.QtGui import QFontMetrics
        self.text = t
        self.setFixedSize(QFontMetrics(font(13, 600)).horizontalAdvance(t) + 28, 28)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(40, 40, 42, 215))
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        p.setPen(QColor("white"))
        p.setFont(font(13, 600))
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class ReaderScreen(Screen):
    large_title = False

    def __init__(self, app, item_id: str, start_page: int = 0, title_extra: str = ""):
        super().__init__(app)
        self.item_id = item_id
        self.item = app.lib.item(item_id)
        self.add_back()
        self.big_title.hide()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        zo = CircleButton("zoom_out", "Diminuir (Ctrl -)")
        zi = CircleButton("zoom_in", "Aumentar (Ctrl +)")
        self.more = CircleButton("ellipsis", "Mais opções")
        self.more.clicked.connect(self._menu)
        for b in (zo, zi, self.more):
            self.nav.right.addWidget(b)
        self._name = self.item.name if self.item else ""
        self._extra = title_extra
        if self.item is None:
            self.set_title("")
            self.content.addWidget(EmptyState("docs", "PDF não encontrado", "O arquivo foi movido ou apagado."))
            self.finish_content()
            self.view = None
            return
        app.lib.mark_opened(self.item)
        twin = self._twin()
        if twin is not None:
            is_ocr = self.item.meta.is_ocr_result
            seg = Segmented(["Original", "Com OCR"], 1 if is_ocr else 0, self._switch)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(seg)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 4)
            self.content.addWidget(holder)
        try:
            self.view = PagesView(self, self.item.path)
        except Exception as exc:  # noqa: BLE001
            self.view = None
            self.content.addWidget(EmptyState("warning", "Não foi possível abrir o PDF", str(exc)))
            self.finish_content()
            return
        self.content.addWidget(self.view)
        self.finish_content()
        self.content.setContentsMargins(MARGIN, 0, MARGIN, 40)
        zo.clicked.connect(lambda: self.view.step_zoom(-1))
        zi.clicked.connect(lambda: self.view.step_zoom(1))
        self.counter = PageCounter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _v: self._update_counter())
        for seq, fn in (("Ctrl++", lambda: self.view.step_zoom(1)), ("Ctrl+=", lambda: self.view.step_zoom(1)),
                        ("Ctrl+-", lambda: self.view.step_zoom(-1)), ("Ctrl+0", lambda: self.view.set_zoom(1.0)),
                        ("Home", lambda: self.view.go_to(0)), ("End", lambda: self.view.go_to(10 ** 6)),
                        ("PgDown", lambda: self.view.go_to(self.view.current_page() + 1)),
                        ("PgUp", lambda: self.view.go_to(self.view.current_page() - 1))):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self._start = start_page

    def _twin(self):
        lib = self.app.lib
        it = self.item
        if it.meta.is_ocr_result and it.meta.source_id:
            return lib.item(it.meta.source_id)
        return lib.ocr_copy(it)

    def _switch(self, idx):
        want_ocr = idx == 1
        if want_ocr == bool(self.item.meta.is_ocr_result):
            return
        twin = self._twin()
        if twin is None:
            return
        page = self.view.current_page() if self.view else 0
        self.app.replace_top(ReaderScreen(self.app, twin.id, start_page=page))

    def _menu(self):
        if self.item is None:
            return
        m = styled_menu(self.more)
        menu_action(m, "Ajustar à largura (Ctrl+0)", "zoom_in", lambda: self.view and self.view.set_zoom(1.0))
        menu_action(m, "Compartilhar…", "share", lambda: self.app.actions.share([self.item]))
        menu_action(m, "Abrir no leitor de PDF do Windows", "open", lambda: self.app.open_external(self.item))
        menu_action(m, "Ver detalhes do PDF", "info", lambda: self.app.open_document(self.item.id))
        m.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def refresh(self):
        if self.view is not None:
            self.view.update()
        self._update_counter()

    def on_shown(self):
        super().on_shown()
        if self.view is not None:
            self.view.relayout()
            if self._start:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.view.go_to(self._start))
                self._start = 0
            self.view.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "view", None) is not None:
            self.view.relayout()
            self._update_counter()

    def _update_counter(self):
        if getattr(self, "view", None) is None:
            return
        n = len(self.view.sizes)
        i = self.view.current_page() + 1
        zoom = f" · {round(self.view.zoom * 100)}%" if abs(self.view.zoom - 1.0) > 1e-6 else ""
        self.counter.set_text(f"Página {i} de {n}{zoom}")
        self.counter.move((self.width() - self.counter.width()) // 2, self.height() - self.counter.height() - 16)
        self.counter.raise_()
        self.counter.show()
        title = self._name + (f" · {self._extra}" if self._extra else "")
        self.set_title(title)

    def closing(self):
        if getattr(self, "view", None) is not None:
            self.view.cache.shutdown()

    def sizeHint(self):
        return QSize(800, 600)
