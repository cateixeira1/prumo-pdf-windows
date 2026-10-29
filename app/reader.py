"""
Leitor de PDF do próprio Prumo.

- À esquerda, as miniaturas das páginas (como no Word): rolam com o mouse e um clique leva à página.
- No meio, as páginas: rolagem contínua, zoom e troca rápida entre o original e a cópia com OCR.
  Dá para selecionar o texto com o mouse (arrastar; dois cliques selecionam a palavra).
- À direita, o painel: cores de destaque (escolha a cor e arraste sobre o texto), borracha,
  "Adicionar ao resumo" e botões para todas as funções do app.
- Os destaques são gravados no próprio PDF como anotações padrão, que aparecem em qualquer leitor.
- Modo leitor: só o texto (do OCR ou do próprio PDF), em parágrafos, com tamanho da letra,
  fonte e fundo (branco, sépia, escuro) à escolha, para ler com conforto e copiar trechos.
- Busca (Ctrl+F) nos dois modos: ignora acentos e maiúsculas, destaca as ocorrências e
  anda entre elas com Enter / Shift+Enter (ou F3 / Shift+F3).

Atalhos: Ctrl+roda do mouse ou Ctrl+ / Ctrl- para zoom, Ctrl+0 ajusta à largura,
Page Up / Page Down e as setas rolam, Home / End vão ao começo e ao fim, Ctrl+C copia a seleção,
Ctrl+Z desfaz o último destaque.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPen,
                           QShortcut, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy,
                               QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

import annotations
import core
import reader_text
from ios_kit import (CircleButton, EmptyState, Label, Screen, SearchField, TextButton, menu_action, styled_menu)
from ios_theme import MARGIN, T, font, glyph_icon, paint_glyph

GAP = 14
MAX_W = 900            # largura da página com zoom 100%, se a janela couber
ZOOMS = [0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
SIDEBAR_W = 168
PANEL_W = 248
EDGE = 50              # faixa perto da borda que rola a página enquanto se seleciona texto


def page_sizes(path, password: str | None = None) -> list[tuple[float, float]]:
    import pypdfium2 as pdfium

    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path), password=password)
        try:
            return [tuple(pdf.get_page_size(i)) for i in range(len(pdf))]
        finally:
            pdf.close()


def highlight_qcolor(key: str, alpha: int = 255) -> QColor:
    r, g, b = annotations.COLORS.get(key, annotations.COLORS["yellow"])[1]
    return QColor(int(r * 255), int(g * 255), int(b * 255), alpha)


class _Signals(QObject):
    done = Signal(int, int, object)


class _Render(QRunnable):
    def __init__(self, path, page, px, signals, password=None, generation=0):
        super().__init__()
        self.path, self.page, self.px, self.signals, self.password = path, page, px, signals, password
        self.generation = generation

    def run(self):
        from services import render_page
        img = render_page(self.path, self.page, self.px, self.password)
        self.signals.done.emit(self.page, self.px, (self.generation, img if img is not None else QImage()))


class PageCache(QObject):
    """Páginas renderizadas sob demanda, com poucas na memória (páginas grandes ocupam muito)."""

    ready = Signal(int)

    def __init__(self, path, limit=14, password=None):
        super().__init__()
        self.path, self.limit, self.password = str(path), limit, password
        self.mem: OrderedDict[tuple[int, int], QImage] = OrderedDict()
        self.best: dict[int, QImage] = {}
        self.pending: set[tuple[int, int]] = set()
        self.generation = 0
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
            self.pool.start(_Render(self.path, page, px, self.signals, self.password, self.generation))
        return self.best.get(page)   # enquanto isso, a melhor versão que já existe (ampliada)

    def _done(self, page, px, payload):
        generation, img = payload
        if generation != self.generation:
            return   # página de antes de o arquivo mudar
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

    def invalidate(self, path=None):
        """O arquivo mudou: desenha de novo, mostrando a versão antiga até a nova ficar pronta."""
        if path is not None:
            self.path = str(path)
        self.generation += 1
        self.mem.clear()
        self.pending.clear()

    def shutdown(self):
        self.pool.clear()
        self.pool.waitForDone(2000)


class PagesView(QWidget):
    page_changed = Signal(int)
    selection_changed = Signal()

    def __init__(self, screen, path, password=None):
        super().__init__()
        self.screen = screen
        self.sizes = page_sizes(path, password)
        self.cache = PageCache(path, password=password)
        self.cache.ready.connect(lambda _p: self.update())
        self.zoom = 1.0
        self.hits: dict[int, list] = {}          # página → ocorrências da busca
        self.current_hit = None
        # seleção de texto: ((página, posição), (página, posição)) na ordem em que foi feita
        self.tool = "select"                     # "select", "highlight" ou "erase"
        self.color = "yellow"
        self.sel = None
        self.sel_rects: dict[int, list] = {}
        self.marks: dict[int, list] = {}         # página → [(Mark, retângulos na tela)]
        self._pressing = False
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(30)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        self.setMouseTracking(True)
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

    def scale(self, i: int) -> float:
        """Pixels na tela por ponto da página i."""
        return self.page_rect(i).width() / max(1.0, self.sizes[i][0])

    def total_height(self) -> int:
        self._layout()
        return int(self._total)

    def relayout(self):
        bw = self.base_width() * self.zoom
        self.setMinimumWidth(int(bw) if bw > self.avail() else 0)
        self.setFixedHeight(max(1, self.total_height()))
        self.update()

    def to_screen(self, i: int, rect) -> QRectF:
        """Retângulo em pontos da página (origem no alto à esquerda) → retângulo neste widget."""
        r = self.page_rect(i)
        s = self.scale(i)
        x0, y0, x1, y1 = rect
        return QRectF(r.x() + x0 * s, r.y() + y0 * s, (x1 - x0) * s, (y1 - y0) * s)

    def locate(self, pos: QPointF):
        """(página, x, y em pontos da página) sob o ponto do widget; perto do vão, a página mais próxima."""
        n = len(self.sizes)
        if not n:
            return None
        best = None
        for i in range(n):
            r = self.page_rect(i)
            if r.top() - GAP / 2 <= pos.y() <= r.bottom() + GAP / 2:
                best = i
                break
            if pos.y() < r.top():
                best = i
                break
        if best is None:
            best = n - 1
        r = self.page_rect(best)
        s = self.scale(best)
        x = max(0.0, min(self.sizes[best][0], (pos.x() - r.x()) / s))
        y = max(0.0, min(self.sizes[best][1], (pos.y() - r.y()) / s))
        return best, x, y

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        exposed = QRectF(ev.rect())
        dpr = self.devicePixelRatioF()
        sel_color = highlight_qcolor(self.color, 125) if self.tool == "highlight" else QColor(41, 120, 245, 70)
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
            for sr in self.sel_rects.get(i, ()):
                p.setPen(Qt.NoPen)
                p.setBrush(sel_color)
                p.drawRect(self.to_screen(i, sr).adjusted(-0.5, -1, 0.5, 1))
            for hit in self.hits.get(i, ()):
                current = hit is self.current_hit
                for hr in self.hit_rects(hit):
                    p.setPen(QPen(QColor(230, 120, 0), 2) if current else Qt.NoPen)
                    p.setBrush(QColor(255, 149, 0, 110) if current else QColor(255, 214, 10, 105))
                    p.drawRoundedRect(hr.adjusted(-1.5, -1.5, 1.5, 1.5), 2.5, 2.5)

    def hit_rects(self, hit) -> list[QRectF]:
        return [self.to_screen(hit.page, rect) for rect in hit.rects]

    def show_hit(self, hit):
        """Rola até a ocorrência (deixando um pouco de folga acima)."""
        self.current_hit = hit
        rects = self.hit_rects(hit)
        if rects:
            sb = self.screen.scroll.verticalScrollBar()
            top = self.y() + rects[0].top()
            vh = self.screen.scroll.viewport().height()
            if not (sb.value() + 60 < top < sb.value() + vh - 80):
                sb.setValue(int(top - vh * 0.3))
            hb = self.screen.scroll.horizontalScrollBar()
            if hb.maximum() > 0:
                hb.setValue(int(rects[0].left() - 80))
        self.update()

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

    # --- seleção de texto e destaques ---
    def has_selection(self) -> bool:
        return bool(self.ranges())

    def ranges(self) -> list[tuple[int, int, int]]:
        """Trechos selecionados: [(página, início, fim)], na ordem do documento."""
        if not self.sel:
            return []
        a, b = sorted(self.sel)
        text = self.screen.text
        if text is None:
            return []
        out = []
        for page in range(a[0], b[0] + 1):
            start = a[1] if page == a[0] else 0
            end = b[1] if page == b[0] else text.char_count(page)
            if end > start:
                out.append((page, start, end))
        return out

    def _update_sel_rects(self):
        text = self.screen.text
        self.sel_rects = {}
        if text is not None:
            for page, a, b in self.ranges():
                self.sel_rects[page] = text.view_rects(page, a, b)
        self.update()
        self.selection_changed.emit()

    def clear_selection(self):
        if self.sel is not None or self.sel_rects:
            self.sel = None
            self.sel_rects = {}
            self.update()
            self.selection_changed.emit()

    def select_range(self, start, end):
        self.sel = (start, end)
        self._update_sel_rects()

    def mark_at(self, pos: QPointF):
        loc = self.locate(pos)
        if loc is None:
            return None
        page, x, y = loc
        for mark, rects in self.marks.get(page, ()):
            for x0, y0, x1, y1 in rects:
                if x0 - 1.5 <= x <= x1 + 1.5 and y0 - 1.5 <= y <= y1 + 1.5:
                    return mark
        return None

    def _boundary(self, pos: QPointF):
        loc = self.locate(pos)
        text = self.screen.text
        if loc is None or text is None:
            return None
        page, x, y = loc
        b = text.boundary_at(page, x, y)
        return None if b is None else (page, b)

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self.tool == "erase":
            mark = self.mark_at(pos)
            if mark is not None:
                self.screen.erase_mark(mark)
            else:
                self.screen.app.toast("Clique sobre um destaque para apagá-lo.")
            return
        b = self._boundary(pos)
        if b is None:
            self.clear_selection()
            self.screen.no_text_here()
            return
        if e.modifiers() & Qt.ShiftModifier and self.sel:
            self.sel = (self.sel[0], b)
        else:
            self.sel = (b, b)
        self._pressing = True
        self._update_sel_rects()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._pressing and e.buttons() & Qt.LeftButton:
            b = self._boundary(pos)
            if b is not None and self.sel:
                self.sel = (self.sel[0], b)
                self._update_sel_rects()
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
            return
        if self.tool == "erase":
            self.setCursor(Qt.PointingHandCursor if self.mark_at(pos) is not None else Qt.ArrowCursor)
        else:
            loc = self.locate(pos)
            text = self.screen.text
            on_text = loc is not None and text is not None and text.has_text(loc[0])
            self.setCursor(Qt.IBeamCursor if on_text else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._pressing:
            return
        self._pressing = False
        self._scroll_timer.stop()
        if self.has_selection() and self.tool == "highlight":
            self.screen.highlight_selection(self.color)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or self.tool == "erase":
            return
        loc = self.locate(e.position())
        text = self.screen.text
        if loc is None or text is None:
            return
        page, x, y = loc
        word = text.word_at(page, x, y)
        if word is None:
            return
        self._pressing = False
        self.select_range((page, word[0]), (page, word[1]))
        if self.tool == "highlight":
            self.screen.highlight_selection(self.color)

    def contextMenuEvent(self, e):
        self.screen.context_menu(e.pos(), self.mark_at(QPointF(e.pos())))

    def _auto_scroll(self):
        if not self._pressing:
            self._scroll_timer.stop()
            return
        vp = self.screen.scroll.viewport()
        y = vp.mapFromGlobal(QCursor.pos()).y()
        h = vp.height()
        speed = 0
        if y < EDGE:
            speed = -int(4 + 26 * min(1.0, (EDGE - y) / EDGE))
        elif y > h - EDGE:
            speed = int(4 + 26 * min(1.0, (y - (h - EDGE)) / EDGE))
        if speed:
            sb = self.screen.scroll.verticalScrollBar()
            sb.setValue(sb.value() + speed)
            b = self._boundary(QPointF(self.mapFromGlobal(QCursor.pos())))
            if b is not None and self.sel:
                self.sel = (self.sel[0], b)
                self._update_sel_rects()


class Segmented(QWidget):
    """Botões lado a lado (Original | Com OCR | Texto), como o controle segmentado do iOS."""

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


class SearchBar(QWidget):
    """Campo de busca do leitor, com "3 de 17", anterior, próxima e fechar."""

    def __init__(self, on_query, on_step, on_close):
        super().__init__()
        self.on_step = on_step
        lay = QHBoxLayout(self)
        lay.setContentsMargins(MARGIN, 0, MARGIN, 8)
        lay.setSpacing(8)
        self.field = SearchField("Buscar no documento (sem precisar de acentos)")
        self.field.debounced.connect(on_query)
        self.field.edit.returnPressed.connect(self._enter)
        lay.addWidget(self.field, 1)
        self.count = Label("", 13, 600, "secondary", wrap=False)
        lay.addWidget(self.count)
        self.buttons = []
        for glyph, tip, d in (("back", "Anterior (Shift+Enter)", -1), ("back", "Próxima (Enter)", 1)):
            b = QPushButton()
            b.setToolTip(tip)
            b.setFixedSize(36, 36)
            b.setCursor(Qt.PointingHandCursor)
            from PySide6.QtGui import QTransform
            pm = glyph_icon(glyph, T.color("blue"), 18).pixmap(18, 18).transformed(QTransform().rotate(90 if d < 0 else -90))
            b.setIcon(pm)
            b.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 18px; }"
                            f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}")
            b.clicked.connect(lambda _c=False, d=d: on_step(d))
            lay.addWidget(b)
            self.buttons.append(b)
        close = TextButton("OK", bold=True)
        close.clicked.connect(on_close)
        lay.addWidget(close)
        self.hide()

    def _enter(self):
        mods = QGuiApplication.keyboardModifiers()
        self.on_step(-1 if mods & Qt.ShiftModifier else 1)

    def text(self) -> str:
        return self.field.text()

    def set_count(self, text: str):
        self.count.setText(text)

    def open(self):
        self.show()
        self.field.edit.setFocus()
        self.field.edit.selectAll()


# --- Miniaturas à esquerda ------------------------------------------------------------

class _ThumbList(QWidget):
    clicked = Signal(int)

    THUMB = 104
    LABEL = 20
    PAD = 9

    def __init__(self, sidebar):
        super().__init__()
        self.sidebar = sidebar
        self.current = 0
        self.hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._layout()

    def _layout(self):
        self.tops = []
        y = 6.0
        for w, h in self.sidebar.sizes:
            th = max(40.0, min(220.0, self.THUMB * h / max(1.0, w)))
            self.tops.append((y, th))
            y += th + self.LABEL + 2 * self.PAD
        self.setFixedHeight(int(y + 10))

    def cell_rect(self, i) -> QRectF:
        y, th = self.tops[i]
        return QRectF(6, y, SIDEBAR_W - 24, th + self.LABEL + 2 * self.PAD)

    def thumb_rect(self, i) -> QRectF:
        y, th = self.tops[i]
        w, h = self.sidebar.sizes[i]
        tw = min(float(self.THUMB), th * w / max(1.0, h))
        cx = 6 + (SIDEBAR_W - 24) / 2
        return QRectF(cx - tw / 2, y + self.PAD, tw, th)

    def index_at(self, pos) -> int:
        for i in range(len(self.tops)):
            if self.cell_rect(i).contains(pos):
                return i
        return -1

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        exposed = QRectF(ev.rect())
        dpr = self.devicePixelRatioF()
        for i in range(len(self.tops)):
            cell = self.cell_rect(i)
            if cell.bottom() < exposed.top():
                continue
            if cell.top() > exposed.bottom():
                break
            if i == self.current or i == self.hover:
                c = QColor(T.color("blue"))
                c.setAlpha(46 if i == self.current else 20)
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(cell, 10, 10)
            r = self.thumb_rect(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 26))
            p.drawRect(r.translated(0, 1.5))
            p.fillRect(r, QColor("white"))
            img = self.sidebar.image(i, int(r.width() * dpr))
            if img is not None and not img.isNull():
                p.drawImage(r, img)
            if i == self.current:
                p.setPen(QPen(T.color("blue"), 2.5))
            else:
                p.setPen(QPen(T.color("thumb_border"), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setPen(T.color("blue") if i == self.current else T.color("secondary"))
            p.setFont(font(12.5, 700 if i == self.current else 500))
            p.drawText(QRectF(cell.x(), r.bottom() + 2, cell.width(), self.LABEL), Qt.AlignCenter, str(i + 1))

    def mouseMoveEvent(self, e):
        i = self.index_at(e.position())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = self.index_at(e.position())
            if i >= 0:
                self.clicked.emit(i)


class ThumbSidebar(QScrollArea):
    """Coluna de miniaturas das páginas, como no Word: rola com o mouse e o clique leva à página."""

    page_clicked = Signal(int)

    def __init__(self, screen, sizes):
        super().__init__()
        self.screen = screen
        self.sizes = sizes
        self.setObjectName("thumbSidebar")
        self.setFixedWidth(SIDEBAR_W)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = _ThumbList(self)
        self.list.clicked.connect(self.page_clicked)
        self.setWidget(self.list)
        self._apply_style()
        T.changed.connect(self._apply_style)
        self._own = None
        thumbs = screen.app.hub.thumbs
        thumbs.ready.connect(self._ready)
        self.destroyed.connect(lambda *_: self._disconnect(thumbs))

    def _disconnect(self, thumbs):
        try:
            thumbs.ready.disconnect(self._ready)
        except (RuntimeError, TypeError):
            pass

    def _ready(self, *_):
        try:
            self.list.update()
        except RuntimeError:
            pass

    def _apply_style(self):
        self.setStyleSheet(f"#thumbSidebar {{ background: {T.hex('tile')}; border: none; }}"
                           "#thumbSidebar > QWidget > QWidget { background: transparent; }")

    def image(self, page: int, px: int):
        item, pw = self.screen.item, self.screen.password
        if item is None:
            return None
        if pw:   # PDF com senha: as miniaturas comuns não abrem; usa um cache próprio
            if self._own is None:
                self._own = PageCache(item.path, limit=40, password=pw)
                self._own.ready.connect(lambda _p: self.list.update())
            return self._own.get(page, px)
        return self.screen.app.hub.thumbs.get(item.path, item.version, page, max(64, px // 16 * 16 + 16))

    def set_current(self, i: int):
        if i == self.list.current:
            return
        self.list.current = i
        self.list.update()
        if self.isVisible() and 0 <= i < len(self.list.tops):
            r = self.list.cell_rect(i)
            self.ensureVisible(0, int(r.center().y()), 0, int(r.height() / 2 + 12))

    def shutdown(self):
        if self._own is not None:
            self._own.shutdown()


# --- Painel à direita: destaque e ferramentas -------------------------------------------

class _Swatch(QAbstractButton):
    """Ferramenta do painel: cor de destaque (círculo colorido), seleção de texto ou borracha."""

    def __init__(self, key: str, tip: str, color: QColor | None = None, glyph: str | None = None):
        super().__init__()
        self.key, self.color, self.glyph = key, color, glyph
        self.active = False
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.active:
            p.setPen(QPen(T.color("blue"), 2.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2))
            r = r.adjusted(2.5, 2.5, -2.5, -2.5)
        elif self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("tile_hover"))
            p.drawEllipse(QRectF(self.rect()))
        if self.color is not None:
            p.setPen(QPen(QColor(0, 0, 0, 40), 1))
            p.setBrush(self.color)
            p.drawEllipse(r)
        if self.glyph:
            paint_glyph(p, r.adjusted(3, 3, -3, -3), self.glyph, T.color("text"), 1.9)


class _PanelButton(QPushButton):
    def __init__(self, text: str, glyph: str, color: str = "blue", tip: str = ""):
        super().__init__("  " + text)
        self.glyph, self.color_name = glyph, color
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip or text)
        self.setFont(font(13.5, 500))
        self.setIconSize(QSize(18, 18))
        self.restyle()

    def restyle(self):
        c = T.color(self.color_name) if self.isEnabled() else T.color("placeholder")
        self.setIcon(glyph_icon(self.glyph, c, 18))
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; text-align: left; "
            f"padding: 6px 8px; color: {T.hex('text')}; }}"
            f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}"
            f"QPushButton:disabled {{ color: {T.hex('placeholder')}; }}")

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.EnabledChange:
            self.restyle()


class ToolPanel(QScrollArea):
    """Painel à direita do leitor: cores de destaque, ações da seleção e todas as funções do app."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.setObjectName("toolPanel")
        self.setFixedWidth(PANEL_W)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(12, 10, 10, 20)
        self.lay.setSpacing(2)
        self.setWidget(body)
        self.buttons: dict[str, _PanelButton] = {}
        self._build()
        self._apply_style()
        T.changed.connect(self._apply_style)

    def _apply_style(self):
        self.setStyleSheet(f"#toolPanel {{ background: {T.hex('tile')}; border: none; }}"
                           "#toolPanel > QWidget > QWidget { background: transparent; }")
        for b in self.buttons.values():
            b.restyle()

    def _title(self, text):
        t = Label(text.upper(), 12, 700, "secondary", wrap=False)
        t.setContentsMargins(4, 12, 0, 4)
        self.lay.addWidget(t)

    def _button(self, key, text, glyph, cb, color="blue", tip=""):
        b = _PanelButton(text, glyph, color, tip)
        b.clicked.connect(lambda _c=False: cb())
        self.buttons[key] = b
        self.lay.addWidget(b)
        return b

    def _build(self):
        s = self.screen
        self._title("Destacar")
        row = QHBoxLayout()
        row.setSpacing(2)
        self.tools: list[_Swatch] = []
        sel = _Swatch("select", "Selecionar texto (sem destacar)", glyph="cursor_text")
        sel.clicked.connect(lambda: s.set_tool("select"))
        row.addWidget(sel)
        self.tools.append(sel)
        for key, (label, _rgb) in annotations.COLORS.items():
            sw = _Swatch(key, f"Destacar em {label.lower()}", color=highlight_qcolor(key))
            sw.clicked.connect(lambda _c=False, k=key: s.set_tool("highlight", k))
            row.addWidget(sw)
            self.tools.append(sw)
        row.addStretch(1)
        self.lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(2)
        er = _Swatch("erase", "Borracha: clique num destaque para apagá-lo", glyph="eraser")
        er.clicked.connect(lambda: s.set_tool("erase"))
        row2.addWidget(er)
        self.tools.append(er)
        self.hint = Label("", 12, 400, "secondary")
        row2.addWidget(self.hint, 1)
        self.lay.addLayout(row2)
        self._button("undo_mark", "Desfazer destaque", "undo", s.undo_highlight, "gray", "Ctrl+Z")

        self._title("Texto selecionado")
        self._button("copy", "Copiar", "copy", s.copy_selection, tip="Ctrl+C")
        self._button("mark", "Destacar a seleção", "highlighter", lambda: s.highlight_selection(s.view.color), "orange")
        self._button("summary", "Adicionar ao resumo deste PDF", "summary", s.add_to_summary, "teal")
        self._button("open_summary", "Abrir o resumo", "docs", s.open_summary, "teal")

        self._title("Página")
        self._button("search", "Buscar no documento", "search", s.open_search, tip="Ctrl+F")
        self._button("text_mode", "Modo leitor (só o texto)", "text", s.open_text_mode)
        self._button("fit", "Ajustar à largura", "zoom_in", lambda: s.view and s.view.set_zoom(1.0), tip="Ctrl+0")
        self._button("crop", "Cortar e girar páginas", "crop", s.tool_crop, "indigo")
        self._button("number", "Numerar páginas", "numbers", s.tool_number, "indigo")

        self._title("Documento")
        self._button("ocr", "Fazer OCR", "textscan", s.tool_ocr, "orange")
        self._button("organize", "Organizar páginas", "grid", s.tool_organize, "purple")
        self._button("insert", "Incluir páginas", "plusrect", s.tool_insert, "teal")
        self._button("remove", "Remover páginas", "minusrect", s.tool_remove, "red")
        self._button("extract", "Extrair páginas", "docplus", s.tool_extract, "indigo")
        self._button("split", "Dividir em partes", "scissors", s.tool_split, "pink")
        self._button("merge", "Combinar com outros PDFs", "stack", s.tool_merge, "purple")
        self._button("dewarp", "Corrigir páginas curvas", "curve", s.tool_dewarp, "teal")
        self._button("protect", "Proteger com senha", "lock", s.tool_protect, "purple")
        self._button("duplicate", "Duplicar", "duplicate", s.tool_duplicate, "gray")

        self._title("Arquivo")
        self._button("share", "Compartilhar…", "share", s.tool_share, "green")
        self._button("favorite", "Favoritar", "star", s.tool_favorite, "yellow")
        self._button("rename", "Renomear", "pencil", s.tool_rename, "gray")
        self._button("move", "Mover para pasta", "folder_line", s.tool_move, "brown")
        self._button("external", "Abrir no leitor do Windows", "open", s.tool_external, "gray")
        self._button("details", "Ver detalhes do PDF", "info", s.tool_details, "gray")
        self._button("undo_file", "Desfazer última alteração", "undo", s.tool_undo_file, "gray")
        self._button("delete", "Excluir", "trash", s.tool_delete, "red")
        self.lay.addStretch(1)

    def update_state(self):
        s = self.screen
        item = s.item
        view = s.view
        tool = view.tool if view else "select"
        color = view.color if view else "yellow"
        for t in self.tools:
            t.active = (t.key == tool) if tool != "highlight" else (t.key == color)
            t.update()
        self.hint.setText({"select": "Selecione o texto com o mouse.",
                           "highlight": "Arraste sobre o texto para destacar.",
                           "erase": "Clique num destaque para apagá-lo."}[tool])
        has_sel = bool(view and view.has_selection())
        locked = bool(item and item.meta.locked)
        for k in ("copy", "summary"):
            self.buttons[k].setEnabled(has_sel)
        self.buttons["mark"].setEnabled(has_sel and not locked)
        self.buttons["undo_mark"].setEnabled(bool(s.session_marks) and not locked)
        self.buttons["open_summary"].setVisible(s.summary_item() is not None)
        if item is None:
            return
        lib = s.app.lib
        self.buttons["protect"].setText("  " + ("Remover senha" if locked else "Proteger com senha"))
        self.buttons["favorite"].setText("  " + ("Remover dos favoritos" if item.meta.favorite else "Favoritar"))
        for k in ("ocr", "organize", "insert", "remove", "extract", "split", "merge", "dewarp", "duplicate",
                  "crop", "number"):
            self.buttons[k].setEnabled(not locked)
        self.buttons["ocr"].setEnabled(not locked and lib.needs_ocr_attention(item))
        self.buttons["undo_file"].setEnabled(lib.can_undo(item))


def _twin(lib, item):
    """A outra versão do mesmo documento (original ↔ cópia com OCR), se existir."""
    if item.meta.is_ocr_result and item.meta.source_id:
        return lib.item(item.meta.source_id)
    return lib.ocr_copy(item)


def text_source(lib, item):
    """De onde vem o texto do modo leitor: a cópia com OCR, se houver; senão, o próprio PDF."""
    if item.meta.is_ocr_result:
        return item
    return lib.ocr_copy(item) or item


def mode_choices(lib, item):
    """Opções do controle no alto do leitor: [(rótulo, (modo, id do PDF))]."""
    twin = _twin(lib, item)
    if twin is None:
        return [("Página", ("page", item.id)), ("Texto", ("text", item.id))]
    original, ocr = (twin, item) if item.meta.is_ocr_result else (item, twin)
    return [("Original", ("page", original.id)), ("Com OCR", ("page", ocr.id)), ("Texto", ("text", ocr.id))]


class _ReaderBase(Screen):
    """Partes comuns aos dois modos: título, controle de versão, barra de busca e atalhos."""

    large_title = False
    mode = "page"

    def __init__(self, app, item_id, password=None):
        super().__init__(app)
        self.item_id = item_id
        self.item = app.lib.item(item_id)
        self.password = password
        self.add_back()
        self.big_title.hide()
        self.search_bar = SearchBar(self.run_search, self.step, self.close_search)
        self.layout().insertWidget(1, self.search_bar)
        self.search_btn = CircleButton("search", "Buscar (Ctrl+F)")
        self.search_btn.clicked.connect(self.open_search)
        self.nav.right.addWidget(self.search_btn)
        for seq, fn in (("F3", lambda: self.step(1)),
                        ("Shift+F3", lambda: self.step(-1)), ("Esc", self.escape)):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)

    def add_mode_switch(self):
        if self.item is None:
            return
        choices = mode_choices(self.app.lib, self.item)
        current = next((i for i, (_l, (m, iid)) in enumerate(choices) if m == self.mode and iid == self.item_id), 0)
        seg = Segmented([c[0] for c in choices], current, lambda i: self.switch_to(*choices[i][1]))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 6)
        row.addStretch(1)
        row.addWidget(seg)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.layout().insertWidget(1, holder)

    def switch_to(self, mode, item_id):
        if mode == self.mode and item_id == self.item_id:
            return
        page = self.current_page_index()
        query = self.search_bar.text() if self.search_bar.isVisible() else ""
        pw = self.password if item_id == self.item_id else None
        screen = (ReaderScreen(self.app, item_id, start_page=page, password=pw) if mode == "page"
                  else TextReaderScreen(self.app, item_id, start_page=page, password=pw))
        self.app.replace_top(screen)
        if query:
            screen.open_search()
            screen.search_bar.field.setText(query)
            screen.run_search(query)

    def current_page_index(self) -> int:
        return 0

    def open_search(self):
        self.search_bar.open()

    def escape(self):
        self.close_search()

    def close_search(self):
        if self.search_bar.isVisible():
            self.search_bar.field.setText("")
            self.search_bar.hide()
            self.clear_search()

    def run_search(self, _q):
        """Busca o texto do campo (cada modo implementa)."""

    def step(self, d):
        """Vai para a ocorrência seguinte (d=1) ou anterior (d=-1)."""

    def clear_search(self):
        pass


class ReaderScreen(_ReaderBase):
    mode = "page"

    def __init__(self, app, item_id: str, start_page: int = 0, title_extra: str = "", password=None):
        super().__init__(app, item_id, password)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.thumbs_btn = CircleButton("sidebar", "Miniaturas das páginas")
        self.thumbs_btn.clicked.connect(lambda: self.toggle_side("reader_thumbs"))
        self.nav.left.addWidget(self.thumbs_btn)
        zo = CircleButton("zoom_out", "Diminuir (Ctrl -)")
        zi = CircleButton("zoom_in", "Aumentar (Ctrl +)")
        self.panel_btn = CircleButton("sidebar_right", "Destacar e ferramentas")
        self.panel_btn.clicked.connect(lambda: self.toggle_side("reader_panel"))
        for b in (zo, zi, self.panel_btn):
            self.nav.right.addWidget(b)
        self._name = self.item.name if self.item else ""
        self._extra = title_extra
        self._version = self.item.version if self.item else None
        self._path = str(self.item.path) if self.item else None
        self.view = None
        self.text = None
        self.sidebar = None
        self.panel = None
        self.session_marks: list[list[tuple[int, str]]] = []   # destaques feitos agora (para desfazer)
        self._warned_no_text = False
        self.results: list = []
        self.index = -1
        self._search_job = None
        if self.item is None:
            self.set_title("")
            self.content.addWidget(EmptyState("docs", "PDF não encontrado", "O arquivo foi movido ou apagado."))
            self.finish_content()
            return
        app.lib.mark_opened(self.item)
        self.add_mode_switch()
        try:
            self.view = PagesView(self, self.item.path, self.password)
        except Exception as exc:  # noqa: BLE001
            self.content.addWidget(EmptyState("warning", "Não foi possível abrir o PDF", str(exc)))
            self.finish_content()
            return
        try:
            self.text = reader_text.TextLayer(self.item.path, self.password)
        except Exception:  # noqa: BLE001 - sem texto, o leitor continua mostrando as páginas
            self.text = None
        self.content.addWidget(self.view)
        self.finish_content()
        self.content.setContentsMargins(MARGIN, 0, MARGIN, 40)
        # miniaturas à esquerda, páginas no meio, painel à direita
        outer = self.layout()
        outer.removeWidget(self.scroll)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = ThumbSidebar(self, self.view.sizes)
        self.sidebar.page_clicked.connect(lambda i: self.view.go_to(i))
        self.panel = ToolPanel(self)
        h.addWidget(self.sidebar)
        h.addWidget(self.scroll, 1)
        h.addWidget(self.panel)
        outer.addWidget(row, 1)
        self.view.selection_changed.connect(self.panel.update_state)
        self._reload_marks()
        zo.clicked.connect(lambda: self.view.step_zoom(-1))
        zi.clicked.connect(lambda: self.view.step_zoom(1))
        self.counter = PageCounter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _v: self._update_counter())
        for seq, fn in (("Ctrl++", lambda: self.view.step_zoom(1)), ("Ctrl+=", lambda: self.view.step_zoom(1)),
                        ("Ctrl+-", lambda: self.view.step_zoom(-1)), ("Ctrl+0", lambda: self.view.set_zoom(1.0)),
                        ("Home", lambda: self.view.go_to(0)), ("End", lambda: self.view.go_to(10 ** 6)),
                        ("PgDown", lambda: self.view.go_to(self.view.current_page() + 1)),
                        ("PgUp", lambda: self.view.go_to(self.view.current_page() - 1)),
                        ("Ctrl+C", self.copy_selection), ("Ctrl+Z", self.undo_highlight)):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self._start = start_page
        self.panel.update_state()
        self._apply_sides()

    def current_page_index(self) -> int:
        return self.view.current_page() if self.view else 0

    # --- painéis laterais ---
    def toggle_side(self, key):
        default = True
        on = not bool(self.app.setting(key, default))
        self.app.set_setting(key, on)
        self._apply_sides()

    def _apply_sides(self):
        if self.sidebar is None or self.panel is None:
            return
        w = self.width() or 1100
        thumbs = bool(self.app.setting("reader_thumbs", True)) and w >= 640
        panel = bool(self.app.setting("reader_panel", True)) and w - (SIDEBAR_W if thumbs else 0) - PANEL_W >= 420
        self.sidebar.setVisible(thumbs)
        self.panel.setVisible(panel)
        if thumbs:
            self.sidebar.set_current(self.view.current_page())

    # --- busca nas páginas ---
    def run_search(self, _q=None):
        """Procura página por página (algumas por vez, sem travar a janela)."""
        if self.view is None:
            return
        q = self.search_bar.text().strip()
        if self._search_job is not None:
            self._search_job.stop()
            self._search_job = None
        self.results, self.index = [], -1
        self.view.hits, self.view.current_hit = {}, None
        self.view.update()
        if len(reader_text.Folded.fold_query(q)) < 2:
            self.search_bar.set_count("")
            return
        import pypdfium2 as pdfium
        with core.PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(str(self.item.path), password=self.password)
        state = {"page": 0, "pdf": pdf, "any_text": False}
        total = len(self.view.sizes)
        timer = QTimer(self)
        timer.setInterval(0)

        def tick():
            end = min(total, state["page"] + 8)
            with core.PDFIUM_LOCK:
                for i in range(state["page"], end):
                    hits = reader_text.search_page(pdf, i, q)
                    if hits:
                        self.view.hits[i] = hits
                        self.results.extend(hits)
                    elif not state["any_text"]:
                        pg = pdf[i]
                        tp = pg.get_textpage()
                        state["any_text"] = tp.count_chars() > 0
                        tp.close()
                        pg.close()
            if self.results and not state["any_text"]:
                state["any_text"] = True
            state["page"] = end
            if self.index < 0 and self.results:
                self.index = 0
                self.view.show_hit(self.results[0])
            self.view.update()
            if end >= total:
                timer.stop()
                self._search_job = None
                with core.PDFIUM_LOCK:
                    pdf.close()
                self._finish_count(state["any_text"])
            else:
                self.search_bar.set_count(f"{len(self.results)}…")

        timer.timeout.connect(tick)
        self._search_job = timer
        timer.start()

    def _finish_count(self, any_text):
        if self.results:
            self.search_bar.set_count(f"{self.index + 1} de {len(self.results)}")
            return
        if not any_text:
            twin = _twin(self.app.lib, self.item)
            if twin is not None and twin.meta.is_ocr_result:
                self.search_bar.set_count("Sem texto aqui")
                self.app.toast("Este é o original escaneado, sem texto. A busca funciona na cópia com OCR.",
                               "Buscar nela", lambda: self.switch_to("page", twin.id))
            else:
                self.search_bar.set_count("Sem texto")
                self.app.toast("Este PDF não tem texto pesquisável (é imagem). Faça o OCR para poder buscar.")
        else:
            self.search_bar.set_count("Nada encontrado")

    def step(self, d):
        if not self.results:
            return
        self.index = (self.index + d) % len(self.results)
        self.view.show_hit(self.results[self.index])
        if self._search_job is None:
            self.search_bar.set_count(f"{self.index + 1} de {len(self.results)}")

    def clear_search(self):
        if self._search_job is not None:
            self._search_job.stop()
            self._search_job = None
        self.results, self.index = [], -1
        if self.view is not None:
            self.view.hits, self.view.current_hit = {}, None
            self.view.update()

    def escape(self):
        if self.search_bar.isVisible():
            self.close_search()
        elif self.view is not None and self.view.has_selection():
            self.view.clear_selection()
        elif self.view is not None and self.view.tool != "select":
            self.set_tool("select")

    # --- seleção, destaques e resumo ---
    def set_tool(self, tool, color=None):
        if self.view is None:
            return
        if tool != "select" and self.item is not None and self.item.meta.locked:
            self.app.toast("Este PDF tem senha. Para destacar, crie antes uma cópia sem senha (“Remover senha”).")
            return
        self.view.tool = tool
        if color:
            self.view.color = color
            self.app.set_setting("reader_color", color)
        if tool == "highlight" and self.view.has_selection():
            self.highlight_selection(self.view.color)
        self.view.update()
        self.panel.update_state()

    def no_text_here(self):
        if self._warned_no_text:
            return
        self._warned_no_text = True
        twin = _twin(self.app.lib, self.item) if self.item else None
        if twin is not None and twin.meta.is_ocr_result:
            self.app.toast("Esta página é imagem, sem texto para selecionar. A cópia com OCR tem o texto.",
                           "Abrir", lambda: self.switch_to("page", twin.id))
        else:
            self.app.toast("Esta página não tem texto para selecionar (é imagem). Faça o OCR para poder "
                           "selecionar, destacar e resumir.")

    def selection_text(self) -> str:
        if self.view is None or self.text is None:
            return ""
        return "\n".join(self.text.text(p, a, b) for p, a, b in self.view.ranges()).replace("\r\n", "\n")

    def copy_selection(self):
        t = self.selection_text().strip()
        if not t:
            return
        QGuiApplication.clipboard().setText(t)
        self.app.toast("Texto copiado. Cole com Ctrl+V onde quiser.")

    def _modify(self, change, busy="Salvando…"):
        """Grava uma mudança no PDF (com "Desfazer última alteração") e atualiza o leitor."""
        out = {}
        ok = self.app.attempt(lambda: out.setdefault("r", self.app.lib.modify(self.item, change, keep_review=True)),
                              busy=busy)
        self._check_file()
        return out.get("r") if ok else None

    def highlight_selection(self, color):
        if self.view is None or self.text is None or self.item is None:
            return
        if self.item.meta.locked:
            self.app.toast("Este PDF tem senha. Para destacar, crie antes uma cópia sem senha (“Remover senha”).")
            return
        items = []
        for page, a, b in self.view.ranges():
            rects = self.text.pdf_rects(page, a, b)
            if rects:
                items.append((page, rects, color, self.text.text(page, a, b).strip()))
        if not items:
            return
        names = self._modify(lambda path: annotations.add_to_file(path, items))
        if names:
            self.session_marks.append(names)
            self.view.clear_selection()
        if self.panel:
            self.panel.update_state()

    def erase_mark(self, mark):
        if self.item is None or self.item.meta.locked:
            return
        if self._modify(lambda path: annotations.remove_from_file(path, [(mark.page, mark.ref)])):
            self.app.toast("Destaque apagado. Use Ctrl+Z ou “Desfazer última alteração” se precisar.")

    def recolor_mark(self, mark, color):
        if self.item is None or self.item.meta.locked:
            return
        self._modify(lambda path: annotations.recolor_in_file(path, mark.page, mark.ref, color))

    def undo_highlight(self):
        if not self.session_marks or self.item is None:
            return
        names = self.session_marks.pop()
        if self._modify(lambda path: annotations.remove_from_file(path, names)) is None:
            self.session_marks.append(names)
        else:
            self.app.toast("Destaque desfeito.")
        if self.panel:
            self.panel.update_state()

    def excerpts(self) -> list:
        """A seleção como trechos para o resumo: [(páginas, texto)]."""
        ranges = self.view.ranges() if self.view else []
        if not ranges or self.text is None:
            return []
        parts = [(p, self.text.text(p, a, b)) for p, a, b in ranges]
        parts = [(p, t) for p, t in parts if t.strip()]
        if not parts:
            return []
        text = reader_text.clean_excerpt("\n".join(t.replace("\r\n", "\n") for _p, t in parts))
        return [([p + 1 for p, _t in parts], text)] if text.strip() else []

    def add_to_summary(self):
        if self.item is None:
            return
        found = self.excerpts()
        if not found:
            self.app.toast("Selecione o trecho com o mouse e depois toque em “Adicionar ao resumo”.")
            return
        import summary
        res = {}
        if self.app.attempt(lambda: res.setdefault("item", summary.add_excerpts(self.app.lib, self.item, found)),
                            busy="Atualizando o resumo…"):
            new = res.get("item")
            if new is not None:
                self.view.clear_selection()
                self.app.toast(f"Trecho adicionado a “{new.name}”.", "Abrir", lambda: self.app.read(new))
        if self.panel:
            self.panel.update_state()

    def summary_item(self):
        if self.item is None:
            return None
        import summary
        return summary.find_summary(self.app.lib, self.item)

    def open_summary(self):
        s = self.summary_item()
        if s is not None:
            self.app.read(s)

    def context_menu(self, pos, mark=None):
        if self.view is None:
            return
        m = styled_menu(self.view)
        has_sel = self.view.has_selection()
        locked = bool(self.item and self.item.meta.locked)
        if mark is not None and not locked:
            menu_action(m, "Apagar este destaque", "eraser", lambda: self.erase_mark(mark), destructive=True)
            sub = m.addMenu(glyph_icon("highlighter", T.color("text"), 18), "Mudar a cor do destaque")
            for key, (label, _rgb) in annotations.COLORS.items():
                act = sub.addAction(self._color_icon(key), label)
                act.triggered.connect(lambda _c=False, k=key: self.recolor_mark(mark, k))
            m.addSeparator()
        if has_sel:
            menu_action(m, "Copiar (Ctrl+C)", "copy", self.copy_selection)
            if not locked:
                sub = m.addMenu(glyph_icon("highlighter", T.color("text"), 18), "Destacar")
                for key, (label, _rgb) in annotations.COLORS.items():
                    act = sub.addAction(self._color_icon(key), label)
                    act.triggered.connect(lambda _c=False, k=key: self.highlight_selection(k))
            menu_action(m, "Adicionar ao resumo deste PDF", "summary", self.add_to_summary)
            m.addSeparator()
        menu_action(m, "Buscar (Ctrl+F)", "search", self.open_search)
        menu_action(m, "Modo leitor (só o texto)", "text", self.open_text_mode)
        menu_action(m, "Ajustar à largura (Ctrl+0)", "zoom_in", lambda: self.view.set_zoom(1.0))
        m.addSeparator()
        menu_action(m, "Compartilhar…", "share", self.tool_share)
        menu_action(m, "Abrir no leitor de PDF do Windows", "open", self.tool_external)
        menu_action(m, "Ver detalhes do PDF", "info", self.tool_details)
        m.exec(self.view.mapToGlobal(pos))

    @staticmethod
    def _color_icon(key):
        from PySide6.QtGui import QIcon, QPixmap
        pm = QPixmap(36, 36)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 50), 1.5))
        p.setBrush(highlight_qcolor(key))
        p.drawEllipse(QRectF(4, 4, 28, 28))
        p.end()
        pm.setDevicePixelRatio(2)
        return QIcon(pm)

    # --- o arquivo mudou (destaque, outra ferramenta, outro aparelho) ---
    def _reload_marks(self):
        if self.view is None or self.item is None:
            return
        found = annotations.read_marks(self.item.path, self.password)
        marks = {}
        for page, lst in found.items():
            if self.text is None or page >= self.text.count:
                continue
            geom = self.text.geom(page)
            marks[page] = [(mk, [geom.rect_to_view(r) for r in mk.rects]) for mk in lst]
        self.view.marks = marks

    def _check_file(self):
        """Confere se o PDF mudou desde que foi aberto e recarrega o que for preciso."""
        if self.view is None:
            return
        item = self.app.lib.item(self.item_id)
        if item is None:
            return
        changed_file = item.version != self._version or str(item.path) != self._path
        self.item = item
        self._name = item.name
        if not changed_file:
            return
        try:
            sizes = page_sizes(item.path, self.password)
        except Exception:  # noqa: BLE001
            return
        if len(sizes) != len(self.view.sizes):
            # páginas incluídas, removidas ou reorganizadas: abre de novo, na mesma página
            page = min(self.view.current_page(), len(sizes) - 1)
            self.app.replace_top(ReaderScreen(self.app, self.item_id, start_page=max(0, page),
                                              title_extra=self._extra, password=self.password))
            return
        self._version, self._path = item.version, str(item.path)
        self.view.sizes = sizes
        self.view._layout_key = None
        self.view.cache.invalidate(item.path)
        if self.text is not None:
            self.text.close()
        try:
            self.text = reader_text.TextLayer(item.path, self.password)
        except Exception:  # noqa: BLE001
            self.text = None
        self.view.clear_selection()
        self._reload_marks()
        self.view.relayout()
        if self.sidebar is not None:
            self.sidebar.sizes = sizes
            self.sidebar.list._layout()
            self.sidebar.list.update()

    # --- ferramentas do painel (as mesmas da tela do PDF) ---
    def _current_item(self):
        self.item = self.app.lib.item(self.item_id) or self.item
        return self.item

    def open_text_mode(self):
        if self.item is not None:
            self.switch_to("text", text_source(self.app.lib, self.item).id)

    def tool_ocr(self):
        self.app.actions.request_ocr(self._current_item())

    def tool_organize(self):
        self.app.organize(self._current_item())

    def tool_insert(self):
        import screens
        screens.include_pages_dialog(self.app, self._current_item())
        self._check_file()

    def tool_remove(self):
        import screens
        self.app.push(screens.PagePickerScreen(self.app, self.item_id, "remove"))

    def tool_extract(self):
        import screens
        self.app.push(screens.PagePickerScreen(self.app, self.item_id, "extract"))

    def tool_split(self):
        import screens
        screens.split_dialog(self.app, self._current_item())

    def tool_merge(self):
        import screens
        self.app.push(screens.MergeScreen(self.app, preselection=[self.item_id]))

    def tool_dewarp(self):
        import screens
        screens.dewarp_dialog(self.app, self._current_item())

    def tool_crop(self):
        import page_tools
        page_tools.crop_dialog(self.app, self._current_item(), self.current_page_index())
        self._check_file()

    def tool_number(self):
        import page_tools
        page_tools.number_dialog(self.app, self._current_item())
        self._check_file()

    def tool_protect(self):
        import screens
        item = self._current_item()
        if item.meta.locked:
            screens.unprotect_dialog(self.app, item)
        else:
            screens.protect_dialog(self.app, item)

    def tool_duplicate(self):
        self.app.actions.duplicate(self._current_item())

    def tool_share(self):
        self.app.actions.share([self._current_item()])

    def tool_favorite(self):
        self.app.actions.toggle_favorite(self._current_item())
        if self.panel:
            self.panel.update_state()

    def tool_rename(self):
        self.app.actions.rename(self._current_item())
        self._check_file()

    def tool_move(self):
        self.app.actions.move([self._current_item()])
        self._check_file()

    def tool_external(self):
        self.app.open_external(self._current_item())

    def tool_details(self):
        self.app.open_document(self.item_id)

    def tool_undo_file(self):
        if self.app.actions.undo(self._current_item()):
            self.session_marks.clear()
            self._check_file()

    def tool_delete(self):
        self.app.actions.delete([self._current_item()], after=self.app.back)

    def refresh(self):
        if self.view is not None:
            self._check_file()
            self.view.update()
        if self.panel is not None:
            self.panel.update_state()
        self._update_counter()

    def on_shown(self):
        super().on_shown()
        if self.view is not None:
            self.view.relayout()
            if self._start:
                QTimer.singleShot(0, lambda: self.view.go_to(self._start))
                self._start = 0
            self.view.setFocus()
        self._apply_sides()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "view", None) is not None:
            self._apply_sides()
            self.view.relayout()
            self._update_counter()

    def _update_counter(self):
        if getattr(self, "view", None) is None:
            return
        n = len(self.view.sizes)
        cur = self.view.current_page()
        zoom = f" · {round(self.view.zoom * 100)}%" if abs(self.view.zoom - 1.0) > 1e-6 else ""
        self.counter.set_text(f"Página {cur + 1} de {n}{zoom}")
        from PySide6.QtCore import QPoint
        origin = self.scroll.mapTo(self, QPoint(0, 0))
        x = origin.x() + (self.scroll.width() - self.counter.width()) // 2
        self.counter.move(x, self.height() - self.counter.height() - 16)
        self.counter.raise_()
        self.counter.show()
        if self.sidebar is not None and self.sidebar.isVisible():
            self.sidebar.set_current(cur)
        self.set_title(self._name + (f" · {self._extra}" if self._extra else ""))

    def closing(self):
        self.clear_search()
        if getattr(self, "view", None) is not None:
            self.view.cache.shutdown()
        if getattr(self, "sidebar", None) is not None:
            self.sidebar.shutdown()
        if getattr(self, "text", None) is not None:
            self.text.close()
            self.text = None

    def sizeHint(self):
        return QSize(800, 600)


# --- Modo leitor (só o texto) ----------------------------------------------------------

BACKGROUNDS = {
    "white": ("Branco", "#FFFFFF", "#1C1C1E"),
    "sepia": ("Sépia", "#F6EEDC", "#3B2F20"),
    "dark": ("Escuro", "#1C1C1E", "#E8E8EA"),
}
FONTS = {
    "sans": ("Sem serifa", ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"]),
    "serif": ("Com serifa", ["Georgia", "Cambria", "Times New Roman", "Noto Serif", "DejaVu Serif"]),
}


class ReadingBrowser(QTextBrowser):
    """Texto numa coluna de largura confortável (cerca de 75 caracteres), centralizada na janela."""

    COLUMN = 820

    def resizeEvent(self, e):
        m = max(0, (self.width() - self.COLUMN) // 2)
        self.setViewportMargins(m, 0, m, 0)
        super().resizeEvent(e)


class TextReaderScreen(_ReaderBase):
    """O texto do documento em parágrafos, como uma nota (o mesmo modo leitor do iPhone)."""

    mode = "text"

    def __init__(self, app, item_id: str, start_page: int = 0, password=None):
        super().__init__(app, item_id, password)
        self.scroll.hide()
        self.matches: list[tuple[int, int]] = []
        self.index = -1
        self.size = int(app.setting("reader_size", 18) or 18)
        self.family = str(app.setting("reader_font", "sans") or "sans")
        self.bg = str(app.setting("reader_bg", "white") or "white")
        smaller = TextButton("A−")
        smaller.setToolTip("Letra menor (Ctrl -)")
        smaller.clicked.connect(lambda: self.set_size(self.size - 2))
        bigger = TextButton("A+", bold=True)
        bigger.setToolTip("Letra maior (Ctrl +)")
        bigger.clicked.connect(lambda: self.set_size(self.size + 2))
        self.more = CircleButton("ellipsis", "Fonte, fundo e mais opções")
        self.more.clicked.connect(self._menu)
        for b in (smaller, bigger, self.more):
            self.nav.right.addWidget(b)
        self.browser = ReadingBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setFrameShape(QTextBrowser.NoFrame)
        self.browser.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.layout().addWidget(self.browser, 1)
        self.pages: list = []
        self._start = start_page
        if self.item is None:
            self.set_title("")
            return
        app.lib.mark_opened(self.item)
        self.add_mode_switch()
        self.set_title(f"{self.item.name} · modo leitor")
        try:
            self.pages = reader_text.reader_pages(self.item.path, self.password)
        except Exception as exc:  # noqa: BLE001
            self.pages = []
            self.app.show_error(f"Não foi possível ler o texto: {exc}")
        for seq, fn in (("Ctrl++", lambda: self.set_size(self.size + 2)), ("Ctrl+=", lambda: self.set_size(self.size + 2)),
                        ("Ctrl+-", lambda: self.set_size(self.size - 2))):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self.render()

    @property
    def is_empty(self) -> bool:
        return not any(p.paragraphs for p in self.pages)

    def html(self) -> str:
        import html as h
        bg, fg = BACKGROUNDS[self.bg][1], BACKGROUNDS[self.bg][2]
        review = set(self.item.meta.review_pages or [])
        parts = []
        if self.is_empty:
            parts.append(f"<p style='color:{fg}'>Este PDF não tem texto para o modo leitor: as páginas são imagens. "
                         "Faça o OCR e abra o modo leitor na cópia com OCR.</p>")
        for pg in self.pages:
            tag = " · <span style='color:#D97706'>revisar (baixa confiança no OCR)</span>" if pg.number in review else ""
            parts.append(f"<a name='p{pg.number}'></a><p style='color:#8E8E93; font-size:{max(11, self.size - 6)}px;"
                         f" margin-top:{18 if pg.number > 1 else 0}px'>— Página {pg.number}{tag} —</p>")
            if not pg.paragraphs:
                parts.append("<p style='color:#8E8E93'><i>(sem texto)</i></p>")
            for para in pg.paragraphs:
                parts.append(f"<p style='line-height:150%'>{h.escape(para)}</p>")
        return (f"<html><body style='background:{bg}; color:{fg}'>"
                f"<div style='margin: 0'>{''.join(parts)}</div></body></html>")

    def render(self):
        bg, fg = BACKGROUNDS[self.bg][1], BACKGROUNDS[self.bg][2]
        f = QFont()
        f.setFamilies(FONTS[self.family][1])
        f.setPixelSize(self.size)
        self.browser.setFont(f)
        self.browser.document().setDefaultFont(f)
        self.browser.setStyleSheet(f"QTextBrowser {{ background: {bg}; color: {fg}; border: none; }}")
        self.browser.viewport().setStyleSheet(f"background: {bg};")
        self.browser.document().setDocumentMargin(28)
        pos = self.browser.verticalScrollBar().value()
        self.browser.setHtml(self.html())
        self.browser.verticalScrollBar().setValue(pos)
        if self.search_bar.isVisible() and self.search_bar.text().strip():
            self.run_search()

    def set_size(self, n):
        self.size = max(12, min(40, n))
        self.app.set_setting("reader_size", self.size)
        self.render()

    def set_font(self, key):
        self.family = key
        self.app.set_setting("reader_font", key)
        self.render()

    def set_bg(self, key):
        self.bg = key
        self.app.set_setting("reader_bg", key)
        self.render()

    def on_shown(self):
        super().on_shown()
        if self._start:
            n = self._start + 1
            QTimer.singleShot(0, lambda: self.browser.scrollToAnchor(f"p{n}"))
            self._start = 0
        self.browser.setFocus()

    def current_page_index(self) -> int:
        from PySide6.QtCore import QPoint
        cur = self.browser.cursorForPosition(QPoint(20, 20))
        text = self.browser.toPlainText()[:cur.position()]
        import re
        found = re.findall(r"— Página (\d+)", text)
        return int(found[-1]) - 1 if found else 0

    def _menu(self):
        m = styled_menu(self.more)
        menu_action(m, "Buscar no texto (Ctrl+F)", "search", self.open_search)
        sub = m.addMenu("Fonte")
        for key, (label, _f) in FONTS.items():
            menu_action(sub, label, None, lambda k=key: self.set_font(k), checked=self.family == key)
        sub2 = m.addMenu("Fundo")
        for key, (label, _b, _f) in BACKGROUNDS.items():
            menu_action(sub2, label, None, lambda k=key: self.set_bg(k), checked=self.bg == key)
        m.addSeparator()
        menu_action(m, "Copiar todo o texto", "copy", self.copy_all)
        menu_action(m, "Ver as páginas", "docs", lambda: self.switch_to("page", self.item_id))
        m.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def copy_all(self):
        text = "\n\n".join(f"— Página {p.number} —\n\n" + ("\n\n".join(p.paragraphs) or "(sem texto)")
                            for p in self.pages)
        QGuiApplication.clipboard().setText(text)
        self.app.toast("Texto copiado. Cole com Ctrl+V onde quiser.")

    # --- busca no texto ---
    def run_search(self, _q=None):
        q = self.search_bar.text()
        self.matches = reader_text.find_all(self.browser.toPlainText(), q) if len(
            reader_text.Folded.fold_query(q)) >= 2 else []
        self.index = 0 if self.matches else -1
        self._highlight()
        if not q.strip():
            self.search_bar.set_count("")
        elif not self.matches:
            self.search_bar.set_count("Nada encontrado")

    def step(self, d):
        if not self.matches:
            return
        self.index = (self.index + d) % len(self.matches)
        self._highlight()

    def clear_search(self):
        self.matches, self.index = [], -1
        self.browser.setExtraSelections([])

    def _highlight(self):
        sels = []
        for k, (a, b) in enumerate(self.matches):
            sel = QTextEdit.ExtraSelection()
            cur = QTextCursor(self.browser.document())
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(255, 149, 0, 200) if k == self.index else QColor(255, 214, 10, 150))
            fmt.setForeground(QColor("#000000"))
            sel.cursor, sel.format = cur, fmt
            sels.append(sel)
        self.browser.setExtraSelections(sels)
        if self.matches and self.index >= 0:
            a, b = self.matches[self.index]
            cur = QTextCursor(self.browser.document())
            cur.setPosition(a)
            self.browser.setTextCursor(cur)
            self.browser.ensureCursorVisible()
            self.search_bar.set_count(f"{self.index + 1} de {len(self.matches)}")
