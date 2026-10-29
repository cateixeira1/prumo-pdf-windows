"""
Cortar e girar páginas, e numerar páginas (janelas do leitor e da tela do PDF).

- Cortar: a página aparece inteira, com uma moldura que se arrasta pelas bordas e cantos (ou
  margens digitadas em milímetros). "Margens automáticas" encosta a moldura no conteúdo. O corte
  vira o CropBox, o recorte padrão do PDF: nada é apagado, e "Página inteira" desfaz.
- Girar: 90° para um lado ou para o outro, ou 180°.
- Numerar: posição, formato ("1", "Página 1", "Página 1 de 12", "1/12", "- 1 -"), número inicial,
  a partir de qual página e tamanho da letra. O número vira texto de verdade na página.

Vale para esta página, todas, pares, ímpares ou um trecho (ex.: 3-10). Tudo pode ser desfeito
com "Desfazer última alteração".
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

import pdfops
from ios_kit import Label, PrimaryButton, SheetOverlay, TileCard, sheet_header
from ios_theme import T, font

MM = 72 / 25.4
HANDLE = 9


def _small_button(text, cb):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(font(13, 600))
    b.setStyleSheet(f"QPushButton {{ background: {T.hex('search')}; border: none; border-radius: 8px; "
                    f"padding: 6px 12px; color: {T.color('blue').name()}; }}"
                    f"QPushButton:disabled {{ color: {T.hex('placeholder')}; }}")
    b.clicked.connect(lambda _c=False: cb())
    return b


def render_full_page(path, index: int, width_px: int) -> QImage | None:
    """A página inteira (MediaBox), sem o corte atual, com o giro que ela já tem."""
    import core
    import pypdfium2 as pdfium
    from pathlib import Path

    data = Path(path).read_bytes()
    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(data)
        try:
            page = pdf[index]
            try:
                page.set_cropbox(*page.get_mediabox())
                w = page.get_width() or 1
                pil = page.render(scale=max(0.05, width_px / w), rev_byteorder=True).to_pil().convert("RGB")
            finally:
                page.close()
        finally:
            pdf.close()
    return QImage(pil.tobytes(), pil.width, pil.height, pil.width * 3, QImage.Format_RGB888).copy()


def rotate_margins(m, delta: int):
    """Margens (esquerda, alto, direita, baixo) depois de girar a página `delta` graus (horário)."""
    l, t, r, b = m
    d = delta % 360
    if d == 90:
        return (b, l, t, r)
    if d == 180:
        return (r, b, l, t)
    if d == 270:
        return (t, r, b, l)
    return m


def content_margins(img: QImage, pts_w: float, pad: float = 8.0):
    """Margens (em pontos) até onde há conteúdo (não branco) na imagem da página."""
    from PIL import Image

    rgb = img.convertToFormat(QImage.Format_RGB888)
    w, h = rgb.width(), rgb.height()
    pil = Image.frombuffer("RGB", (w, h), bytes(rgb.constBits()), "raw", "RGB", rgb.bytesPerLine(), 1)
    gray = pil.convert("L").point(lambda v: 255 if v < 225 else 0)
    box = gray.getbbox()
    if not box:
        return None
    s = pts_w / w
    x0, y0, x1, y1 = box
    return (max(0.0, x0 * s - pad), max(0.0, y0 * s - pad), max(0.0, (w - x1) * s - pad), max(0.0, (h - y1) * s - pad))


class CropPreview(QWidget):
    """A página inteira com a moldura do corte (arraste as bordas, os cantos ou o meio)."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.img: QImage | None = None
        self.size_pt = (595.0, 842.0)        # página como aparece (depois do giro pendente)
        self.margins = (0.0, 0.0, 0.0, 0.0)  # esquerda, alto, direita, baixo (pontos)
        self._drag = None
        self.setMinimumSize(300, 380)
        self.setMouseTracking(True)

    def set_page(self, img: QImage | None, size_pt):
        self.img, self.size_pt = img, size_pt
        self.update()

    def set_margins(self, m):
        self.margins = tuple(float(v) for v in m)
        self.update()

    def _page_rect(self) -> QRectF:
        w, h = self.size_pt
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        s = min(area.width() / w, area.height() / h)
        return QRectF(area.center().x() - w * s / 2, area.center().y() - h * s / 2, w * s, h * s)

    def _scale(self) -> float:
        return self._page_rect().width() / max(1.0, self.size_pt[0])

    def frame(self) -> QRectF:
        r, s = self._page_rect(), self._scale()
        l, t, ri, b = self.margins
        return QRectF(r.left() + l * s, r.top() + t * s, r.width() - (l + ri) * s, r.height() - (t + b) * s)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._page_rect()
        p.fillRect(r, QColor("white"))
        if self.img is not None and not self.img.isNull():
            p.drawImage(r, self.img)
        f = self.frame()
        dim = QColor(0, 0, 0, 120)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), f.top() - r.top()), dim)
        p.fillRect(QRectF(r.left(), f.bottom(), r.width(), r.bottom() - f.bottom()), dim)
        p.fillRect(QRectF(r.left(), f.top(), f.left() - r.left(), f.height()), dim)
        p.fillRect(QRectF(f.right(), f.top(), r.right() - f.right(), f.height()), dim)
        p.setPen(QPen(T.color("blue"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(f)
        p.setBrush(QColor("white"))
        for pt in self._handles(f).values():
            p.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))

    @staticmethod
    def _handles(f: QRectF) -> dict[str, QPointF]:
        cx, cy = f.center().x(), f.center().y()
        return {"tl": f.topLeft(), "t": QPointF(cx, f.top()), "tr": f.topRight(), "r": QPointF(f.right(), cy),
                "br": f.bottomRight(), "b": QPointF(cx, f.bottom()), "bl": f.bottomLeft(), "l": QPointF(f.left(), cy)}

    def _hit(self, pos: QPointF):
        f = self.frame()
        for key, pt in self._handles(f).items():
            if abs(pos.x() - pt.x()) <= HANDLE and abs(pos.y() - pt.y()) <= HANDLE:
                return key
        edges = {"l": abs(pos.x() - f.left()), "r": abs(pos.x() - f.right()),
                 "t": abs(pos.y() - f.top()), "b": abs(pos.y() - f.bottom())}
        inside_v = f.top() - HANDLE <= pos.y() <= f.bottom() + HANDLE
        inside_h = f.left() - HANDLE <= pos.x() <= f.right() + HANDLE
        for key in ("l", "r"):
            if edges[key] <= HANDLE / 1.5 and inside_v:
                return key
        for key in ("t", "b"):
            if edges[key] <= HANDLE / 1.5 and inside_h:
                return key
        return "move" if f.contains(pos) else None

    def mousePressEvent(self, e):
        key = self._hit(e.position())
        if key:
            self._drag = (key, e.position(), self.margins)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            key = self._hit(e.position())
            cursors = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                       "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                       "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "move": Qt.SizeAllCursor}
            self.setCursor(cursors.get(key, Qt.ArrowCursor))
            return
        key, start, (l, t, r, b) = self._drag
        s = self._scale()
        dx, dy = (e.position().x() - start.x()) / s, (e.position().y() - start.y()) / s
        w, h = self.size_pt
        minw = 36.0
        if key == "move":
            dx = max(-l, min(r, dx))
            dy = max(-t, min(b, dy))
            l, r, t, b = l + dx, r - dx, t + dy, b - dy
        else:
            if "l" in key:
                l = max(0.0, min(w - r - minw, l + dx))
            if "r" in key:
                r = max(0.0, min(w - l - minw, r - dx))
            if "t" in key:
                t = max(0.0, min(h - b - minw, t + dy))
            if "b" in key:
                b = max(0.0, min(h - t - minw, b - dy))
        self.margins = (l, t, r, b)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):
        self._drag = None


def _scope_row(total: int, current: int):
    """Caixa "Aplicar a" (esta página, todas, ímpares, pares, escolher) e o campo de páginas."""
    combo = QComboBox()
    combo.addItem(f"Só esta página ({current})", "this")
    combo.addItem("Todas as páginas", "all")
    combo.addItem("Páginas ímpares (1, 3, 5…)", "odd")
    combo.addItem("Páginas pares (2, 4, 6…)", "even")
    combo.addItem("Escolher páginas…", "custom")
    field = QLineEdit()
    field.setPlaceholderText(f"Ex.: 1, 3-5, 10-fim (de 1 a {total})")
    field.hide()
    combo.currentIndexChanged.connect(lambda _i: field.setVisible(combo.currentData() == "custom"))
    return combo, field


def _scope_pages(combo, field, total: int, current: int) -> list[int]:
    kind = combo.currentData()
    if kind == "this":
        return [current]
    if kind == "all":
        return list(range(1, total + 1))
    if kind == "odd":
        return list(range(1, total + 1, 2))
    if kind == "even":
        return list(range(2, total + 1, 2))
    return pdfops.parse_page_selection(field.text(), total)


def crop_dialog(app, item, start_page: int = 0) -> bool:
    """Cortar margens e girar páginas. Devolve True se o PDF mudou."""
    if item is None:
        return False
    if item.meta.locked:
        app.toast("Este PDF tem senha. Para cortar ou girar, crie antes uma cópia sem senha.")
        return False
    try:
        boxes = pdfops.page_boxes(item.path)
    except Exception as exc:  # noqa: BLE001
        app.show_error(str(exc))
        return False
    total = len(boxes)
    if not total:
        return False
    st = {"page": max(0, min(total - 1, start_page)), "rot": 0, "touched": False}
    b0 = boxes[st["page"]]
    st["margins"] = pdfops.box_to_margins(b0["media"], b0["rotate"], b0["crop"])

    ov = SheetOverlay(app, 760, max_height=900)
    sheet_header(ov, "Cortar e girar páginas")
    body = QHBoxLayout()
    body.setContentsMargins(16, 4, 16, 16)
    body.setSpacing(14)
    left = QVBoxLayout()
    preview = CropPreview()
    left.addWidget(preview, 1)
    nav = QHBoxLayout()
    page_label = Label("", 13, 600, wrap=False)
    prev_b = _small_button("‹ Anterior", lambda: go(-1))
    next_b = _small_button("Próxima ›", lambda: go(1))
    nav.addWidget(prev_b)
    nav.addStretch(1)
    nav.addWidget(page_label)
    nav.addStretch(1)
    nav.addWidget(next_b)
    left.addLayout(nav)
    body.addLayout(left, 3)

    right = QVBoxLayout()
    right.setSpacing(10)
    card = TileCard()
    card.lay.addWidget(Label("Margens (mm)", 14, 600))
    card.lay.addWidget(Label("Arraste a moldura azul na página ou digite as margens.", 12, 400, "secondary"))
    grid = QGridLayout()
    spins = {}
    for k, (key, label) in enumerate((("l", "Esquerda"), ("t", "Alto"), ("r", "Direita"), ("b", "Baixo"))):
        sp = QDoubleSpinBox()
        sp.setRange(0, 500)
        sp.setDecimals(1)
        sp.setSingleStep(1)
        sp.setSuffix(" mm")
        grid.addWidget(Label(label, 13, 500), k // 2 * 2, k % 2)
        grid.addWidget(sp, k // 2 * 2 + 1, k % 2)
        spins[key] = sp
    card.lay.addLayout(grid)
    row = QHBoxLayout()
    row.addWidget(_small_button("Margens automáticas", lambda: auto()))
    row.addWidget(_small_button("Página inteira", lambda: set_margins((0, 0, 0, 0), True)))
    card.lay.addLayout(row)
    right.addWidget(card)

    card2 = TileCard()
    card2.lay.addWidget(Label("Girar", 14, 600))
    row2 = QHBoxLayout()
    row2.addWidget(_small_button("↺ 90°", lambda: rotate(-90)))
    row2.addWidget(_small_button("↻ 90°", lambda: rotate(90)))
    row2.addWidget(_small_button("180°", lambda: rotate(180)))
    card2.lay.addLayout(row2)
    rot_label = Label("", 12, 500, "secondary")
    card2.lay.addWidget(rot_label)
    right.addWidget(card2)

    card3 = TileCard()
    card3.lay.addWidget(Label("Aplicar a", 14, 600))
    combo, field = _scope_row(total, st["page"] + 1)
    card3.lay.addWidget(combo)
    card3.lay.addWidget(field)
    err = Label("", 12, 500, "red")
    card3.lay.addWidget(err)
    right.addWidget(card3)
    btn = PrimaryButton("Aplicar", "indigo")
    right.addWidget(btn)
    right.addWidget(Label("O corte não apaga nada do PDF: “Página inteira” mostra tudo de novo. "
                          "Também dá para usar “Desfazer última alteração”.", 12, 400, "secondary"))
    right.addStretch(1)
    body.addLayout(right, 2)
    ov.lay.addLayout(body)

    syncing = {"on": False}

    def page_size():
        b = boxes[st["page"]]
        x0, y0, x1, y1 = b["media"]
        w, h = x1 - x0, y1 - y0
        if (b["rotate"] + st["rot"]) % 180:
            w, h = h, w
        return (w, h)

    def show():
        page = st["page"]
        page_label.setText(f"Página {page + 1} de {total}")
        prev_b.setEnabled(page > 0)
        next_b.setEnabled(page < total - 1)
        combo.setItemText(0, f"Só esta página ({page + 1})")
        img = None
        try:
            img = render_full_page(item.path, page, 700)
        except Exception:  # noqa: BLE001
            img = None
        if img is not None and st["rot"] % 360:
            img = img.transformed(QTransform().rotate(st["rot"]))
        st["img"] = img
        preview.set_page(img, page_size())
        rot_label.setText(f"Giro a aplicar: {st['rot'] % 360}°" if st["rot"] % 360 else "Sem giro a aplicar.")
        set_margins(st["margins"], False)

    def set_margins(m, touched):
        w, h = page_size()
        l, t, r, b = (max(0.0, float(v)) for v in m)
        l = min(l, w - 36)
        r = min(r, max(0.0, w - 36 - l))
        t = min(t, h - 36)
        b = min(b, max(0.0, h - 36 - t))
        st["margins"] = (l, t, r, b)
        if touched:
            st["touched"] = True
        preview.set_margins(st["margins"])
        syncing["on"] = True
        for key, v in zip("ltrb", st["margins"]):
            spins[key].setValue(round(v / MM, 1))
        syncing["on"] = False

    def from_spins(_v=None):
        if syncing["on"]:
            return
        set_margins(tuple(spins[k].value() * MM for k in "ltrb"), True)

    def from_preview():
        st["margins"] = preview.margins
        st["touched"] = True
        syncing["on"] = True
        for key, v in zip("ltrb", st["margins"]):
            spins[key].setValue(round(v / MM, 1))
        syncing["on"] = False

    def go(d):
        st["page"] = max(0, min(total - 1, st["page"] + d))
        show()

    def rotate(delta):
        st["margins"] = rotate_margins(st["margins"], delta)
        st["rot"] = (st["rot"] + delta) % 360
        show()

    def auto():
        img = st.get("img")
        if img is None:
            return
        m = content_margins(img, page_size()[0])
        if m is None:
            app.toast("A página parece estar em branco.")
            return
        set_margins(m, True)

    for sp in spins.values():
        sp.valueChanged.connect(from_spins)
    preview.changed.connect(from_preview)
    btn.clicked.connect(lambda: ov.done(True))
    show()
    if not ov.run():
        return False
    try:
        pages = _scope_pages(combo, field, total, st["page"] + 1)
    except ValueError as exc:
        app.show_error(str(exc))
        return False
    margins = st["margins"] if st["touched"] else None
    rot = st["rot"] % 360
    if margins is None and not rot:
        app.toast("Nada mudou: arraste a moldura, digite as margens ou gire a página.")
        return False
    res = {}
    if app.attempt(lambda: res.setdefault("n", app.lib.modify(
            item, lambda p: pdfops.crop_and_rotate(p, pages, margins, rot), keep_review=True)), busy="Salvando…"):
        n = res.get("n") or len(pages)
        what = " e ".join(x for x in ("cortada" + ("s" if n != 1 else "") if margins is not None else "",
                                      "girada" + ("s" if n != 1 else "") if rot else "") if x)
        app.toast(f"{n} página{'s' if n != 1 else ''} {what}. Use “Desfazer última alteração” se precisar.")
        return True
    return False


class _NumberPreview(QWidget):
    """Página de exemplo com o número no lugar escolhido."""

    def __init__(self):
        super().__init__()
        self.text, self.position, self.size_pt, self.margin_pt = "1", "bottom_center", 10.0, 28.0
        self.setFixedSize(170, 230)

    def set_options(self, text, position, size_pt, margin_pt):
        self.text, self.position, self.size_pt, self.margin_pt = text, position, size_pt, margin_pt
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(10, 6, 150, 212)
        s = r.width() / 595.0
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.setBrush(QColor("white"))
        p.drawRect(r)
        p.setPen(QPen(QColor(200, 200, 205), 3))
        for k in range(9):
            y = r.top() + 40 + k * 16
            p.drawLine(QPointF(r.left() + 22, y), QPointF(r.right() - 22 - (30 if k % 3 == 2 else 0), y))
        f = font(max(6.0, self.size_pt * s * 1.25), 600)
        p.setFont(f)
        p.setPen(QColor(30, 30, 30))
        vert, horiz = self.position.split("_")
        m = self.margin_pt * s
        box_h = 14
        y = r.bottom() - m - box_h + 4 if vert == "bottom" else r.top() + m - 4
        align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[horiz]
        p.drawText(QRectF(r.left() + m, y, r.width() - 2 * m, box_h), align | Qt.AlignVCenter, self.text)


def number_dialog(app, item) -> bool:
    """Numerar as páginas. Devolve True se o PDF mudou."""
    if item is None:
        return False
    if item.meta.locked:
        app.toast("Este PDF tem senha. Para numerar, crie antes uma cópia sem senha.")
        return False
    total = item.page_count or pdfops.page_count(item.path)
    ov = SheetOverlay(app, 560)
    sheet_header(ov, "Numerar páginas")
    wrap = QHBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(14)
    card = TileCard()
    card.lay.setSpacing(6)
    pos = QComboBox()
    for key, label in pdfops.NUMBER_POSITIONS.items():
        pos.addItem(label, key)
    fmt = QComboBox()
    for key, (label, _t) in pdfops.NUMBER_FORMATS.items():
        fmt.addItem(label, key)
    start = QSpinBox()
    start.setRange(0, 99999)
    start.setValue(1)
    first = QSpinBox()
    first.setRange(1, max(1, total))
    first.setValue(1)
    size = QSpinBox()
    size.setRange(6, 28)
    size.setValue(10)
    size.setSuffix(" pt")
    margin = QSpinBox()
    margin.setRange(3, 60)
    margin.setValue(10)
    margin.setSuffix(" mm")
    for label, w in (("Posição", pos), ("Formato", fmt), ("Primeiro número", start),
                     ("Começar a numerar na página", first), ("Tamanho da letra", size), ("Distância da borda", margin)):
        card.lay.addWidget(Label(label, 13, 600))
        card.lay.addWidget(w)
    info = Label("", 12, 500, "teal")
    card.lay.addWidget(info)
    col = QVBoxLayout()
    col.addWidget(card)
    btn = PrimaryButton("Numerar", "indigo")
    col.addWidget(btn)
    col.addWidget(Label("O número fica gravado como texto na página. Para tirar, use “Desfazer última alteração”.",
                        12, 400, "secondary"))
    wrap.addLayout(col, 1)
    side = QVBoxLayout()
    side.addWidget(Label("Prévia", 12, 600, "secondary"))
    preview = _NumberPreview()
    side.addWidget(preview)
    side.addStretch(1)
    wrap.addLayout(side)
    ov.lay.addLayout(wrap)

    def update(_v=None):
        n_first = first.value()
        last = start.value() + (total - n_first)
        sample = pdfops.number_text(fmt.currentData(), start.value(), last)
        preview.set_options(sample, pos.currentData(), size.value(), margin.value() * MM)
        count = total - n_first + 1
        info.setText(f"{count} página{'s' if count != 1 else ''}: de “{sample}” até "
                     f"“{pdfops.number_text(fmt.currentData(), last, last)}”.")

    for w in (pos, fmt):
        w.currentIndexChanged.connect(update)
    for w in (start, first, size, margin):
        w.valueChanged.connect(update)
    btn.clicked.connect(lambda: ov.done(True))
    update()
    if not ov.run():
        return False
    opts = dict(fmt=fmt.currentData(), position=pos.currentData(), start=start.value(), first_page=first.value(),
                size=float(size.value()), margin=margin.value() * MM)
    res = {}
    if app.attempt(lambda: res.setdefault("n", app.lib.modify(item, lambda p: pdfops.number_pages(p, **opts),
                                                              keep_review=True)), busy="Numerando…"):
        n = res.get("n") or 0
        app.toast(f"{n} página{'s' if n != 1 else ''} numerada{'s' if n != 1 else ''}. "
                  "Use “Desfazer última alteração” se precisar.")
        return True
    return False
