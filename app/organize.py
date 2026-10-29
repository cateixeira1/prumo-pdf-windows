"""
Organizar páginas: grade de miniaturas com arrastar e soltar e rolagem automática
perto das bordas (como no iPhone), girar, excluir e desfazer. Nada muda no arquivo
até clicar em "Salvar"; depois, "Desfazer última alteração" volta o PDF inteiro.

Mouse:
- clique seleciona; Ctrl+clique soma ou tira; Shift+clique seleciona um trecho
- arrastar move a página (ou todas as selecionadas); perto do alto ou do pé da
  janela a lista rola sozinha, mais rápido quanto mais perto da borda
- Ctrl+roda do mouse aumenta ou diminui as miniaturas
- a lupa (que aparece ao passar o mouse), o duplo clique ou a tecla Espaço mostram a página grande
- arrastar a partir de um espaço vazio desenha um retângulo que seleciona as páginas dentro dele
Teclado: Delete exclui, Ctrl+A seleciona tudo, Ctrl+Z desfaz, Ctrl+S salva, Esc limpa a seleção.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ios_kit import Label, Screen, TextButton, alert
from ios_theme import MARGIN, SPACING, TILE_RADIUS, T, font, glyph_icon, paint_glyph

DRAG_START = 6          # pixels de movimento antes de virar arraste
EDGE = 70               # faixa perto da borda que liga a rolagem automática
MAX_SPEED = 26          # pixels por quadro, bem na borda
LABEL_H = 26
PAD = 8


class PageModel:
    """Ordem atual das páginas: lista de (página original começando em 1, rotação em graus)."""

    def __init__(self, total: int):
        self.original = [(i + 1, 0) for i in range(total)]
        self.entries: list[tuple[int, int]] = list(self.original)
        self.history: list[list[tuple[int, int]]] = []

    def snapshot(self):
        self.history.append(list(self.entries))
        del self.history[:-50]

    def undo(self) -> bool:
        if not self.history:
            return False
        self.entries = self.history.pop()
        return True

    @property
    def changed(self) -> bool:
        return self.entries != self.original

    def move(self, positions: list[int], to: int) -> list[int]:
        """Move as posições (índices) para antes do índice `to` da lista atual. Devolve as novas posições."""
        positions = sorted(set(positions))
        moving = [self.entries[i] for i in positions]
        before = sum(1 for i in positions if i < to)
        rest = [e for i, e in enumerate(self.entries) if i not in set(positions)]
        at = max(0, min(len(rest), to - before))
        self.snapshot()
        self.entries = rest[:at] + moving + rest[at:]
        return list(range(at, at + len(moving)))

    def rotate(self, positions, delta):
        self.snapshot()
        for i in positions:
            p, r = self.entries[i]
            self.entries[i] = (p, (r + delta) % 360)

    def delete(self, positions):
        self.snapshot()
        drop = set(positions)
        self.entries = [e for i, e in enumerate(self.entries) if i not in drop]


class PageGrid(QWidget):
    """Grade desenhada à mão: assim o arraste, a linha de inserção e a rolagem ficam leves."""

    selection_changed = Signal()
    changed = Signal()

    def __init__(self, screen, item, model: PageModel):
        super().__init__()
        self.screen, self.item, self.model = screen, item, model
        self.thumbs = screen.app.hub.thumbs
        self.cell_min = 150
        self.selected: set[int] = set()
        self.anchor: int | None = None
        self._press_pos: QPoint | None = None
        self._press_index: int | None = None
        self.dragging = False
        self.drop_index: int | None = None
        self.cursor_pos = QPointF()
        self.hover_index: int | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.thumbs.ready.connect(lambda _k: self.update())
        T.changed.connect(self.update)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._auto_scroll)

    # --- geometria ---
    def columns(self, w=None) -> int:
        w = w or self.width()
        return max(1, (w + SPACING) // (self.cell_min + SPACING))

    def cell_size(self, w=None) -> tuple[float, float]:
        w = w or self.width()
        cols = self.columns(w)
        cw = (w - SPACING * (cols - 1)) / cols
        return cw, (cw - 2 * PAD) * 1.36 + 2 * PAD + LABEL_H

    def cell_rect(self, i: int) -> QRectF:
        cols = self.columns()
        cw, ch = self.cell_size()
        r, c = divmod(i, cols)
        return QRectF(c * (cw + SPACING), r * (ch + SPACING), cw, ch)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        n = len(self.model.entries)
        if not n or w <= 0:
            return 120
        cols = self.columns(w)
        _, ch = self.cell_size(w)
        rows = (n + cols - 1) // cols
        return int(rows * ch + (rows - 1) * SPACING)

    def sizeHint(self):
        return QSize(600, self.heightForWidth(max(600, self.width())))

    def relayout(self):
        self.setFixedHeight(self.heightForWidth(self.width()))
        self.update()

    def resizeEvent(self, e):
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(e)

    def index_at(self, pos: QPointF) -> int | None:
        for i in range(len(self.model.entries)):
            if self.cell_rect(i).contains(pos):
                return i
        return None

    def insertion_at(self, pos: QPointF) -> int:
        """
        Índice de inserção mais próximo do cursor. Também guarda onde desenhar a linha:
        no fim de uma fileira, a linha fica à direita da última página dela (e não no
        começo da fileira seguinte), que é onde o usuário está apontando.
        """
        n = len(self.model.entries)
        self.drop_line = None
        if n == 0:
            return 0
        cols = self.columns()
        cw, ch = self.cell_size()
        rows = (n + cols - 1) // cols
        row = max(0, min(rows - 1, int(max(0.0, pos.y()) // (ch + SPACING))))
        in_row = min(cols, n - row * cols)
        col = max(0, min(in_row, int(round(max(0.0, pos.x()) / (cw + SPACING)))))
        idx = row * cols + col
        y0 = row * (ch + SPACING) + 6
        y1 = y0 + ch - 12
        if col == 0:
            x = 0.0
        elif col >= in_row:
            x = self.cell_rect(idx - 1).right() + SPACING / 2
        else:
            x = self.cell_rect(idx).left() - SPACING / 2
        self.drop_line = (max(2.0, min(self.width() - 2.0, x)), y0, y1)
        return idx

    # --- desenho ---
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        exposed = QRectF(ev.rect())
        for i, (page, rot) in enumerate(self.model.entries):
            r = self.cell_rect(i)
            if not r.intersects(exposed):
                continue
            self._paint_cell(p, r, i, page, rot, dim=self.dragging and i in self.selected)
        if self.dragging and self.drop_index is not None:
            self._paint_insertion(p, self.drop_index)
            self._paint_ghost(p)

    def _page_rect(self, r: QRectF, rot: int) -> QRectF:
        area = QRectF(r.x() + PAD, r.y() + PAD, r.width() - 2 * PAD, r.height() - 2 * PAD - LABEL_H)
        return area

    def _paint_thumb(self, p: QPainter, area: QRectF, page: int, rot: int, opacity=1.0):
        px = int(max(area.width(), area.height()) * self.devicePixelRatioF())
        img = self.thumbs.get(self.item.path, self.item.version, page - 1, px)
        p.save()
        p.setOpacity(opacity)
        if img is None or img.isNull():
            w, h = area.width() * 0.72, area.width() * 0.72 * 1.41
            if rot in (90, 270):
                w, h = h, w
            scale = min(area.width() / w, area.height() / h)
            tr = QRectF(0, 0, w * scale, h * scale)
            tr.moveCenter(area.center())
            p.setPen(QPen(T.color("thumb_border"), 0.8))
            p.setBrush(QColor("white"))
            p.drawRoundedRect(tr, 3, 3)
            p.restore()
            return
        iw, ih = img.width(), img.height()
        rw, rh = (ih, iw) if rot in (90, 270) else (iw, ih)
        scale = min(area.width() / rw, area.height() / rh)
        tw, th = rw * scale, rh * scale
        c = area.center()
        p.translate(c)
        p.rotate(rot)
        dw, dh = iw * scale, ih * scale
        target = QRectF(-dw / 2, -dh / 2, dw, dh)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 26))
        p.drawRoundedRect(target.translated(0, 1.5), 3, 3)
        p.drawImage(target, img)
        p.setPen(QPen(T.color("thumb_border"), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(target, 3, 3)
        p.restore()
        _ = (tw, th)

    def view_rect(self, i: int) -> QRectF:
        """Botão redondo com a lupa, no canto de cima à esquerda da página (aparece com o mouse em cima)."""
        r = self.cell_rect(i)
        return QRectF(r.x() + 10, r.y() + 10, 30, 30)

    def _paint_cell(self, p, r, i, page, rot, dim=False):
        sel = i in self.selected
        if sel:
            c = QColor(T.color("blue"))
            c.setAlpha(36)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 12, 12)
        area = self._page_rect(r, rot)
        self._paint_thumb(p, area, page, rot, 0.3 if dim else 1.0)
        if sel:
            p.setPen(QPen(T.color("blue"), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 11, 11)
            cr = QRectF(r.right() - 34, r.y() + 10, 24, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("blue"))
            p.drawEllipse(cr)
            paint_glyph(p, cr.adjusted(4, 4, -4, -4), "check", QColor("white"), 3)
        p.setPen(T.color("blue") if sel else T.color("text"))
        p.setFont(font(13, 600))
        label = str(i + 1)
        if page != i + 1:
            label += f"  ·  era {page}"
        p.drawText(QRectF(r.x(), r.bottom() - LABEL_H - 2, r.width(), LABEL_H), Qt.AlignCenter, label)
        if rot:
            p.setPen(T.color("secondary"))
            p.setFont(font(11, 600))
            p.drawText(QRectF(r.x() + 44 if i == self.hover_index else r.x() + 10, r.y() + 8, 60, 18),
                       Qt.AlignLeft | Qt.AlignVCenter, f"{rot}°")
        if i == self.hover_index and not self.dragging:
            vr = self.view_rect(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 40))
            p.drawEllipse(vr.translated(0, 1))
            p.setBrush(T.color("panel"))
            p.drawEllipse(vr)
            paint_glyph(p, vr.adjusted(7, 7, -7, -7), "zoom_in", T.color("blue"), 2.2)

    def _paint_insertion(self, p, idx):
        line = getattr(self, "drop_line", None)
        if not line:
            return
        x, y0, y1 = line
        p.setPen(QPen(T.color("blue"), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x, y0), QPointF(x, y1))
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("blue"))
        p.drawEllipse(QPointF(x, y0), 5, 5)
        p.drawEllipse(QPointF(x, y1), 5, 5)

    def _paint_ghost(self, p):
        """A página "levantada", seguindo o cursor (com o total quando são várias)."""
        if self._press_index is None:
            return
        cw, ch = self.cell_size()
        w = min(cw, 150) * 0.85
        h = (w - 2 * PAD) * 1.36 + 2 * PAD
        r = QRectF(self.cursor_pos.x() - w / 2, self.cursor_pos.y() - h * 0.4, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(r.translated(0, 6), 12, 12)
        p.setBrush(T.color("tile"))
        p.drawRoundedRect(r, 12, 12)
        idx = self._press_index if self._press_index in self.selected else min(self.selected)
        page, rot = self.model.entries[idx]
        self._paint_thumb(p, r.adjusted(PAD, PAD, -PAD, -PAD), page, rot)
        n = len(self.selected)
        if n > 1:
            badge = QRectF(r.right() - 16, r.top() - 10, 28, 28)
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("red"))
            p.drawEllipse(badge)
            p.setPen(QColor("white"))
            p.setFont(font(13, 700))
            p.drawText(badge, Qt.AlignCenter, str(n))

    # --- mouse ---
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        i = self.index_at(pos)
        if i is not None and i == self.hover_index and self.view_rect(i).contains(pos):
            self._press_pos = self._press_index = None
            self.screen.preview(i)
            return
        self._press_pos = e.position().toPoint()
        self._press_index = i
        mods = e.modifiers()
        if i is None:
            if not mods & (Qt.ControlModifier | Qt.ShiftModifier):
                self.selected.clear()
                self.selection_changed.emit()
                self.update()
            return
        if mods & Qt.ShiftModifier and self.anchor is not None:
            a, b = sorted((self.anchor, i))
            self.selected = set(range(a, b + 1)) | (self.selected if mods & Qt.ControlModifier else set())
        elif mods & Qt.ControlModifier:
            self.selected.symmetric_difference_update({i})
            self.anchor = i
        elif i not in self.selected:
            self.selected = {i}
            self.anchor = i
        self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, e):
        if not e.buttons():
            i = self.index_at(e.position())
            if i != self.hover_index:
                self.hover_index = i
                self.setToolTip("" if i is None else "Clique na lupa (ou dê dois cliques) para ver a página grande")
                self.update()
            on_view = i is not None and self.view_rect(i).contains(e.position())
            self.setCursor(Qt.PointingHandCursor if on_view else Qt.ArrowCursor)
        if self._press_pos is None or self._press_index is None or not (e.buttons() & Qt.LeftButton):
            return
        if not self.dragging:
            if (e.position().toPoint() - self._press_pos).manhattanLength() < DRAG_START:
                return
            if self._press_index not in self.selected:
                self.selected = {self._press_index}
                self.selection_changed.emit()
            self.dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.timer.start()
        self.cursor_pos = e.position()
        self.drop_index = self.insertion_at(self.cursor_pos)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.dragging:
            self.timer.stop()
            self.dragging = False
            self.unsetCursor()
            if self.drop_index is not None and self.selected:
                old = list(self.model.entries)
                new_pos = self.model.move(sorted(self.selected), self.drop_index)
                if self.model.entries == old:
                    self.model.history.pop()
                else:
                    self.selected = set(new_pos)
                    self.anchor = new_pos[0]
                    self.changed.emit()
            self.drop_index = None
            self.selection_changed.emit()
            self.update()
        elif self._press_index is not None and not e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            # clique simples numa página já selecionada no meio de várias: fica só ela
            if len(self.selected) > 1 and self._press_index in self.selected:
                self.selected = {self._press_index}
                self.anchor = self._press_index
                self.selection_changed.emit()
                self.update()
        self._press_pos = None
        self._press_index = None

    def leaveEvent(self, e):
        self.hover_index = None
        self.update()
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):
        i = self.index_at(e.position())
        if i is not None:
            self.screen.preview(i)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            step = 20 if e.angleDelta().y() > 0 else -20
            self.set_cell_min(self.cell_min + step)
            e.accept()
        else:
            e.ignore()

    def set_cell_min(self, v):
        self.cell_min = max(90, min(340, v))
        self.relayout()

    # --- rolagem automática durante o arraste ---
    def _auto_scroll(self):
        if not self.dragging:
            self.timer.stop()
            return
        sa = self.screen.scroll
        vp = sa.viewport()
        y = vp.mapFromGlobal(QCursor.pos()).y()
        h = vp.height()
        speed = 0.0
        if y < EDGE:
            speed = -MAX_SPEED * min(1.0, (EDGE - y) / EDGE)
        elif y > h - EDGE:
            speed = MAX_SPEED * min(1.0, (y - (h - EDGE)) / EDGE)
        if speed:
            bar = sa.verticalScrollBar()
            before = bar.value()
            bar.setValue(int(before + speed))
            if bar.value() != before:
                self.cursor_pos = QPointF(self.mapFromGlobal(QCursor.pos()))
                self.drop_index = self.insertion_at(self.cursor_pos)
                self.update()


class OrganizeBar(QWidget):
    """Barra flutuante: girar, excluir, desfazer e a contagem da seleção."""

    def __init__(self, screen):
        super().__init__(screen)
        self.screen = screen
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 12, 10)
        lay.setSpacing(6)
        self.label = Label("", 14, 600, wrap=False)
        lay.addWidget(self.label, 1)
        self.buttons = {}
        for key, glyph, tip in (("view", "eye", "Ver a página grande (Espaço)"),
                                ("left", "rotate_left", "Girar para a esquerda"),
                                ("right", "rotate_right", "Girar para a direita"),
                                ("delete", "trash", "Excluir páginas (Delete)"),
                                ("undo", "undo", "Desfazer (Ctrl+Z)")):
            b = QPushButton()
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(42, 42)
            b.setIconSize(QSize(23, 23))
            b.clicked.connect(lambda _c=False, k=key: screen.bar_action(k))
            self.buttons[key] = (b, glyph)
            lay.addWidget(b)

    def update_state(self, n_sel: int, total: int, can_undo: bool):
        self.label.setText("Arraste para mudar a ordem" if n_sel == 0
                           else f"{n_sel} página{'s' if n_sel != 1 else ''} selecionada{'s' if n_sel != 1 else ''}")
        enabled = {"view": total > 0, "left": n_sel > 0, "right": n_sel > 0, "delete": 0 < n_sel < total,
                   "undo": can_undo}
        for k, (b, glyph) in self.buttons.items():
            color = T.color("red" if k == "delete" else "blue") if enabled[k] else T.color("placeholder")
            b.setIcon(glyph_icon(glyph, color, 23))
            b.setEnabled(enabled[k])
            b.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 21px; }"
                            f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("shadow"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 3, -1, 0), TILE_RADIUS, TILE_RADIUS)
        p.setBrush(T.color("tile"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, -3), TILE_RADIUS, TILE_RADIUS)

    def place(self):
        w = min(600, self.screen.width() - 2 * MARGIN)
        self.setFixedSize(w, 64)
        self.move((self.screen.width() - w) // 2, self.screen.height() - 64 - 14)


class OrganizeScreen(Screen):
    large_title = False

    def __init__(self, app, item_id: str):
        super().__init__(app)
        self.item_id = item_id
        self.item = app.lib.item(item_id)
        import pdfops
        total = self.item.page_count or pdfops.page_count(self.item.path)
        self.model = PageModel(total)
        self.add_back()
        self.big_title.hide()
        self.set_title("Organizar páginas")
        self.big_title.hide()
        self.save_btn = TextButton("Salvar", bold=True)
        self.save_btn.clicked.connect(lambda _checked=False: self.save())
        self.nav.right.addWidget(self.save_btn)
        hint = Label(f"“{self.item.name}”. Arraste as páginas para mudar a ordem; perto do alto ou do pé da "
                     "janela, a lista rola sozinha. Ctrl+clique seleciona várias, Shift+clique um trecho, e arrastar "
                     "a partir de um espaço vazio desenha um retângulo de seleção. "
                     "Ctrl+roda do mouse muda o tamanho. Para ler uma página, clique na lupa que aparece sobre ela "
                     "(ou dê dois cliques, ou tecle Espaço).",
                     13, 400, "secondary")
        hint.setContentsMargins(4, 0, 4, 0)
        self.content.addWidget(hint)
        self.grid = PageGrid(self, self.item, self.model)
        self.grid.selection_changed.connect(self._sync)
        self.grid.changed.connect(self._sync)
        self.content.addWidget(self.grid)
        self.finish_content()
        self.content.setContentsMargins(MARGIN, 0, MARGIN, 100)
        self.bar = OrganizeBar(self)
        # Retângulo de seleção: começa num espaço vazio (arrastar em cima de uma página a move).
        from rubberband import RubberBand
        self._band_base: set[int] = set()
        self.band = RubberBand(self.body, self.scroll, self._band_items, self._band_select,
                               lambda add: setattr(self, "_band_base", set(self.grid.selected) if add else set()),
                               lambda w, pos: not (w is self.grid and self.grid.index_at(pos) is not None))
        for seq, fn in (("Delete", lambda: self.bar_action("delete")), ("Ctrl+A", self.select_all),
                        ("Ctrl+Z", lambda: self.bar_action("undo")), ("Ctrl+S", self.save),
                        ("Esc", self.clear_selection), ("Space", lambda: self.bar_action("view"))):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self._sync()

    def _band_items(self):
        off = self.grid.mapTo(self.body, QPoint(0, 0))
        return [(i, self.grid.cell_rect(i).translated(off.x(), off.y())) for i in range(len(self.model.entries))]

    def _band_select(self, keys: set, _additive: bool, _final: bool):
        g = self.grid
        g.selected = self._band_base | keys
        if keys:
            g.anchor = min(keys)
        g.update()
        self._sync()

    def refresh(self):
        # A grade só muda pelas ações desta tela (a biblioteca recarregar não deve apagar a edição).
        self.grid.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.bar.place()
        self.bar.raise_()

    def _sync(self):
        g = self.grid
        n = len(self.model.entries)
        g.selected = {i for i in g.selected if i < n}
        self.bar.update_state(len(g.selected), n, bool(self.model.history))
        self.save_btn.setEnabled(self.model.changed)
        self.save_btn.update()
        self.set_title(f"Organizar páginas · {n}" + (" · não salvo" if self.model.changed else ""))
        self.big_title.hide()
        self.bar.place()
        self.bar.raise_()
        self.bar.show()

    def select_all(self):
        self.grid.selected = set(range(len(self.model.entries)))
        self.grid.update()
        self._sync()

    def clear_selection(self):
        self.grid.selected.clear()
        self.grid.update()
        self._sync()

    def bar_action(self, key):
        g = self.grid
        sel = sorted(g.selected)
        if key == "view":
            if self.model.entries:
                start = g.anchor if g.anchor is not None and g.anchor in g.selected else (sel[0] if sel else 0)
                self.preview(start)
            return
        if key in ("left", "right") and sel:
            self.model.rotate(sel, -90 if key == "left" else 90)
        elif key == "delete" and sel:
            if len(sel) >= len(self.model.entries):
                self.app.toast("O PDF precisa ficar com pelo menos uma página.")
                return
            self.model.delete(sel)
            g.selected.clear()
        elif key == "undo":
            if not self.model.undo():
                return
            g.selected.clear()
        else:
            return
        g.relayout()
        self._sync()

    def preview(self, i):
        """A página grande, por cima desta tela, na ordem e com o giro ainda não salvos."""
        from page_view import PagePreviewOverlay
        from reader import ReaderScreen
        entries = list(self.model.entries)
        if not entries:
            return
        n = len(entries)

        def label(k):
            page, rot = entries[k]
            extra = (f" · era a {page}" if page != k + 1 else "") + (f" · girada {rot}°" if rot else "")
            return f"Página {k + 1} de {n}{extra}"

        def open_reader(page_index):
            self.app.push(ReaderScreen(self.app, self.item_id, start_page=page_index,
                                       title_extra=f"página {page_index + 1}"))

        ov = PagePreviewOverlay(self.app, self.item.path, [(p - 1, r) for p, r in entries], i, label,
                                on_open_reader=None if self.model.changed else open_reader)
        ov.closed.connect(lambda: self.grid.setFocus())
        self._preview = ov
        ov.open()

    def can_leave(self) -> bool:
        if not self.model.changed:
            return True
        idx = alert(self.app, "Salvar a nova ordem?", "As mudanças nas páginas ainda não foram gravadas no PDF.",
                    [("Salvar", "default"), ("Descartar", "destructive"), ("Continuar editando", "cancel")])
        if idx == 0:
            return self.save(go_back=False)
        return idx == 1

    def save(self, go_back=True) -> bool:
        if not self.model.changed:
            if go_back:
                self.app.back()
            return True
        import pdfops
        entries = list(self.model.entries)
        lib = self.app.lib
        item = lib.item(self.item_id)
        if item is None:
            self.app.show_error("O PDF foi movido ou apagado.")
            return False
        if self.app.attempt(lambda: lib.modify(item, lambda p: pdfops.arrange(p, entries)), busy="Salvando…"):
            self.model = PageModel(len(entries))
            self.grid.model = self.model
            if go_back:
                self.app.back(force=True)
            self.app.toast("Páginas reorganizadas. Use “Desfazer última alteração” se precisar.")
            return True
        return False
