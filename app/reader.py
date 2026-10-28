"""
Leitor de PDF do próprio Prumo.

- Páginas: rolagem contínua, zoom e troca rápida entre o original e a cópia com OCR.
- Modo leitor: só o texto (do OCR ou do próprio PDF), em parágrafos, com tamanho da letra,
  fonte e fundo (branco, sépia, escuro) à escolha, para ler com conforto e copiar trechos.
- Busca (Ctrl+F) nos dois modos: ignora acentos e maiúsculas, destaca as ocorrências e
  anda entre elas com Enter / Shift+Enter (ou F3 / Shift+F3).

Atalhos: Ctrl+roda do mouse ou Ctrl+ / Ctrl- para zoom, Ctrl+0 ajusta à largura,
Page Up / Page Down e as setas rolam, Home / End vão ao começo e ao fim.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPen, QShortcut,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QTextBrowser, QTextEdit, QWidget

import core
import reader_text
from ios_kit import (CircleButton, EmptyState, Label, Screen, SearchField, TextButton, menu_action, styled_menu)
from ios_theme import MARGIN, T, font, glyph_icon

GAP = 14
MAX_W = 900            # largura da página com zoom 100%, se a janela couber
ZOOMS = [0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]


def page_sizes(path, password: str | None = None) -> list[tuple[float, float]]:
    import pypdfium2 as pdfium

    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path), password=password)
        try:
            return [tuple(pdf.get_page_size(i)) for i in range(len(pdf))]
        finally:
            pdf.close()


class _Signals(QObject):
    done = Signal(int, int, object)


class _Render(QRunnable):
    def __init__(self, path, page, px, signals, password=None):
        super().__init__()
        self.path, self.page, self.px, self.signals, self.password = path, page, px, signals, password

    def run(self):
        from services import render_page
        img = render_page(self.path, self.page, self.px, self.password)
        self.signals.done.emit(self.page, self.px, img if img is not None else QImage())


class PageCache(QObject):
    """Páginas renderizadas sob demanda, com poucas na memória (páginas grandes ocupam muito)."""

    ready = Signal(int)

    def __init__(self, path, limit=14, password=None):
        super().__init__()
        self.path, self.limit, self.password = str(path), limit, password
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
            self.pool.start(_Render(self.path, page, px, self.signals, self.password))
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

    def __init__(self, screen, path, password=None):
        super().__init__()
        self.screen = screen
        self.sizes = page_sizes(path, password)
        self.cache = PageCache(path, password=password)
        self.cache.ready.connect(lambda _p: self.update())
        self.zoom = 1.0
        self.hits: dict[int, list] = {}          # página → ocorrências da busca
        self.current_hit = None
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
            for hit in self.hits.get(i, ()):
                current = hit is self.current_hit
                for hr in self.hit_rects(hit):
                    p.setPen(QPen(QColor(230, 120, 0), 2) if current else Qt.NoPen)
                    p.setBrush(QColor(255, 149, 0, 110) if current else QColor(255, 214, 10, 105))
                    p.drawRoundedRect(hr.adjusted(-1.5, -1.5, 1.5, 1.5), 2.5, 2.5)

    def hit_rects(self, hit) -> list[QRectF]:
        r = self.page_rect(hit.page)
        s = r.width() / max(1.0, self.sizes[hit.page][0])
        return [QRectF(r.x() + x0 * s, r.y() + y0 * s, (x1 - x0) * s, (y1 - y0) * s)
                for x0, y0, x1, y1 in hit.rects]

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
                        ("Shift+F3", lambda: self.step(-1)), ("Esc", self.close_search)):
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
        zo = CircleButton("zoom_out", "Diminuir (Ctrl -)")
        zi = CircleButton("zoom_in", "Aumentar (Ctrl +)")
        self.more = CircleButton("ellipsis", "Mais opções")
        self.more.clicked.connect(self._menu)
        for b in (zo, zi, self.more):
            self.nav.right.addWidget(b)
        self._name = self.item.name if self.item else ""
        self._extra = title_extra
        self.view = None
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

    def current_page_index(self) -> int:
        return self.view.current_page() if self.view else 0

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

    def _menu(self):
        if self.item is None:
            return
        m = styled_menu(self.more)
        menu_action(m, "Buscar (Ctrl+F)", "search", self.open_search)
        menu_action(m, "Modo leitor (só o texto)", "text",
                    lambda: self.switch_to("text", text_source(self.app.lib, self.item).id))
        menu_action(m, "Ajustar à largura (Ctrl+0)", "zoom_in", lambda: self.view and self.view.set_zoom(1.0))
        m.addSeparator()
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
        self.set_title(self._name + (f" · {self._extra}" if self._extra else ""))

    def closing(self):
        self.clear_search()
        if getattr(self, "view", None) is not None:
            self.view.cache.shutdown()

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
