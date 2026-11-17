"""
Tela "Preencher formulário".

- Campos do PDF (AcroForm): aparecem em azul-claro sobre a página e se preenchem ali mesmo (texto, caixa de
  marcar, opção, lista suspensa, lista).
- PDF sem campos: a ferramenta "Texto" põe uma caixa de texto onde se clicar; ✓, ✗ e ● põem marcas.
  As caixas se arrastam com o mouse; dois cliques editam; Delete apaga.
- A barra de formatação segue a do Got It!: Fonte, tamanho, negrito e cor, com separadores. Vale para a
  caixa escolhida e para as próximas.
- "Salvar" grava no próprio PDF (com "Desfazer última alteração" na tela do PDF). "Finalizar" cria uma
  cópia achatada ("Nome - preenchido"), em que nada mais muda.

O motor (ler, gravar, achatar) fica em forms.py; aqui só a interface.
"""

from __future__ import annotations

import copy
import json

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen, QShortcut,
                           QTextBlockFormat, QTextCursor)
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QSizePolicy, QWidget)

import forms
import i18n
from i18n import raw, tr, trf
from ios_kit import (CircleButton, EmptyState, Label, Screen, TextButton, alert, menu_action, styled_menu)
from ios_theme import MARGIN, T, connect_alive, font, paint_glyph
from reader import GAP, MAX_W, PageCache

FIELD_BG = QColor(214, 228, 255, 215)
FIELD_BORDER = QColor(80, 125, 230, 150)
SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36]
FONT_LABELS = {"helvetica": "Helvetica", "times": "Times", "courier": "Courier"}
COLOR_LABELS = {"black": "Preto", "blue": "Azul", "red": "Vermelho", "green": "Verde"}
TOOLS = [  # chave, desenho, dica
    ("select", "pointer", "Selecionar e mover (Esc)"),
    ("text", "textbox", "Texto: clique na página para escrever"),
    ("check", "checkmark", "Marcar com ✓"),
    ("cross", "x", "Marcar com ✗"),
    ("dot", "dot", "Marcar com ●"),
]

def qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*rgb)


def ui_font(key: str, bold: bool, px: float) -> QFont:
    f = QFont(forms.FONTS.get(key, forms.FONTS["helvetica"])[2])
    f.setPixelSize(max(1, round(px)))
    f.setBold(bold)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def mark_path(kind: str, rect: QRectF) -> QPainterPath:
    """A mesma marca que forms._mark_ops grava no PDF, para a tela."""
    s = rect.width()
    def pt(px, py):
        return QPointF(rect.x() + px * s, rect.y() + (1 - py) * s)
    path = QPainterPath()
    if kind == "check":
        path.moveTo(pt(0.15, 0.52))
        path.lineTo(pt(0.40, 0.22))
        path.lineTo(pt(0.86, 0.82))
    elif kind == "cross":
        path.moveTo(pt(0.2, 0.2))
        path.lineTo(pt(0.8, 0.8))
        path.moveTo(pt(0.2, 0.8))
        path.lineTo(pt(0.8, 0.2))
    else:
        path.addEllipse(QPointF(rect.center()), s * 0.28, s * 0.28)
    return path


# --- Barra de formatação (no formato da do Got It!) ----------------------------------

class _BarButton(QAbstractButton):
    """Botão de ícone da barra, como os da barra de formatação do Got It!."""

    def __init__(self, glyph: str, tip: str, text: str = "", checkable=False, menu=False):
        super().__init__()
        self.glyph, self.label = glyph, text
        self.menu_cb = menu
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFixedHeight(36)
        self._resize()
        connect_alive(T.changed, self, lambda o, *_: o.update())

    def set_label(self, text: str):
        self.label = text
        self._resize()
        self.update()

    def _resize(self):
        w = 36
        if self.label:
            from PySide6.QtGui import QFontMetrics
            text = tr(self.label) + (" ▾" if self.menu_cb else "")
            w = QFontMetrics(font(14, 500)).horizontalAdvance(text) + (40 if self.glyph else 22)
        self.setFixedWidth(w)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.color("blue").red(), T.color("blue").green(), T.color("blue").blue(), 40))
            p.drawRoundedRect(r, 9, 9)
        elif self.underMouse() and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("tile_hover"))
            p.drawRoundedRect(r, 9, 9)
        color = T.color("blue") if self.isChecked() else (T.color("text") if self.isEnabled() else T.color("placeholder"))
        x = 8.0
        if self.glyph:
            paint_glyph(p, QRectF(x, 8, 20, 20), self.glyph, color, 1.9)
            x += 24
        if self.label:
            p.setPen(color)
            p.setFont(font(14, 500))
            i18n.draw_raw(p, QRectF(x, 0, self.width() - x - 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                          tr(self.label) + " ▾" if self.menu_cb else tr(self.label))


class _Separator(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(13, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(T.color("thumb_border"), 1))
        p.drawLine(6, 0, 6, 22)


class FormatBar(QFrame):
    """Ferramentas (selecionar, texto, ✓, ✗, ●) e formatação (fonte, tamanho, negrito, cor)."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.setObjectName("formBar")
        self.setFixedHeight(48)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(4)
        self.tools = {}
        for key, glyph, tip in TOOLS:
            b = _BarButton(glyph, tip, checkable=True)
            b.clicked.connect(lambda _c=False, k=key: screen.set_tool(k))
            self.tools[key] = b
            lay.addWidget(b)
        lay.addWidget(_Separator())
        self.font_btn = _BarButton("", "Fonte", "Fonte", menu=True)
        self.font_btn.clicked.connect(self._font_menu)
        self.size_btn = _BarButton("textsize", "Tamanho da letra", trf("{} pt", 12), menu=True)
        self.size_btn.clicked.connect(self._size_menu)
        lay.addWidget(self.font_btn)
        lay.addWidget(self.size_btn)
        lay.addWidget(_Separator())
        self.bold_btn = _BarButton("bold", "Negrito (Ctrl+B)", checkable=True)
        self.bold_btn.clicked.connect(lambda _c=False: screen.set_style(bold=self.bold_btn.isChecked()))
        lay.addWidget(self.bold_btn)
        self.color_btn = _ColorButton()
        self.color_btn.clicked.connect(self._color_menu)
        lay.addWidget(self.color_btn)
        lay.addWidget(_Separator())
        self.delete_btn = _BarButton("trash", "Apagar a caixa escolhida (Delete)")
        self.delete_btn.clicked.connect(screen.delete_selected)
        lay.addWidget(self.delete_btn)
        lay.addStretch(1)
        self._apply_style()
        connect_alive(T.changed, self, lambda o, *_: o._apply_style())

    def _apply_style(self):
        self.setStyleSheet(f"#formBar {{ background: {T.hex('panel')}; border: none; "
                           f"border-bottom: 1px solid rgba(0,0,0,30); }}")

    def sync(self, tool: str, style: dict, has_box: bool):
        for k, b in self.tools.items():
            b.setChecked(k == tool)
        self.font_btn.set_label(FONT_LABELS[style["font"]])
        self.size_btn.set_label(trf("{} pt", i18n.fmt_number(style["size"], 0 if style["size"] == int(style["size"]) else 1)))
        self.bold_btn.setChecked(style["bold"])
        self.color_btn.set_color(style["color"])
        self.delete_btn.setEnabled(has_box)

    def _popup(self, button, fill):
        m = styled_menu(self)
        fill(m)
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _font_menu(self):
        cur = self.screen.style["font"]
        def fill(m):
            for key, label in FONT_LABELS.items():
                act = menu_action(m, label, None, lambda k=key: self.screen.set_style(font=k), checked=(key == cur))
                act.setFont(ui_font(key, False, 15))
        self._popup(self.font_btn, fill)

    def _size_menu(self):
        cur = self.screen.style["size"]
        def fill(m):
            for s in SIZES:
                menu_action(m, trf("{} pt", s), None, lambda s=s: self.screen.set_style(size=float(s)), checked=(s == cur))
        self._popup(self.size_btn, fill)

    def _color_menu(self):
        cur = self.screen.style["color"]
        def fill(m):
            for key, label in COLOR_LABELS.items():
                act = menu_action(m, label, None, lambda k=key: self.screen.set_style(color=k), checked=(key == cur))
                if key != cur:
                    from ios_theme import glyph_icon
                    act.setIcon(glyph_icon("dot", qcolor(forms.COLORS[key]), 18))
        self._popup(self.color_btn, fill)


class _ColorButton(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.key = "black"
        self.setFixedSize(36, 36)
        self.setToolTip(tr("Cor do texto"))
        self.setAccessibleName(tr("Cor do texto"))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def set_color(self, key):
        self.key = key
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("tile_hover"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        p.setPen(QPen(QColor(0, 0, 0, 50), 1))
        p.setBrush(qcolor(forms.COLORS[self.key]))
        p.drawEllipse(QRectF(9, 9, 18, 18))


# --- Campos (AcroForm) ---------------------------------------------------------------

class _Toggle(QAbstractButton):
    """Caixa de marcar ou botão de opção do PDF."""

    def __init__(self, view, f: forms.Field, w: forms.Widget):
        super().__init__(view)
        self.view, self.field, self.wid = view, f, w
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(raw(f.tooltip or f.name))
        self.setAccessibleName(raw(f.tooltip or f.name))
        self.clicked.connect(self._click)

    def on(self) -> bool:
        v = self.view.screen.values.get(self.field.name)
        if self.field.kind == "check":
            return bool(v)
        return bool(v) and v == self.wid.on_state

    def _click(self):
        if self.field.readonly:
            return
        name = self.field.name
        if self.field.kind == "check":
            self.view.screen.set_value(name, not self.on())
        else:
            self.view.screen.set_value(name, "" if self.on() else (self.wid.on_state or ""))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(FIELD_BORDER, 1))
        p.setBrush(FIELD_BG)
        if self.field.kind == "radio":
            p.drawEllipse(r)
        else:
            p.drawRect(r)
        if self.on():
            s = min(r.width(), r.height())
            sq = QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)
            if self.field.kind == "radio":
                p.setPen(Qt.NoPen)
                p.setBrush(qcolor(self.field.color))
                p.drawPath(mark_path("dot", sq))
            else:
                p.setPen(QPen(qcolor(self.field.color), max(1.2, s * 0.12), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPath(mark_path("check", sq))


_FIELD_CSS = ("background: rgba(214,228,255,215); border: 1px solid rgba(80,125,230,150); border-radius: 0px; "
              "padding: 0px 1px; color: {color}; selection-background-color: rgba(41,120,245,110);")


class _LineField(QLineEdit):
    def __init__(self, view, f: forms.Field, w: forms.Widget):
        super().__init__(view)
        self.view, self.field, self.wid = view, f, w
        self.setFrame(False)
        self.setToolTip(raw(f.tooltip or f.name))
        self.setReadOnly(f.readonly)
        if f.maxlen:
            self.setMaxLength(f.maxlen)
        if f.password:
            self.setEchoMode(QLineEdit.Password)
        self.setAlignment({1: Qt.AlignHCenter, 2: Qt.AlignRight}.get(f.align, Qt.AlignLeft) | Qt.AlignVCenter)
        self.setStyleSheet(_FIELD_CSS.format(color=qcolor(f.color).name()))
        self.textEdited.connect(self._edited)
        self.editingFinished.connect(lambda: view.screen.commit())

    def _edited(self, text):
        clean = self.view.screen.filter_text(text)
        if clean != text:
            pos = self.cursorPosition()
            self.setText(clean)
            self.setCursorPosition(min(pos, len(clean)))
        self.view.screen.set_value(self.field.name, clean, commit=False, source=self)
        self.fit()

    def show_value(self, v):
        if self.text() != str(v or ""):
            self.setText(str(v or ""))
        self.fit()

    def fit(self):
        s = self.view.scale(self.wid.page)
        x0, y0, x1, y1 = self.view.field_rect(self.wid)
        size = forms._auto_size(self.field, self.text(), x1 - x0, y1 - y0)
        self.setFont(ui_font(self.field.font, self.field.bold, size * s))


class _TextField(QPlainTextEdit):
    def __init__(self, view, f: forms.Field, w: forms.Widget):
        super().__init__(view)
        self.view, self.field, self.wid = view, f, w
        self.setFrameShape(QFrame.NoFrame)
        self.setToolTip(raw(f.tooltip or f.name))
        self.setReadOnly(f.readonly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(1)
        self.setStyleSheet("QPlainTextEdit { " + _FIELD_CSS.format(color=qcolor(f.color).name()) + " }")
        self.textChanged.connect(self._changed)
        self._setting = False

    def _changed(self):
        if self._setting:
            return
        text = self.toPlainText()
        clean = self.view.screen.filter_text(text)
        if clean != text:
            self._setting = True
            cur = self.textCursor().position()
            self.setPlainText(clean)
            c = self.textCursor()
            c.setPosition(min(cur, len(clean)))
            self.setTextCursor(c)
            self._setting = False
        self.view.screen.set_value(self.field.name, clean, commit=False, source=self)
        self.fit()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.view.screen.commit()

    def show_value(self, v):
        if self.toPlainText() != str(v or ""):
            self._setting = True
            self.setPlainText(str(v or ""))
            self._setting = False
        self.fit()

    def fit(self):
        s = self.view.scale(self.wid.page)
        x0, y0, x1, y1 = self.view.field_rect(self.wid)
        size = forms._auto_size(self.field, self.toPlainText(), x1 - x0, y1 - y0)
        self.setFont(ui_font(self.field.font, self.field.bold, size * s))


class _ComboField(QComboBox):
    def __init__(self, view, f: forms.Field, w: forms.Widget):
        super().__init__(view)
        self.view, self.field, self.wid = view, f, w
        self.setToolTip(raw(f.tooltip or f.name))
        self.setEditable(f.editable)
        self.setEnabled(not f.readonly)
        self.addItem("", "")
        for exp, disp in f.options:
            self.addItem(raw(disp), exp)
        self.setStyleSheet("QComboBox { " + _FIELD_CSS.format(color=qcolor(f.color).name()) + " }")
        self.activated.connect(self._picked)
        if f.editable:
            self.lineEdit().editingFinished.connect(self._typed)
        self._setting = False

    def _picked(self, i):
        if not self._setting:
            self.view.screen.set_value(self.field.name, self.itemData(i) or "")

    def _typed(self):
        text = self.view.screen.filter_text(self.currentText())
        exp = next((e for e, d in self.field.options if d == text), text)
        self.view.screen.set_value(self.field.name, exp)

    def show_value(self, v):
        self._setting = True
        i = self.findData(v or "")
        if i >= 0:
            self.setCurrentIndex(i)
        elif self.field.editable:
            self.setEditText(str(v or ""))
        self._setting = False
        s = self.view.scale(self.wid.page)
        self.setFont(ui_font(self.field.font, self.field.bold, (self.field.size or 10) * s))

    def fit(self):
        self.show_value(self.view.screen.values.get(self.field.name))


class _ListField(QListWidget):
    def __init__(self, view, f: forms.Field, w: forms.Widget):
        super().__init__(view)
        self.view, self.field, self.wid = view, f, w
        self.setToolTip(raw(f.tooltip or f.name))
        self.setEnabled(not f.readonly)
        self.setFrameShape(QFrame.NoFrame)
        for exp, disp in f.options:
            it = QListWidgetItem(raw(disp))
            it.setData(Qt.UserRole, exp)
            self.addItem(it)
        self.setStyleSheet("QListWidget { " + _FIELD_CSS.format(color=qcolor(f.color).name()) + " }")
        self.itemClicked.connect(self._picked)
        self._setting = False

    def _picked(self, it):
        if self._setting:
            return
        exp = it.data(Qt.UserRole)
        cur = self.view.screen.values.get(self.field.name)
        self.view.screen.set_value(self.field.name, "" if cur == exp else exp)

    def show_value(self, v):
        self._setting = True
        self.clearSelection()
        for k in range(self.count()):
            if self.item(k).data(Qt.UserRole) == v:
                self.item(k).setSelected(True)
        self._setting = False
        s = self.view.scale(self.wid.page)
        self.setFont(ui_font(self.field.font, self.field.bold, (self.field.size or 10) * s))

    def fit(self):
        self.show_value(self.view.screen.values.get(self.field.name))


FIELD_CLASSES = {"check": _Toggle, "radio": _Toggle, "combo": _ComboField, "list": _ListField}


# --- Caixa de texto livre em edição ----------------------------------------------------

class BoxEditor(QPlainTextEdit):
    """Edita uma caixa de texto livre no lugar. Cada linha como foi digitada (sem quebra automática)."""

    def __init__(self, view, box: forms.Box):
        super().__init__(view)
        self.view, self.box = view, box
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setPlainText(box.text)
        self.textChanged.connect(self._changed)
        self._setting = False
        self.restyle()
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        self.setTextCursor(c)

    def restyle(self):
        s = self.view.scale(self.box.page)
        f = ui_font(self.box.font, self.box.bold, self.box.size * s)
        self.setFont(f)
        self.setStyleSheet("QPlainTextEdit { background: transparent; border: none; padding: 0px; "
                           f"color: {qcolor(forms.COLORS[self.box.color]).name()}; "
                           "selection-background-color: rgba(41,120,245,110); }")
        fmt = QTextBlockFormat()
        fmt.setLineHeight(self.box.size * forms.LINE * s, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        c = QTextCursor(self.document())
        c.select(QTextCursor.Document)
        self._setting = True
        c.mergeBlockFormat(fmt)
        self._setting = False
        self.place()

    def place(self):
        b = self.box
        s = self.view.scale(b.page)
        r = self.view.box_rect(b)
        fm = QFontMetricsF(self.font())
        baseline = r.y() + (forms.BOX_PAD + b.size * forms.ASCENT) * s
        lh = b.size * forms.LINE * s
        # com altura fixa de linha, o Qt põe a base da letra em (altura da linha - descida)
        top = baseline - (lh - fm.descent())
        self.setGeometry(int(r.x() + forms.BOX_PAD * s), int(top), int(r.width() + 40 * s + 20),
                         int(r.height() + lh * 2))

    def _changed(self):
        if self._setting:
            return
        text = self.toPlainText()
        clean = self.view.screen.filter_text(text)
        if clean != text:
            self._setting = True
            cur = self.textCursor().position()
            self.setPlainText(clean)
            c = self.textCursor()
            c.setPosition(min(cur, len(clean)))
            self.setTextCursor(c)
            self._setting = False
            self.restyle()
        self.box.text = clean
        self.view.update()
        self.place()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.view.finish_edit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.view.finish_edit()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        QTimer.singleShot(0, lambda: self.view.finish_edit(self) if self.view.editor is self else None)


# --- Páginas --------------------------------------------------------------------------

class FormView(QWidget):
    """As páginas (sem as partes editáveis), com os campos e as caixas por cima."""

    def __init__(self, screen, base_path, data: forms.FormData):
        super().__init__()
        self.screen = screen
        self.data = data
        self.sizes = [g.size for g in data.pages]
        self.cache = PageCache(base_path)
        connect_alive(self.cache.ready, self, lambda o, *_: o.update())
        self.zoom = 1.0
        self.selected: forms.Box | None = None
        self.editor: BoxEditor | None = None
        self._drag = None              # (caixa, ponto inicial na tela, x, y da caixa)
        self._moved = False
        self.widgets: list = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        for f in data.fields:
            for w in f.widgets:
                if f.kind == "text":
                    cls = _TextField if f.multiline else _LineField
                else:
                    cls = FIELD_CLASSES[f.kind]
                self.widgets.append(cls(self, f, w))
        connect_alive(T.changed, self, lambda o, *_: o.update())

    # --- medidas (iguais às do leitor) ---
    def avail(self) -> float:
        return max(200.0, self.screen.scroll.viewport().width() - 2 * MARGIN)

    def base_width(self) -> float:
        return min(self.avail(), MAX_W)

    def _layout(self):
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
        return self.page_rect(i).width() / max(1.0, self.sizes[i][0])

    def to_screen(self, i: int, x0, y0, x1, y1) -> QRectF:
        r = self.page_rect(i)
        s = self.scale(i)
        return QRectF(r.x() + x0 * s, r.y() + y0 * s, (x1 - x0) * s, (y1 - y0) * s)

    def field_rect(self, w: forms.Widget):
        return self.data.pages[w.page].rect_to_display(w.rect)

    def box_rect(self, b: forms.Box) -> QRectF:
        w, h = b.size_pt()
        return self.to_screen(b.page, b.x, b.y, b.x + w, b.y + h)

    def locate(self, pos: QPointF):
        n = len(self.sizes)
        for i in range(n):
            r = self.page_rect(i)
            if r.contains(pos):
                s = self.scale(i)
                return i, (pos.x() - r.x()) / s, (pos.y() - r.y()) / s
        return None

    def relayout(self):
        bw = self.base_width() * self.zoom
        self.setMinimumWidth(int(bw) if bw > self.avail() else 0)
        self._layout()
        self.setFixedHeight(max(1, int(self._total)))
        self.place_children()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.place_children()

    def place_children(self):
        for wd in self.widgets:
            x0, y0, x1, y1 = self.field_rect(wd.wid)
            r = self.to_screen(wd.wid.page, x0, y0, x1, y1)
            wd.setGeometry(r.toAlignedRect())
            wd.show_value(self.screen.values.get(wd.field.name)) if hasattr(wd, "show_value") else wd.update()
        if self.editor is not None:
            self.editor.restyle()

    def refresh_values(self, source=None):
        for wd in self.widgets:
            if wd is source:
                continue
            if hasattr(wd, "show_value"):
                wd.show_value(self.screen.values.get(wd.field.name))
            else:
                wd.update()

    def set_zoom(self, z: float):
        self.zoom = max(0.5, min(4.0, z))
        self.relayout()

    def step_zoom(self, d: int):
        steps = [0.5, 0.67, 0.75, 0.9, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]
        cur = min(range(len(steps)), key=lambda k: abs(steps[k] - self.zoom))
        self.set_zoom(steps[max(0, min(len(steps) - 1, cur + d))])

    # --- desenho ---
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
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
                p.drawText(r, Qt.AlignCenter, trf("Página {}", i + 1))
            p.setPen(QPen(T.color("thumb_border"), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        for b in self.screen.boxes:
            br = self.box_rect(b)
            if not br.intersects(exposed.adjusted(-4, -4, 4, 4)):
                continue
            if b is self.selected:
                p.setPen(QPen(T.color("blue"), 1.2, Qt.DashLine))
                p.setBrush(QColor(41, 120, 245, 18))
                p.drawRect(br.adjusted(-2, -2, 2, 2))
            if self.editor is not None and self.editor.box is b:
                continue
            self.paint_box(p, b, br)

    def paint_box(self, p: QPainter, b: forms.Box, br: QRectF):
        s = self.scale(b.page)
        color = qcolor(forms.COLORS[b.color])
        if b.kind == "text":
            p.setPen(color)
            p.setFont(ui_font(b.font, b.bold, b.size * s))
            y = br.y() + (forms.BOX_PAD + b.size * forms.ASCENT) * s
            for line in b.text.split("\n"):
                i18n.draw_raw(p, QPointF(br.x() + forms.BOX_PAD * s, y), line)
                y += b.size * forms.LINE * s
            return
        path = mark_path(b.kind, br)
        if b.kind == "dot":
            p.setPen(Qt.NoPen)
            p.setBrush(color)
        else:
            p.setPen(QPen(color, max(0.8, b.size * 0.12) * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    # --- mouse ---
    def box_at(self, pos: QPointF):
        for b in reversed(self.screen.boxes):
            if self.box_rect(b).adjusted(-3, -3, 3, 3).contains(pos):
                return b
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus()
        pos = e.position()
        b = self.box_at(pos)
        if self.editor is not None and (b is None or b is not self.editor.box):
            self.finish_edit()
        if b is not None:
            self.select(b)
            self._drag = (b, pos, b.x, b.y)
            self._moved = False
            return
        tool = self.screen.tool
        hit = self.locate(pos)
        if hit is None:
            self.select(None)
            return
        page, x, y = hit
        if tool == "text":
            st = self.screen.style
            box = forms.Box(page, x - forms.BOX_PAD, y - (forms.BOX_PAD + st["size"] * forms.LINE / 2),
                            "text", "", st["font"], st["bold"], st["size"], st["color"])
            self._clamp(box)
            self.screen.boxes.append(box)
            self.select(box)
            self.edit(box)
        elif tool in forms.MARKS:
            st = self.screen.style
            size = max(10.0, st["size"] * 1.1)
            box = forms.Box(page, x - size / 2, y - size / 2, tool, "", st["font"], st["bold"], size, st["color"])
            self._clamp(box)
            self.screen.boxes.append(box)
            self.select(box)
            self.screen.commit()
        else:
            self.select(None)

    def _clamp(self, b: forms.Box):
        w, h = b.size_pt()
        pw, ph = self.sizes[b.page]
        b.x = max(0.0, min(pw - min(w, pw), b.x))
        b.y = max(0.0, min(ph - min(h, ph), b.y))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            b, start, x0, y0 = self._drag
            d = pos - start
            if not self._moved and abs(d.x()) + abs(d.y()) < 4:
                return
            self._moved = True
            s = self.scale(b.page)
            b.x, b.y = x0 + d.x() / s, y0 + d.y() / s
            self._clamp(b)
            if self.editor is not None and self.editor.box is b:
                self.editor.place()
            self.update()
            return
        b = self.box_at(pos)
        if b is not None:
            self.setCursor(Qt.SizeAllCursor)
        elif self.screen.tool == "text" and self.locate(pos) is not None:
            self.setCursor(Qt.IBeamCursor)
        elif self.screen.tool in forms.MARKS and self.locate(pos) is not None:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        b = self._drag[0]
        self._drag = None
        if self._moved:
            self.screen.commit()
        elif b.kind == "text" and self.screen.tool == "text" and self.editor is None:
            self.edit(b)

    def mouseDoubleClickEvent(self, e):
        b = self.box_at(e.position())
        if b is not None and b.kind == "text":
            self.edit(b)

    def select(self, b):
        self.selected = b
        if b is not None:
            self.screen.style = {"font": b.font, "bold": b.bold, "size": b.size if b.kind == "text" else self.screen.style["size"],
                                 "color": b.color}
        self.screen.sync_bar()
        self.update()

    def edit(self, b: forms.Box):
        if self.editor is not None:
            if self.editor.box is b:
                return
            self.finish_edit()
        self.editor = BoxEditor(self, b)
        self.editor.show()
        self.editor.setFocus()
        self.update()

    def finish_edit(self, editor=None):
        ed = self.editor
        if ed is None or (editor is not None and ed is not editor):
            return
        self.editor = None
        box = ed.box
        ed.hide()
        ed.deleteLater()
        if not box.text.strip():
            if box in self.screen.boxes:
                self.screen.boxes.remove(box)
            if self.selected is box:
                self.selected = None
        self.screen.commit()
        self.screen.sync_bar()
        self.update()

    def event(self, e):
        # Backspace volta de tela (atalho da janela); com uma caixa escolhida, ele apaga a caixa
        if e.type() == e.Type.ShortcutOverride and e.key() in (Qt.Key_Backspace, Qt.Key_Delete) \
                and self.selected is not None:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected is not None:
            self.screen.delete_selected()
            return
        if e.key() == Qt.Key_Escape:
            if self.selected is not None:
                self.select(None)
            else:
                self.screen.set_tool("select")
            return
        if self.selected is not None and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 5.0 if e.modifiers() & Qt.ShiftModifier else 0.5
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(e.key(), 0.0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(e.key(), 0.0)
            self.selected.x += dx
            self.selected.y += dy
            self._clamp(self.selected)
            self.update()
            self.screen.commit()
            return
        if self.selected is not None and self.selected.kind == "text" and e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
            self.edit(self.selected)
            return
        super().keyPressEvent(e)

    def shutdown(self):
        self.cache.shutdown()


# --- Tela ------------------------------------------------------------------------------

class FormScreen(Screen):
    large_title = False

    def __init__(self, app, item_id: str, base_path, data: forms.FormData):
        super().__init__(app)
        self.item_id = item_id
        self.item = app.lib.item(item_id)
        self.base_path = base_path
        self.data = data
        self.values = data.values()
        self.boxes: list[forms.Box] = copy.deepcopy(data.boxes)
        self.tool = "select" if data.fields else "text"
        self.style = {"font": "helvetica", "bold": False, "size": 12.0, "color": "black"}
        try:
            saved = json.loads(app.setting("form_style", "") or "{}")
        except (TypeError, ValueError):
            saved = {}
        if isinstance(saved, dict):
            self.style.update({k: v for k, v in saved.items() if k in self.style})
            self.style["bold"] = self.style["bold"] is True
            if self.style["font"] not in forms.FONTS:
                self.style["font"] = "helvetica"
            if self.style["color"] not in forms.COLORS:
                self.style["color"] = "black"
            try:
                self.style["size"] = float(self.style["size"])
            except (TypeError, ValueError):
                self.style["size"] = 12.0
        self._history = [self._snapshot()]
        self._pos = 0
        self._saved = self._snapshot()
        self._warned_chars = False
        self.add_back()
        self.big_title.hide()
        self.set_title(raw(self.item.name) if self.item else "")
        self.undo_btn = CircleButton("undo", "Desfazer (Ctrl+Z)")
        self.redo_btn = CircleButton("redo", "Refazer (Ctrl+Y)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.nav.left.addWidget(self.undo_btn)
        self.nav.left.addWidget(self.redo_btn)
        zo = CircleButton("zoom_out", "Diminuir (Ctrl -)")
        zi = CircleButton("zoom_in", "Aumentar (Ctrl +)")
        self.finish_btn = TextButton("Finalizar")
        self.finish_btn.setToolTip(tr("Cria uma cópia em que o preenchimento não pode mais ser alterado"))
        self.save_btn = TextButton("Salvar", bold=True)
        self.save_btn.setToolTip(tr("Gravar no PDF (Ctrl+S)"))
        for b in (zo, zi, self.finish_btn, self.save_btn):
            self.nav.right.addWidget(b)
        self.bar = FormatBar(self)
        self.layout().insertWidget(1, self.bar)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view = FormView(self, base_path, data)
        self.content.addWidget(self.view)
        self.finish_content()
        self.content.setContentsMargins(MARGIN, 12, MARGIN, 40)
        zo.clicked.connect(lambda: self.view.step_zoom(-1))
        zi.clicked.connect(lambda: self.view.step_zoom(1))
        self.save_btn.clicked.connect(lambda: self.save())
        self.finish_btn.clicked.connect(self.finalize)
        for seq, fn in (("Ctrl+S", lambda: self.save()), ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                        ("Ctrl+Shift+Z", self.redo), ("Ctrl+B", lambda: self.set_style(bold=not self.style["bold"])),
                        ("Ctrl++", lambda: self.view.step_zoom(1)), ("Ctrl+=", lambda: self.view.step_zoom(1)),
                        ("Ctrl+-", lambda: self.view.step_zoom(-1)), ("Ctrl+0", lambda: self.view.set_zoom(1.0))):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self.sync_bar()
        self._update_buttons()

    # --- estado ---
    def _snapshot(self):
        return dict(self.values), [copy.copy(b) for b in self.boxes]

    @staticmethod
    def _same(a, b) -> bool:
        if a[0] != b[0] or len(a[1]) != len(b[1]):
            return False
        return all(x.__dict__ == y.__dict__ for x, y in zip(a[1], b[1]))

    @property
    def dirty(self) -> bool:
        return not self._same(self._snapshot(), self._saved)

    def commit(self):
        snap = self._snapshot()
        if self._same(snap, self._history[self._pos]):
            self._update_buttons()
            return
        del self._history[self._pos + 1:]
        self._history.append(snap)
        if len(self._history) > 200:
            self._history.pop(0)
        self._pos = len(self._history) - 1
        self._update_buttons()

    def _restore(self, snap):
        if self.view.editor is not None:
            ed = self.view.editor
            self.view.editor = None
            ed.hide()
            ed.deleteLater()
        self.values = dict(snap[0])
        self.boxes = [copy.copy(b) for b in snap[1]]
        self.view.selected = None
        self.view.refresh_values()
        self.view.update()
        self.sync_bar()
        self._update_buttons()

    def undo(self):
        if self.view.editor is not None:
            self.view.finish_edit()
        if self._pos > 0:
            self._pos -= 1
            self._restore(self._history[self._pos])

    def redo(self):
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self._restore(self._history[self._pos])

    def _update_buttons(self):
        self.undo_btn.setEnabled(self._pos > 0 or self.view.editor is not None)
        self.redo_btn.setEnabled(self._pos < len(self._history) - 1)
        self.save_btn.setEnabled(self.dirty)

    def set_value(self, name, value, commit=True, source=None):
        self.values[name] = value
        self.view.refresh_values(source)
        if commit:
            self.commit()
        else:
            self._update_buttons()

    def filter_text(self, text: str) -> str:
        bad = forms.unsupported(text)
        if bad and not self._warned_chars:
            self._warned_chars = True
            self.app.toast(trf("Estas letras não podem ser gravadas no formulário: {}", raw(bad)))
        return "".join(ch for ch in text if forms.encodable(ch)) if bad else text

    # --- ferramentas e formatação ---
    def set_tool(self, tool: str):
        if self.view.editor is not None:
            self.view.finish_edit()
        self.tool = tool
        self.sync_bar()

    def set_style(self, **kw):
        self.style.update(kw)
        self.app.set_setting("form_style", json.dumps(self.style))
        b = self.view.selected
        if b is not None:
            if "font" in kw:
                b.font = kw["font"]
            if "bold" in kw:
                b.bold = kw["bold"]
            if "color" in kw:
                b.color = kw["color"]
            if "size" in kw:
                b.size = kw["size"] if b.kind == "text" else max(10.0, kw["size"] * 1.1)
            self.view._clamp(b)
            if self.view.editor is not None and self.view.editor.box is b:
                self.view.editor.restyle()
                self.view.editor.setFocus()
            else:
                self.commit()
            self.view.update()
        self.sync_bar()

    def sync_bar(self):
        self.bar.sync(self.tool, self.style, self.view.selected is not None if hasattr(self, "view") else False)
        if hasattr(self, "view"):
            self._update_buttons()

    def delete_selected(self):
        b = self.view.selected
        if b is None:
            return
        if self.view.editor is not None and self.view.editor.box is b:
            ed = self.view.editor
            self.view.editor = None
            ed.hide()
            ed.deleteLater()
        if b in self.boxes:
            self.boxes.remove(b)
        self.view.selected = None
        self.commit()
        self.sync_bar()
        self.view.update()

    # --- gravar ---
    def _flush(self):
        if self.view.editor is not None:
            self.view.finish_edit()
        fw = self.focusWidget()
        if fw is not None and fw is not self.view:
            self.view.setFocus()
        self.commit()

    def save(self, quiet=False) -> bool:
        self._flush()
        if not self.dirty:
            return True
        lib = self.app.lib
        item = lib.item(self.item_id)
        if item is None:
            self.app.show_error("O PDF foi movido ou apagado.")
            return False
        values = dict(self.values)
        boxes = [b for b in self.boxes if b.kind != "text" or b.text.strip()]
        ok = self.app.attempt(lambda: lib.modify(item, lambda p: forms.save(p, values, boxes), keep_review=True),
                              busy="Salvando…")
        if ok:
            self._saved = self._snapshot()
            self._history[self._pos] = self._saved
            self._update_buttons()
            if not quiet:
                self.app.toast("Formulário salvo no PDF.")
        return ok

    def finalize(self):
        self._flush()
        idx = alert(self.app, "Finalizar o formulário?",
                    "O Prumo cria uma cópia em que os campos e o texto viram parte da página e não podem mais ser "
                    "alterados. O original continua editável.",
                    [("Finalizar", "default"), ("Cancelar", "cancel")])
        if idx != 0:
            return
        if self.dirty and not self.save(quiet=True):
            return
        lib = self.app.lib
        item = lib.item(self.item_id)
        if item is None:
            return
        tmp = lib.temp_path()
        try:
            forms.flatten(item.path, tmp)
            base = i18n.strip_suffix(item.name, "{} - preenchido")
            new = lib.adopt(tmp, trf("{} - preenchido", base), item.folder)
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            self.app.show_error(trf("Não foi possível finalizar: {}", exc))
            return
        self.app.toast("Formulário finalizado: cópia criada.", "Abrir", lambda: self.app.open_document(new.id))

    def can_leave(self) -> bool:
        self._flush()
        if not self.dirty:
            return True
        idx = alert(self.app, "Salvar o preenchimento?", "O que foi preenchido ainda não foi gravado no PDF.",
                    [("Salvar", "default"), ("Descartar", "destructive"), ("Continuar editando", "cancel")])
        if idx == 0:
            return self.save(quiet=True)
        return idx == 1

    # --- tela ---
    def on_shown(self):
        QTimer.singleShot(0, self.view.relayout)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "view"):
            QTimer.singleShot(0, self.view.relayout)

    def closing(self):
        self.view.shutdown()
        try:
            from pathlib import Path
            Path(self.base_path).unlink(missing_ok=True)
        except OSError:
            pass


def open_form(app, item) -> FormScreen | None:
    """Abre a tela de preenchimento (do leitor, da tela do PDF, do menu ⋮ ou da tela inicial)."""
    if item is None:
        return None
    if item.meta.locked:
        app.toast("Este PDF tem senha. Para preencher, crie antes uma cópia sem senha.")
        return None
    if getattr(item.meta, "signed", 0):
        from screens import SIGNED_EDIT_MSG
        app.toast(SIGNED_EDIT_MSG)
        return None
    try:
        data = forms.load(item.path)
    except forms.FormError as exc:
        app.show_error(tr(str(exc)))
        return None
    except Exception as exc:  # noqa: BLE001
        app.show_error(trf("Não foi possível abrir o formulário: {}", exc))
        return None
    if data.xfa_only:
        idx = alert(app, "Formulário XFA",
                    "Este PDF usa um tipo de formulário (XFA) que só o Adobe Acrobat preenche. No Prumo, dá para "
                    "escrever por cima da página com caixas de texto.",
                    [("Usar caixas de texto", "default"), ("Cancelar", "cancel")])
        if idx != 0:
            return None
    base = app.lib.temp_path()
    try:
        forms.make_base(item.path, base)
    except Exception as exc:  # noqa: BLE001
        base.unlink(missing_ok=True)
        app.show_error(trf("Não foi possível abrir o formulário: {}", exc))
        return None
    screen = FormScreen(app, item.id, base, data)
    app.push(screen)
    if not data.fields:
        app.toast("Este PDF não tem campos: clique na página para escrever.")
    return screen
