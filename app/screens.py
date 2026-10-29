"""Telas do Prumo PDF para Windows, na mesma organização do app do iPhone."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIntValidator, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout,
                               QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

import pdfops
from ios_kit import (CircleButton, DocTile, EmptyState, FlowGrid, Label, PrimaryButton, Screen,
                     SearchField, SectionTitle, SheetOverlay, TextButton, Thumb, Tile, TileCard,
                     WideTile, action_sheet, alert, elide, menu_action, paint_badge, sheet_header,
                     styled_menu, wrap_lines)
from ios_theme import MARGIN, SPACING, TILE_RADIUS, T, font, glyph_icon, paint_glyph
from library import LISTS, TEXT_LABELS, needs_ocr_status


def pages_text(n: int) -> str:
    return "1 página" if n == 1 else f"{n} páginas"


def size_text(n: int) -> str:
    if n < 1000:
        return f"{n} bytes"
    for unit in ("KB", "MB", "GB"):
        n /= 1000
        if n < 1000 or unit == "GB":
            return (f"{n:.0f} {unit}" if n >= 10 or unit == "KB" else f"{n:.1f} {unit}").replace(".", ",")
    return ""


def date_text(ts: float) -> str:
    return time.strftime("%d/%m/%Y, %H:%M", time.localtime(ts))


# --- Ações comuns sobre PDFs --------------------------------------------------

class Actions:
    """Renomear, mover, excluir, compartilhar, OCR: usadas por várias telas."""

    def __init__(self, app):
        self.app = app

    @property
    def lib(self):
        return self.app.lib

    def rename(self, item):
        idx, text = alert(self.app, "Renomear PDF", "", [("Cancelar", "cancel"), ("Salvar", "default")],
                          text=item.name, placeholder="Nome")
        if idx == 1:
            self.app.attempt(lambda: self.lib.rename(item, text))

    def move(self, items):
        if not items:
            return
        title = "Mover PDF" if len(items) == 1 else f"Mover {len(items)} PDFs"
        folder = pick_folder(self.app, title, items[0].folder if len(items) == 1 else None)
        if folder is None:
            return
        if self.app.attempt(lambda: self.lib.move(items, folder)):
            self.app.toast(f"Movido para {folder.rsplit('/', 1)[-1] if folder else 'Sem pasta'}.")

    def delete(self, items, after=None) -> bool:
        if not items:
            return False
        title = f"Excluir “{items[0].name}”?" if len(items) == 1 else f"Excluir {len(items)} PDFs?"
        idx = alert(self.app, title,
                    "O arquivo vai para a Lixeira do Windows. Dá para recuperar por lá, se precisar.",
                    [("Cancelar", "cancel"), ("Excluir", "destructive")])
        if idx == 1 and self.app.attempt(lambda: self.lib.delete(items)):
            if after:
                after()
            return True
        return False

    def share(self, items):
        if not items:
            return
        one = len(items) == 1
        options = [
            ("Copiar arquivo" if one else f"Copiar {len(items)} arquivos", "default", "copy"),
            ("Exportar cópia para…", "default", "export"),
            ("Mostrar no Explorador", "default", "explorer"),
        ]
        if one:
            options.append(("Abrir no leitor de PDF", "default", "open"))
        idx = action_sheet(self.app, "Compartilhar",
                           "“Copiar” coloca o arquivo na área de transferência: depois é só colar (Ctrl+V) "
                           "no WhatsApp, no e-mail ou em outra pasta.", options)
        if idx == 0:
            self.app.copy_files([i.path for i in items])
            self.app.toast("Arquivo copiado. Cole com Ctrl+V onde quiser." if one
                           else f"{len(items)} arquivos copiados. Cole com Ctrl+V onde quiser.")
        elif idx == 1:
            self.app.export_copies(items)
        elif idx == 2:
            self.app.reveal(items[0].path)
        elif idx == 3:
            self.app.open_external(items[0])

    def ocr(self, item):
        self.app.start_ocr(item)

    def request_ocr(self, item):
        """OCR com os avisos da tela do PDF (já em andamento, já tem cópia, já tem texto)."""
        lib = self.lib
        copy = lib.ocr_copy(item)
        if self.app.jobs.is_busy(item.id):
            self.app.toast("O OCR deste PDF já está em andamento.")
        elif item.meta.is_ocr_result:
            self.app.toast("Este arquivo já é o resultado de um OCR.")
        elif copy is not None:
            self.app.toast(f"Já existe uma cópia com OCR: {copy.name}", "Abrir",
                           lambda: self.app.open_document(copy.id))
        elif item.meta.text_status == "digital":
            self.app.toast("Todas as páginas já têm texto selecionável. O OCR não é necessário.")
        else:
            self.app.start_ocr(item)

    def duplicate(self, item):
        res = {}
        if self.app.attempt(lambda: res.setdefault("c", self.lib.duplicate(item))) and res.get("c"):
            self.app.toast(f"Cópia criada: {res['c'].name}", "Abrir", lambda: self.app.open_document(res["c"].id))

    def undo(self, item) -> bool:
        if not self.lib.can_undo(item):
            self.app.toast("Não há alteração para desfazer neste PDF.")
            return False
        idx = alert(self.app, "Desfazer a última alteração?",
                    "O PDF volta a ficar como estava antes da última mudança (páginas, destaques, cortes ou numeração).",
                    [("Cancelar", "cancel"), ("Desfazer", "default")])
        if idx == 1 and self.app.attempt(lambda: self.lib.undo(item)):
            self.app.toast("Alteração desfeita.")
            return True
        return False

    def toggle_favorite(self, item):
        on = not item.meta.favorite
        self.lib.set_favorite(item, on)
        self.app.toast("Adicionado aos Favoritos." if on else "Removido dos Favoritos.")

    def context_menu(self, tile, item, pos, extra_open=True):
        m = styled_menu(tile)
        if extra_open:
            menu_action(m, "Abrir", "docs", lambda: self.app.open_document(item.id))
        menu_action(m, "Ler", "book", lambda: self.app.read(item))
        menu_action(m, "Compartilhar…", "share", lambda: self.share([item]))
        if self.lib.needs_ocr_attention(item):
            menu_action(m, "Fazer OCR", "textscan", lambda: self.ocr(item))
        menu_action(m, "Organizar páginas", "grid", lambda: self.app.organize(item))
        menu_action(m, "Remover dos favoritos" if item.meta.favorite else "Favoritar", "star",
                    lambda: self.toggle_favorite(item))
        m.addSeparator()
        menu_action(m, "Renomear", "pencil", lambda: self.rename(item))
        menu_action(m, "Mover para pasta", "folder_line", lambda: self.move([item]))
        menu_action(m, "Mostrar no Explorador", "explorer", lambda: self.app.reveal(item.path))
        m.addSeparator()
        menu_action(m, "Excluir", "trash", lambda: self.delete([item]), destructive=True)
        m.exec(tile.mapToGlobal(pos))


def make_doc_tile(app, item, show_folder=False, on_click=None, menu=True):
    tile = DocTile(item, app.hub.thumbs, needs_ocr=app.lib.needs_ocr_attention(item), show_folder=show_folder,
                   show_actions=menu)
    action = on_click or (lambda: app.open_document(item.id))
    # O clique do Qt manda um valor (checked); ele não pode chegar à ação, que às vezes tem
    # argumentos com valor padrão (ex.: lambda it=it), senão o PDF escolhido vira False.
    tile.clicked.connect(lambda _checked=False: action())
    if menu:
        current = lambda: app.lib.item(item.id) or item  # noqa: E731
        tile.setContextMenuPolicy(Qt.CustomContextMenu)
        tile.customContextMenuRequested.connect(lambda pos: app.actions.context_menu(tile, current(), pos))
        tile.menu_clicked.connect(
            lambda: app.actions.context_menu(tile, current(), tile.dots_rect().bottomRight().toPoint()))
        tile.star_clicked.connect(lambda: app.actions.toggle_favorite(current()))
    return tile


def make_folder_tile(app, folder, on_click=None):
    sub = folder.subfolder_count
    tile = Tile(folder.name, "folder", "indigo", str(folder.total_doc_count),
                f"{sub} subpasta{'s' if sub != 1 else ''}" if sub else None, rounded_icon=True)
    tile.clicked.connect(on_click or (lambda: app.push(DocumentGridScreen(app, folder=folder.path))))
    tile.setContextMenuPolicy(Qt.CustomContextMenu)

    def menu(pos):
        m = styled_menu(tile)
        menu_action(m, "Renomear", "pencil", lambda: rename_folder(app, folder.path))
        menu_action(m, "Mostrar no Explorador", "explorer", lambda: app.reveal(app.lib.folder_path(folder.path)))
        m.addSeparator()
        menu_action(m, "Excluir pasta", "trash", lambda: delete_folder(app, folder), destructive=True)
        m.exec(tile.mapToGlobal(pos))
    tile.customContextMenuRequested.connect(menu)
    return tile


def create_folder(app, parent="") -> str | None:
    idx, name = alert(app, "Nova subpasta" if parent else "Nova pasta",
                      "Por exemplo, o nome do cliente ou o número do processo.",
                      [("Cancelar", "cancel"), ("Criar", "default")], text="", placeholder="Nome da pasta")
    if idx == 1:
        result = {}
        if app.attempt(lambda: result.setdefault("p", app.lib.create_folder(name, parent))):
            return result.get("p")
    return None


def add_pdfs_to_folder(app, folder: str) -> list:
    """
    Adiciona PDFs a uma pasta: do computador (copia para dentro dela) ou de qualquer lugar
    da biblioteca (outra pasta, Todos os PDFs, Favoritos…), movendo ou copiando.
    """
    name = folder.rsplit("/", 1)[-1] if folder else "Sem pasta"
    picked = choose_documents(app, f"Adicionar a “{name}”", multiple=True, allow_import=True,
                              import_folder=folder, exclude_folder=folder)
    if not picked:
        return []
    from_lib = [i for i in picked if i.folder != folder]
    if not from_lib:
        return picked   # vieram do computador e já foram copiados para a pasta
    n = len(from_lib)
    idx = alert(app, f"Mover ou copiar {'o PDF' if n == 1 else f'os {n} PDFs'}?",
                "“Mover” tira o arquivo da pasta onde ele está. “Copiar” deixa o original lá e cria "
                "uma cópia nesta pasta.",
                [("Mover", "default"), ("Copiar", "default"), ("Cancelar", "cancel")])
    if idx == 0:
        if app.attempt(lambda: app.lib.move(from_lib, folder)):
            app.toast(f"{'PDF movido' if n == 1 else f'{n} PDFs movidos'} para {name}.")
    elif idx == 1:
        if app.attempt(lambda: app.lib.copy_into(from_lib, folder), busy="Copiando…"):
            app.toast(f"{'PDF copiado' if n == 1 else f'{n} PDFs copiados'} para {name}.")
    return picked


def new_folder_flow(app, parent=""):
    """Cria a pasta, abre e oferece adicionar PDFs logo em seguida."""
    path = create_folder(app, parent)
    if path is None:
        return None
    app.push(DocumentGridScreen(app, folder=path))
    add_pdfs_to_folder(app, path)
    return path


def rename_folder(app, path):
    idx, name = alert(app, "Renomear pasta", "", [("Cancelar", "cancel"), ("Salvar", "default")],
                      text=path.rsplit("/", 1)[-1], placeholder="Nome da pasta")
    if idx == 1:
        app.attempt(lambda: app.lib.rename_folder(path, name))


def delete_folder(app, folder):
    n = folder.total_doc_count
    if n == 0:
        msg = "A pasta está vazia."
    elif n == 1:
        msg = "A pasta e o PDF dentro dela vão para a Lixeira do Windows."
    else:
        msg = f"A pasta e os {n} PDFs dentro dela vão para a Lixeira do Windows."
    idx = alert(app, f"Excluir a pasta “{folder.name}”?", msg,
                [("Cancelar", "cancel"), ("Excluir", "destructive")])
    if idx == 1:
        app.attempt(lambda: app.lib.delete_folder(folder.path))


class _FolderRow(QAbstractButton):
    def __init__(self, title, depth, current, count, parent=None):
        super().__init__(parent)
        self.title, self.depth, self.current, self.count = title, depth, current, count
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.underMouse() or self.isDown():
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("tile"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(6, 1, -6, -1), 10, 10)
        x = 18 + 20 * self.depth
        paint_glyph(p, QRectF(x, 13, 20, 20), "tray" if self.depth < 0 else "folder",
                    T.color("gray" if self.title == "Sem pasta" else "indigo"), 1.6)
        p.setPen(T.color("text"))
        p.setFont(font(15, 600 if self.current else 400))
        p.drawText(QRectF(x + 30, 0, self.width() - x - 90, 46), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        p.setPen(T.color("secondary"))
        p.setFont(font(13))
        right = "Atual" if self.current else str(self.count)
        p.drawText(QRectF(0, 0, self.width() - 20, 46), Qt.AlignVCenter | Qt.AlignRight, right)


def pick_folder(app, title: str, current: str | None):
    """Escolha de pasta (com opção de criar uma nova). Devolve o caminho, "" para Sem pasta, ou None."""
    while True:
        ov = SheetOverlay(app, 420)
        sheet_header(ov, title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 8)
        col.setSpacing(0)
        rows = [("", "Sem pasta", -0, len(app.lib.items_in_folder("")))]
        for f in app.lib.folders:
            rows.append((f.path, f.name, f.path.count("/") + 1, f.total_doc_count))
        for path, name, depth, count in rows:
            r = _FolderRow(name, depth if path else 0, current == path, count)
            r.clicked.connect(lambda _c=False, path=path: ov.done(("pick", path)))
            col.addWidget(r)
        new = QPushButton("  Nova pasta")
        new.setIcon(glyph_icon("folderplus", T.color("blue"), 20))
        new.setCursor(Qt.PointingHandCursor)
        new.setFont(font(15, 600))
        new.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {T.color('blue').name()};"
                          f" text-align: left; padding: 12px 18px; }}")
        new.clicked.connect(lambda: ov.done(("new", None)))
        col.addWidget(new)
        scroll.setWidget(body)
        scroll.setMinimumHeight(min(480, 50 * len(rows) + 60))
        ov.lay.addWidget(scroll)
        res = ov.run()
        if res is None:
            return None
        if res[0] == "pick":
            return res[1]
        created = create_folder(app)
        if created is not None:
            return created


# --- Tela inicial ---------------------------------------------------------------

class HomeScreen(Screen):
    """
    Tela inicial: listas da biblioteca em cima e, embaixo, todas as ferramentas. Cada
    ferramenta pede o PDF na hora: do computador (entra na biblioteca) ou um já no Prumo.
    """

    def __init__(self, app):
        super().__init__(app)
        gear = CircleButton("gear", "Ajustes")
        gear.clicked.connect(lambda: app.push(SettingsScreen(app)))
        self.nav.right.addWidget(gear)
        self.set_title("Prumo PDF")
        self.search = SearchField("Buscar nome ou texto")
        self.search.debounced.connect(lambda _t: self.refresh())
        self.content.addWidget(self.search)
        self.tiles = {}

        self.grid = FlowGrid(max_cols=3)   # 6 cartões: 2 ou 3 colunas fecham as linhas
        self.tools = FlowGrid(max_cols=5)  # 10 cartões: 2 ou 5 colunas

        def add(grid, key, title, icon, color, rounded=False, cb=None, subtitle=None):
            t = Tile(title, icon, color, subtitle=subtitle, rounded_icon=rounded)
            t.clicked.connect(cb)
            self.tiles[key] = t
            grid.add(t)

        g = self.grid
        add(g, "all", "Todos os PDFs", "docs", "red", False, lambda: app.push(DocumentGridScreen(app, list_id="all")))
        add(g, "recent", "Recentes", "clock", "gray", False, lambda: app.push(DocumentGridScreen(app, list_id="recent")))
        add(g, "pending", "Aguardando OCR", "textscan", "orange", True,
            lambda: app.push(DocumentGridScreen(app, list_id="pending")))
        add(g, "ocr", "Com OCR", "check", "green", False, lambda: app.push(DocumentGridScreen(app, list_id="ocr")))
        add(g, "favorites", "Favoritos", "star", "yellow", True,
            lambda: app.push(DocumentGridScreen(app, list_id="favorites")))
        add(g, "import", "Importar", "import", "blue", True, lambda: app.import_dialog(""))

        t = self.tools
        add(t, "read", "Ler", "book", "blue", False, lambda: self._tool("read"))
        add(t, "do_ocr", "Fazer OCR", "textscan", "orange", True, lambda: self._tool("ocr"))
        add(t, "organize", "Organizar páginas", "grid", "purple", True, lambda: self._tool("organize"))
        add(t, "insert", "Incluir páginas", "plusrect", "teal", True, lambda: self._tool("insert"))
        add(t, "remove", "Remover páginas", "minusrect", "red", True, lambda: self._tool("remove"))
        add(t, "extract", "Extrair páginas", "docplus", "indigo", False, lambda: self._tool("extract"))
        add(t, "split", "Dividir em partes", "scissors", "pink", False, lambda: self._tool("split"))
        add(t, "merge", "Combinar PDFs", "stack", "purple", True, lambda: app.push(MergeScreen(app)))
        add(t, "crop", "Cortar e girar", "crop", "indigo", True, lambda: self._tool("crop"))
        add(t, "number", "Numerar páginas", "numbers", "indigo", False, lambda: self._tool("number"))
        add(t, "sign", "Assinar digitalmente", "signature", "blue", True, lambda: self._tool("sign"))

        self.folders = WideTile("Pastas", "folder", "indigo")
        self.folders.clicked.connect(lambda: app.push(FoldersScreen(app)))
        self.home_box = QWidget()
        hb = QVBoxLayout(self.home_box)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(SPACING)
        hb.addWidget(self.grid)
        hb.addWidget(self.folders)
        hb.addWidget(SectionTitle("Ferramentas"))
        hb.addWidget(self.tools)
        self.convert = WideTile("Converter em PDF", "convert", "teal",
                                subtitle="Fotos e imagens (JPG, PNG, HEIC do iPhone), Word, Excel, PowerPoint, texto")
        self.convert.clicked.connect(lambda: app.convert_dialog(""))
        hb.addWidget(self.convert)
        credit = Label("Color Software", 12, 600, "secondary", wrap=False)
        credit.setAlignment(Qt.AlignCenter)
        credit.setContentsMargins(0, 18, 0, 0)
        hb.addWidget(credit)
        self.content.addWidget(self.home_box)
        self.results_box = QWidget()
        self.results = QVBoxLayout(self.results_box)
        self.results.setContentsMargins(0, 0, 0, 0)
        self.results.setSpacing(SPACING)
        self.content.addWidget(self.results_box)
        self.finish_content()
        self._last_query = None

    TOOL_TITLES = {"read": "Ler qual PDF?", "ocr": "Fazer OCR de quais PDFs?",
                   "organize": "Organizar qual PDF?", "insert": "Incluir páginas em qual PDF?",
                   "remove": "Remover páginas de qual PDF?", "extract": "Extrair páginas de qual PDF?",
                   "split": "Dividir qual PDF?", "crop": "Cortar ou girar páginas de qual PDF?",
                   "number": "Numerar as páginas de qual PDF?", "sign": "Assinar qual PDF?"}

    def _tool(self, key):
        run_tool(self.app, key, self.TOOL_TITLES[key])

    def refresh(self):
        lib = self.app.lib
        self.tiles["all"].set_content(count=str(len(lib.items)))
        for key in ("recent", "pending", "ocr", "favorites"):
            self.tiles[key].set_content(count=str(lib.count(key)))
        self.folders.set_content(count=str(len(lib.top_folders)))
        q = self.search.text().strip()
        self.home_box.setVisible(not q)
        self.results_box.setVisible(bool(q))
        while self.results.count():
            w = self.results.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if q:
            found = lib.search(q)
            if not found:
                self.results.addWidget(EmptyState(
                    "search", "Nada encontrado",
                    "A busca procura no nome dos arquivos e no texto dos PDFs. "
                    "PDFs escaneados só aparecem pelo texto depois do OCR."))
            else:
                self.results.addWidget(SectionTitle(f"{len(found)} resultado{'s' if len(found) != 1 else ''}"))
                g = FlowGrid()
                for it in found:
                    g.add(make_doc_tile(self.app, it, show_folder=True))
                self.results.addWidget(g)


SIGNED_EDIT_MSG = ("Este PDF está assinado digitalmente: qualquer alteração invalidaria a assinatura. Use o "
                   "original (sem assinatura) para mudar páginas, cortar, numerar ou destacar.")
EDIT_TOOLS = {"organize", "insert", "remove", "crop", "number", "dewarp", "protect"}


def blocked_signed(app, item) -> bool:
    """PDF assinado não pode ser alterado: avisa e devolve True."""
    if item is not None and getattr(item.meta, "signed", 0):
        app.toast(SIGNED_EDIT_MSG)
        return True
    return False


def run_tool(app, key, title):
    """Escolhe o PDF (do computador ou da biblioteca) e abre a ferramenta pedida."""
    multiple = key == "ocr"
    picked = choose_documents(app, title, multiple=multiple, allow_import=True,
                              only=(app.lib.needs_ocr_attention if key == "ocr" else None))
    if not picked:
        return
    item = picked[0]
    if key in EDIT_TOOLS and blocked_signed(app, item):
        return
    if key == "read":
        app.read(item)
    elif key == "ocr":
        todo = [i for i in picked if app.lib.needs_ocr_attention(i)]
        for i in todo:
            app.start_ocr(i, quiet=len(todo) > 1)
        if not todo:
            app.toast("Esses PDFs já têm texto selecionável. O OCR não é necessário.")
        elif len(todo) > 1:
            app.toast(f"{len(todo)} PDFs na fila do OCR.")
    elif key == "organize":
        app.organize(item)
    elif key == "insert":
        include_pages_dialog(app, item)
    elif key == "remove":
        app.push(PagePickerScreen(app, item.id, "remove"))
    elif key == "extract":
        app.push(PagePickerScreen(app, item.id, "extract"))
    elif key == "split":
        split_dialog(app, item)
    elif key == "crop":
        import page_tools
        page_tools.crop_dialog(app, item)
    elif key == "number":
        import page_tools
        page_tools.number_dialog(app, item)
    elif key == "sign":
        import sign_ui
        sign_ui.sign_dialog(app, item)


# --- Listas e pastas ------------------------------------------------------------

SORTS = [("recent", "Mais recentes"), ("name", "Nome"), ("pages", "Número de páginas")]


class SelectionBar(QWidget):
    """Barra flutuante do modo de seleção: compartilhar, mover, combinar, excluir."""

    def __init__(self, screen):
        super().__init__(screen)
        self.screen = screen
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 12, 10)
        lay.setSpacing(6)
        self.label = Label("", 14, 600, wrap=False)
        lay.addWidget(self.label, 1)
        self.buttons = {}
        for key, glyph, tip in (("share", "share", "Compartilhar"), ("move", "folder_line", "Mover"),
                                ("merge", "stack", "Combinar"), ("ocr", "textscan", "Fazer OCR"),
                                ("delete", "trash", "Excluir")):
            b = QPushButton()
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(40, 40)
            b.setIconSize(QSize(22, 22))
            b.clicked.connect(lambda _c=False, k=key: screen.selection_action(k))
            self.buttons[key] = b
            lay.addWidget(b)
        self.hide()

    def update_state(self, n: int, any_ocr: bool):
        self.label.setText("Clique nos PDFs ou arraste sobre eles" if n == 0
                           else f"{n} selecionado{'s' if n != 1 else ''}")
        enabled = {"share": n > 0, "move": n > 0, "merge": n >= 2, "ocr": any_ocr, "delete": n > 0}
        for k, b in self.buttons.items():
            glyph = {"share": "share", "move": "folder_line", "merge": "stack", "ocr": "textscan", "delete": "trash"}[k]
            color = T.color("red" if k == "delete" else "blue")
            if not enabled[k]:
                color = T.color("placeholder")
            b.setIcon(glyph_icon(glyph, color, 22))
            b.setEnabled(enabled[k])
            b.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 20px; }"
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
        w = min(620, self.screen.width() - 2 * MARGIN)
        self.setFixedSize(w, 63)
        self.move((self.screen.width() - w) // 2, self.screen.height() - 63 - 14)


class DocumentGridScreen(Screen):
    """Lista de PDFs em cartões: listas da tela inicial e pastas."""

    def __init__(self, app, list_id: str | None = None, folder: str | None = None):
        super().__init__(app)
        self.list_id, self.folder = list_id, folder
        self.sort = app.setting("sort", "recent")
        self.selecting = False
        self.selected: list[str] = []
        self.add_back()
        self.more = CircleButton("ellipsis", "Mais opções")
        self.more.clicked.connect(self._menu)
        self.ok = TextButton("OK", bold=True)
        self.ok.clicked.connect(lambda: self.set_selecting(False))
        self.ok.hide()
        self.nav.right.addWidget(self.ok)
        self.nav.right.addWidget(self.more)
        self.set_title(self._title())
        self.search = SearchField(f"Buscar em {self._title()}")
        self.search.debounced.connect(lambda _t: self.refresh())
        self.content.addWidget(self.search)
        self.bar = SelectionBar(self)
        self._tiles = []
        self._band_base: list[str] = []
        from rubberband import RubberBand, rect_in
        self.band = RubberBand(self.body, self.scroll,
                               lambda: [(t.item.id, rect_in(self.body, t)) for t in self._tiles if t.isVisible()],
                               self._band_select, self._band_start, self._band_can_start)
        self.finish_content()

    # --- seleção com o retângulo (clicar e arrastar) ---
    @staticmethod
    def _band_can_start(widget, pos) -> bool:
        # a estrela e os três pontos continuam sendo botões
        return not (isinstance(widget, DocTile) and widget._target(pos))

    def _band_start(self, additive: bool):
        self._band_base = list(self.selected) if (self.selecting and additive) else []

    def _band_select(self, keys: set, additive: bool, final: bool):
        order = [t.item.id for t in self._tiles]
        sel = self._band_base + [k for k in order if k in keys and k not in self._band_base]
        if not final:
            for t in self._tiles:
                t.set_selection(t.item.id in sel)
            return
        if not sel and not self.selecting:
            for t in self._tiles:
                t.set_selection(None)
            return
        if self.selecting:
            self.selected = sel
            for t in self._tiles:
                t.set_selection(t.item.id in sel)
            self._update_bar()
        else:
            self.selected = sel
            self.set_selecting(True, keep=True)

    def _title(self):
        if self.list_id:
            return LISTS[self.list_id]
        return self.folder.rsplit("/", 1)[-1] if self.folder else "Sem pasta"

    def drop_folder(self) -> str:
        return self.folder or ""

    def base_items(self):
        lib = self.app.lib
        return lib.items_for(self.list_id) if self.list_id else lib.items_in_folder(self.folder)

    def docs(self):
        base = self.base_items()
        q = self.search.text().strip()
        if q:
            return self.app.lib.search(q, base)
        if self.sort == "name":
            return sorted(base, key=lambda i: i.name.casefold())
        if self.sort == "pages":
            return sorted(base, key=lambda i: -(i.page_count or 0))
        if self.list_id == "recent":
            return base
        return sorted(base, key=lambda i: -i.modified)

    def _menu(self):
        m = styled_menu(self.more)
        menu_action(m, "Selecionar", "select", lambda: self.set_selecting(True))
        sub = m.addMenu(glyph_icon("sort", T.color("text"), 18), "Ordenar")
        for key, label in SORTS:
            menu_action(sub, label, None, lambda k=key: self._set_sort(k), checked=self.sort == key)
        if self.folder is not None:
            m.addSeparator()
            menu_action(m, "Adicionar PDFs…", "plus", lambda: add_pdfs_to_folder(self.app, self.folder))
            menu_action(m, "Importar do computador…", "import", lambda: self.app.import_dialog(self.folder))
            menu_action(m, "Converter em PDF aqui…", "convert", lambda: self.app.convert_dialog(self.folder))
            if self.folder:
                menu_action(m, "Nova subpasta", "folderplus", lambda: new_folder_flow(self.app, self.folder))
            menu_action(m, "Mostrar no Explorador", "explorer",
                        lambda: self.app.reveal(self.app.lib.folder_path(self.folder)))
        m.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _set_sort(self, key):
        self.sort = key
        self.app.set_setting("sort", key)
        self.refresh()

    def set_selecting(self, on: bool, keep: bool = False):
        self.selecting = on
        if not keep:
            self.selected = []
        self.more.setVisible(not on)
        self.ok.setVisible(on)
        self.refresh()

    def _toggle(self, item):
        if item.id in self.selected:
            self.selected.remove(item.id)
        else:
            self.selected.append(item.id)
        for t in self._tiles:
            if t.item.id == item.id:
                t.set_selection(item.id in self.selected)
        self._update_bar()

    def _update_bar(self):
        items = self.selected_items()
        self.bar.update_state(len(items), any(self.app.lib.needs_ocr_attention(i) for i in items))
        self.bar.setVisible(self.selecting)
        if self.selecting:
            self.bar.place()
            self.bar.raise_()

    def selected_items(self):
        lib = self.app.lib
        return [i for i in (lib.item(x) for x in self.selected) if i]

    def selection_action(self, key):
        items = self.selected_items()
        a = self.app.actions
        if key == "share":
            a.share(items)
        elif key == "move":
            a.move(items)
        elif key == "merge":
            self.app.push(MergeScreen(self.app, preselection=[i.id for i in items]))
            self.set_selecting(False)
        elif key == "ocr":
            for i in items:
                if self.app.lib.needs_ocr_attention(i):
                    self.app.start_ocr(i, quiet=True)
        elif key == "delete":
            a.delete(items, after=lambda: self.selected.clear())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.bar.isVisible():
            self.bar.place()

    def refresh(self):
        app, lib = self.app, self.app.lib
        pos = self.scroll.verticalScrollBar().value()
        self.clear_after_title(2)
        self._tiles = []
        docs = self.docs()
        q = self.search.text().strip()
        if self.list_id == "pending" and docs and not self.selecting:
            w = WideTile("Fazer OCR de todos", "textscan", "orange", str(len(docs)),
                         "Um arquivo por vez; cada um gera uma cópia com “OCR” no nome")
            w.clicked.connect(lambda: [app.start_ocr(i, quiet=True) for i in self.docs()])
            self.content.addWidget(w)
        if self.folder is not None and not q and not self.selecting:
            add = WideTile("Adicionar PDFs", "plus", "blue",
                           subtitle="Do computador (PDFs, fotos, Word…) ou de outra parte do Prumo")
            add.clicked.connect(lambda: add_pdfs_to_folder(app, self.folder))
            self.content.addWidget(add)
        subs = lib.subfolders(self.folder) if self.folder and not q else []
        if subs:
            g = FlowGrid()
            for f in subs:
                g.add(make_folder_tile(app, f))
            self.content.addWidget(g)
        if not docs and not subs:
            self.content.addWidget(self._empty(q))
        elif docs:
            g = FlowGrid()
            for it in docs:
                if self.selecting:
                    t = make_doc_tile(app, it, show_folder=self.folder is None, menu=False,
                                      on_click=lambda it=it: self._toggle(it))
                    t.set_selection(it.id in self.selected)
                else:
                    t = make_doc_tile(app, it, show_folder=self.folder is None)
                self._tiles.append(t)
                g.add(t)
            self.content.addWidget(g)
        self.finish_content()
        self._update_bar()
        self.scroll.verticalScrollBar().setValue(pos)

    def _empty(self, q):
        if q:
            return EmptyState("search", "Nada encontrado", "Tente outro termo.")
        texts = {
            "pending": ("seal", "Nada aguardando OCR", "PDFs escaneados ou em imagem aparecem aqui até você fazer o OCR."),
            "favorites": ("star", "Nenhum favorito", "Clique na estrela de um PDF para ele aparecer aqui."),
            "ocr": ("textscan", "Nenhum PDF com OCR", "Os arquivos criados pelo OCR aparecem aqui."),
            "recent": ("clock", "Nada recente", "Os PDFs abertos ou alterados nos últimos 7 dias aparecem aqui."),
        }
        if self.list_id in texts:
            return EmptyState(*texts[self.list_id])
        if self.folder is not None:
            return EmptyState("folder_line", "Pasta vazia",
                              "Use “Adicionar PDFs”, acima, ou arraste PDFs para esta janela.")
        return EmptyState("docs", "Nenhum PDF", "Importe PDFs pela tela inicial ou arraste-os para esta janela.")


class FoldersScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.add_back()
        self.set_title("Pastas")
        self.finish_content()

    def refresh(self):
        app, lib = self.app, self.app.lib
        self.clear_after_title(1)
        none = WideTile("Sem pasta", "tray", "gray", str(len(lib.items_in_folder(""))))
        none.clicked.connect(lambda: app.push(DocumentGridScreen(app, folder="")))
        self.content.addWidget(none)
        if not lib.top_folders:
            self.content.addWidget(EmptyState("folderplus", "Nenhuma pasta",
                                              "Crie pastas para organizar seus PDFs, por cliente ou por processo."))
        else:
            g = FlowGrid()
            for f in lib.top_folders:
                g.add(make_folder_tile(app, f))
            self.content.addWidget(g)
        new = WideTile("Nova pasta", "folderplus", "blue")
        new.clicked.connect(lambda: new_folder_flow(app))
        self.content.addWidget(new)
        note = Label(f"As pastas são pastas comuns do Windows, em {lib.root}. "
                     "Clique com o botão direito numa pasta para renomear, excluir ou abrir no Explorador.",
                     13, 400, "secondary")
        note.setContentsMargins(4, 0, 4, 0)
        self.content.addWidget(note)
        self.finish_content()


# --- Documento --------------------------------------------------------------------

class DocHeader(QWidget):
    """Cartão do alto da tela do documento: miniatura grande e informações."""

    def __init__(self, app, item):
        super().__init__()
        self.app, self.item = app, item
        self.thumb = Thumb(self, app.hub.thumbs)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Ler")
        T.changed.connect(self.update)

    def hasHeightForWidth(self):
        return True

    def _lines(self, w):
        return wrap_lines(self.item.name, font(18, 700), w - 14 - 92 - 14 - 14, 4)

    def heightForWidth(self, w):
        text_h = 23 * len(self._lines(w)) + 6 + 3 * 21 + 22
        return 28 + max(124, text_h)

    def sizeHint(self):
        return QSize(400, self.heightForWidth(max(400, self.width())))

    def resizeEvent(self, e):
        self.setFixedHeight(self.heightForWidth(self.width()))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.app.read(self.item)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T.color("tile"))
        p.drawRoundedRect(QRectF(self.rect()), TILE_RADIUS, TILE_RADIUS)
        it = self.item
        self.thumb.paint(p, QRectF(14, 14, 92, 124), it.path, it.version, radius=6)
        x, w = 120, self.width() - 120 - 14
        y = 14
        p.setPen(T.color("text"))
        p.setFont(font(18, 700))
        for line in self._lines(self.width()):
            p.drawText(QRectF(x, y, w, 23), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 23
        y += 6
        info = " · ".join(s for s in (pages_text(it.page_count) if it.page_count else None, size_text(it.size)) if s)
        p.setPen(T.color("secondary"))
        p.setFont(font(13.5, 500))
        p.drawText(QRectF(x, y, w, 21), Qt.AlignLeft | Qt.AlignVCenter, info)
        y += 21
        paint_glyph(p, QRectF(x, y + 3, 15, 15), "folder_line", T.color("secondary"), 1.6)
        p.setFont(font(13.5))
        p.drawText(QRectF(x + 21, y, w - 21, 21), Qt.AlignLeft | Qt.AlignVCenter, elide(it.folder_name, font(13.5), w - 21))
        y += 21
        p.setFont(font(12.5))
        p.drawText(QRectF(x, y, w, 21), Qt.AlignLeft | Qt.AlignVCenter, f"Alterado em {date_text(it.modified)}")
        y += 24
        bx = x
        status = it.meta.text_status
        if status:
            bx += paint_badge(p, bx, y, TEXT_LABELS[status],
                              T.color("orange" if needs_ocr_status(status) else "blue")) + 4
        if it.meta.is_ocr_result:
            bx += paint_badge(p, bx, y, "OCR", T.color("green")) + 4
        if it.meta.locked:
            bx += paint_badge(p, bx, y, "Com senha", T.color("purple")) + 4
        if getattr(it.meta, "signed", 0):
            paint_badge(p, bx, y, "Assinado digitalmente", T.color("blue"))


class DocumentScreen(Screen):
    large_title = False

    def __init__(self, app, item_id: str):
        super().__init__(app)
        self.item_id = item_id
        self.add_back()
        self.big_title.hide()
        self.finish_content()

    def refresh(self):
        app, lib = self.app, self.app.lib
        item = lib.item(self.item_id)
        pos = self.scroll.verticalScrollBar().value()
        self.clear_after_title(1)
        if item is None:
            self.set_title("")
            self.content.addWidget(EmptyState("docs", "PDF não encontrado", "O arquivo foi movido ou apagado."))
            self.finish_content()
            return
        self.set_title(item.name)
        self.big_title.hide()
        self.content.addWidget(DocHeader(app, item))
        if getattr(item.meta, "signed", 0):
            import signing
            card = TileCard()
            row = QHBoxLayout()
            ic = Label("")
            ic.setPixmap(glyph_icon("signature", T.color("blue"), 20).pixmap(20, 20))
            ic.setFixedWidth(24)
            row.addWidget(ic, 0, Qt.AlignTop)
            who = signing.describe_signatures(item.path)
            lines = "; ".join(f"{s['name']}" + (f", em {s['when']}" if s["when"] else "") for s in who)
            row.addWidget(Label(("Assinado digitalmente" + (f" por {lines}" if lines else "") + ". O PDF não pode "
                                 "ser alterado sem invalidar a assinatura. Para conferir a validade, abra no "
                                 "Adobe Reader ou em validar.iti.gov.br."), 13.5), 1)
            card.lay.addLayout(row)
            self.content.addWidget(card)
        if item.meta.review_pages:
            card = TileCard()
            row = QHBoxLayout()
            ic = Label("")
            ic.setPixmap(glyph_icon("warning", T.color("orange"), 20).pixmap(20, 20))
            ic.setFixedWidth(24)
            row.addWidget(ic, 0, Qt.AlignTop)
            row.addWidget(Label(f"Revise as páginas {pdfops.format_ranges(item.meta.review_pages)}: o OCR teve baixa "
                                "confiança nelas. Confira nomes, datas, números e valores no original.", 13.5), 1)
            card.lay.addLayout(row)
            self.content.addWidget(card)

        pages = item.page_count or 0
        busy = app.jobs.is_busy(item.id)
        g = FlowGrid()

        def tile(title, icon, color, cb, count=None, subtitle=None, rounded=False, selected=False, dimmed=False):
            t = Tile(title, icon, color, count, subtitle, rounded_icon=rounded)
            t.selected = selected
            t.dimmed = dimmed
            t.clicked.connect(cb)
            g.add(t)
            return t

        has_ocr = lib.has_ocr_text(item)
        if item.meta.locked:
            tile("Ler", "book", "blue", lambda: app.read(item), subtitle="Pede a senha")
            tile("Remover senha", "lock_open", "purple", lambda: unprotect_dialog(app, item),
                 subtitle="Cria uma cópia sem senha", rounded=True)
            tile("Compartilhar", "share", "green", lambda: app.actions.share([item]),
                 subtitle="Copiar, exportar, Explorador")
            tile("Renomear", "pencil", "gray", lambda: app.actions.rename(item))
            tile("Mover", "folder", "brown", lambda: app.actions.move([item]), subtitle=item.folder_name)
            tile("Favorito" if item.meta.favorite else "Favoritar", "star", "yellow",
                 lambda: lib.set_favorite(item, not item.meta.favorite), rounded=True, selected=item.meta.favorite)
            self.content.addWidget(g)
            note = Label("Este PDF tem senha. Para fazer OCR, organizar ou dividir, crie antes uma cópia sem senha.",
                         13, 400, "secondary")
            note.setContentsMargins(4, 0, 4, 0)
            self.content.addWidget(note)
            d = WideTile("Excluir", "trash_fill", "red")
            d.clicked.connect(lambda: app.actions.delete([item], after=app.back))
            self.content.addWidget(d)
            self.finish_content()
            self.scroll.verticalScrollBar().setValue(pos)
            return
        tile("Ler", "book", "blue", lambda: app.read(item), subtitle="Páginas, modo leitor e busca")
        tile("Compartilhar", "share", "green", lambda: app.actions.share([item]),
             subtitle="Copiar, exportar, Explorador")
        tile("OCR", "textscan", "orange", lambda: self._ocr(item), count=self._ocr_count(item),
             subtitle=self._ocr_subtitle(item, busy), rounded=True)
        signed = bool(getattr(item.meta, "signed", 0))

        def edit(fn):
            return lambda: None if blocked_signed(app, lib.item(item.id) or item) else fn()

        tile("Organizar páginas", "grid", "purple", edit(lambda: app.organize(item)),
             count=str(pages) if pages else None, subtitle="Arrastar, girar, excluir", rounded=True, dimmed=signed)
        tile("Incluir páginas", "plusrect", "teal", edit(lambda: include_pages_dialog(app, item)),
             subtitle="De outro PDF ou do computador", rounded=True, dimmed=signed)
        tile("Remover páginas", "minusrect", "red", edit(lambda: app.push(PagePickerScreen(app, item.id, "remove"))),
             rounded=True, dimmed=signed)
        tile("Dividir em partes", "scissors", "pink", lambda: split_dialog(app, item))
        tile("Corrigir páginas curvas", "curve", "teal", edit(lambda: dewarp_dialog(app, item)),
             subtitle="Fotos de livros, papel ondulado", rounded=True, dimmed=signed)
        tile("Extrair páginas", "docplus", "indigo", lambda: app.push(PagePickerScreen(app, item.id, "extract")))
        tile("Cortar e girar", "crop", "indigo", edit(lambda: self._page_tool("crop", item)),
             subtitle="Margens e orientação", rounded=True, dimmed=signed)
        tile("Numerar páginas", "numbers", "indigo", edit(lambda: self._page_tool("number", item)),
             subtitle="Posição e formato", dimmed=signed)
        tile("Assinar digitalmente", "signature", "blue", lambda: self._sign(item),
             subtitle=("Assinado · assinar de novo" if signed else "Certificado A1 ou A3"), rounded=True)
        tile("Renomear", "pencil", "gray", lambda: app.actions.rename(item))
        tile("Mover", "folder", "brown", lambda: app.actions.move([item]), subtitle=item.folder_name)
        tile("Favorito" if item.meta.favorite else "Favoritar", "star", "yellow",
             lambda: lib.set_favorite(item, not item.meta.favorite), rounded=True, selected=item.meta.favorite)
        tile("Duplicar", "duplicate", "gray", lambda: self._duplicate(item), rounded=True)
        tile("Proteger com senha", "lock", "purple", edit(lambda: protect_dialog(app, item)),
             subtitle="Criptografia padrão de PDF", rounded=True, dimmed=signed)
        self.content.addWidget(g)
        if lib.can_undo(item):
            u = WideTile("Desfazer última alteração", "undo", "gray",
                         subtitle="Volta o arquivo para como estava antes da última mudança nas páginas")
            u.clicked.connect(lambda: self._undo(item))
            self.content.addWidget(u)
        d = WideTile("Excluir", "trash_fill", "red")
        d.clicked.connect(lambda: app.actions.delete([item], after=app.back))
        self.content.addWidget(d)
        self.finish_content()
        self.scroll.verticalScrollBar().setValue(pos)

    def _ocr_count(self, item):
        if self.app.lib.ocr_copy(item) is not None or item.meta.is_ocr_result:
            return None
        n = len(item.meta.ocr_pages or [])
        return str(n) if n else None

    def _ocr_subtitle(self, item, busy):
        if busy:
            return "Em andamento…"
        if item.meta.is_ocr_result:
            return "Já tem OCR"
        if self.app.lib.ocr_copy(item) is not None:
            return "Cópia com OCR criada"
        s = item.meta.text_status
        if s == "digital":
            return "Já tem texto"
        if s in ("scanned", "mixed"):
            n = len(item.meta.ocr_pages or [])
            return "1 página em imagem" if n == 1 else f"{n} páginas em imagem"
        if s == "empty":
            return "Sem páginas"
        return "Verificando…"

    def _ocr(self, item):
        self.app.actions.request_ocr(item)

    def _sign(self, item):
        import sign_ui
        result = sign_ui.sign_dialog(self.app, self.app.lib.item(item.id) or item)
        if result is not None and result.id != item.id:
            self.app.open_document(result.id)
        else:
            self.refresh()

    def _page_tool(self, key, item):
        import page_tools
        (page_tools.crop_dialog if key == "crop" else page_tools.number_dialog)(self.app, item)

    def _duplicate(self, item):
        self.app.actions.duplicate(item)

    def _undo(self, item):
        self.app.actions.undo(item)


# --- Dividir ------------------------------------------------------------------------

def split_dialog(app, item):
    total = item.page_count or 0
    if total < 2:
        app.toast("O PDF precisa ter pelo menos 2 páginas para ser dividido.")
        return
    ov = SheetOverlay(app, 440)
    sheet_header(ov, "Dividir em partes")
    card = TileCard()
    card.lay.setSpacing(10)
    card.lay.addWidget(Label(f"“{item.name}” tem {pages_text(total)}.", 15, 500))
    card.lay.addWidget(Label("Em quantas partes você quer dividir?", 17, 600))
    edit = QLineEdit()
    edit.setValidator(QIntValidator(1, 9999))
    edit.setAlignment(Qt.AlignCenter)
    edit.setFixedHeight(58)
    edit.setPlaceholderText("Número de partes")
    edit.setStyleSheet(f"QLineEdit {{ background: {T.hex('search')}; border: none; border-radius: 10px; "
                       f"font-size: 30px; font-weight: 700; color: {T.hex('text')}; }}")
    card.lay.addWidget(edit)
    info = Label("", 15, 600, "teal")
    preview = Label("", 13, 400, "secondary")
    card.lay.addWidget(info)
    card.lay.addWidget(preview)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    btn = PrimaryButton("Dividir", "pink")
    btn.setEnabled(False)
    wrap.addWidget(btn)
    note = Label("Os novos arquivos ficam na mesma pasta, com o nome do original e o número da parte. "
                 "O original não muda.", 13, 400, "secondary")
    wrap.addWidget(note)
    ov.lay.addLayout(wrap)
    ov.focus_widget = edit

    def update():
        t = edit.text().strip()
        if not t:
            info.setText("")
            preview.setText("")
            btn.setEnabled(False)
            return
        n = int(t)
        err = None
        if n < 2:
            err = "Escolha pelo menos 2 partes."
        elif n > total:
            err = f"O PDF tem {pages_text(total)}; não dá para dividir em {n} partes."
        if err:
            info.role = "red"
            info._apply()
            info.setText(err)
            preview.setText("")
            btn.setEnabled(False)
            return
        info.role = "teal"
        info._apply()
        plan = pdfops.SplitPlan(total, n)
        info.setText(plan.summary)
        ranges = plan.ranges
        shown = list(enumerate(ranges))
        if len(ranges) > 6:
            shown = shown[:3] + [None] + shown[-2:]
        lines = []
        for s in shown:
            if s is None:
                lines.append("…")
            else:
                i, (a, b) = s
                lines.append(f"{item.name} - Parte {i + 1}   ·   págs. {a}–{b}")
        preview.setText("\n".join(lines))
        btn.setEnabled(True)
        ov._place()

    edit.textChanged.connect(update)
    btn.clicked.connect(lambda: ov.done(int(edit.text())))
    edit.returnPressed.connect(lambda: btn.isEnabled() and ov.done(int(edit.text())))
    parts = ov.run()
    if not parts:
        return
    lib = app.lib
    created = []

    def run():
        names = {}

        def dest(n):
            p = lib.unique_path(item.folder, f"{item.name} - Parte {n}")
            names[n] = p
            return p
        pdfops.split(item.path, parts, dest)
        lib.reload()
        created.extend(names.values())

    if app.attempt(run, busy="Dividindo…"):
        folder = item.folder
        app.toast(f"{len(created)} arquivos criados em {item.folder_name}.", "Ver",
                  lambda: app.push(DocumentGridScreen(app, folder=folder)))


# --- Incluir páginas -------------------------------------------------------------

def include_pages_dialog(app, item, source=None):
    """Inclui páginas de outro PDF (ou do próprio) em `item`: todas, ou trechos como 5-15."""
    target_total = item.page_count or pdfops.page_count(item.path)
    if source is None:
        picked = choose_documents(app, f"Incluir páginas em “{item.name}”: de qual PDF?",
                                  allow_import=True, import_folder=item.folder)
        if not picked:
            return False
        source = picked[0]
    src_total = source.page_count or pdfops.page_count(source.path)
    ov = SheetOverlay(app, 460)
    sheet_header(ov, "Incluir páginas")
    card = TileCard()
    card.lay.setSpacing(8)
    same = source.id == item.id
    card.lay.addWidget(Label(f"De: “{source.name}”{' (este mesmo PDF)' if same else ''} · {pages_text(src_total)}",
                             14, 600))
    card.lay.addWidget(Label("Quais páginas? Deixe em branco para incluir todas, ou digite, por exemplo: "
                             "3, 5-15, 20-fim", 13, 400, "secondary"))
    field = QLineEdit()
    field.setPlaceholderText(f"Todas (1-{src_total})")
    card.lay.addWidget(field)
    info = Label("", 13, 500, "teal")
    card.lay.addWidget(info)
    card.lay.addSpacing(6)
    card.lay.addWidget(Label(f"Onde, em “{item.name}” ({pages_text(target_total)})?", 14, 600))
    where = QComboBox()
    where.addItem("No fim", "end")
    where.addItem("No início", "start")
    where.addItem("Depois da página…", "after")
    card.lay.addWidget(where)
    after = QSpinBox()
    after.setRange(1, max(1, target_total))
    after.setValue(max(1, target_total))
    after.setPrefix("Depois da página ")
    after.hide()
    card.lay.addWidget(after)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    btn = PrimaryButton("Incluir", "teal")
    wrap.addWidget(btn)
    wrap.addWidget(Label("Dá para voltar atrás com “Desfazer última alteração”, na tela do PDF.",
                         13, 400, "secondary"))
    ov.lay.addLayout(wrap)
    ov.focus_widget = field
    state = {"pages": list(range(1, src_total + 1))}

    def update():
        t = field.text().strip()
        try:
            state["pages"] = (list(range(1, src_total + 1)) if not t
                              else pdfops.parse_page_selection(t, src_total))
            info.role = "teal"
            info._apply()
            n = len(state["pages"])
            info.setText(f"{pages_text(n)} {'será incluída' if n == 1 else 'serão incluídas'}.")
            btn.setEnabled(n > 0)
        except ValueError as exc:
            state["pages"] = []
            info.role = "red"
            info._apply()
            info.setText(str(exc))
            btn.setEnabled(False)
        after.setVisible(where.currentData() == "after")
        btn.set_title(f"Incluir {pages_text(len(state['pages']))}" if state["pages"] else "Incluir")
        ov._place()

    field.textChanged.connect(update)
    where.currentIndexChanged.connect(lambda _i: update())
    btn.clicked.connect(lambda: ov.done(True))
    field.returnPressed.connect(lambda: btn.isEnabled() and ov.done(True))
    update()
    if not ov.run():
        return False
    mode = where.currentData()
    at = 1 if mode == "start" else (target_total + 1 if mode == "end" else after.value() + 1)
    pages = state["pages"]
    src_path = source.path
    if app.attempt(lambda: app.lib.modify(item, lambda p: pdfops.insert(p, src_path, pages, at)), busy="Incluindo…"):
        n = len(pages)
        app.toast(f"{pages_text(n)} incluída{'s' if n != 1 else ''} em {item.name}. Use “Desfazer” se precisar.")
        return True
    return False


# --- Corrigir páginas curvas ----------------------------------------------------------

class _Preview(QWidget):
    """Página antes e depois da correção, lado a lado."""

    def __init__(self):
        super().__init__()
        self.before = self.after = None
        self.message = "Preparando a prévia…"
        self.setMinimumHeight(340)
        T.changed.connect(self.update)

    def set_images(self, before, after, message=""):
        from PIL.ImageQt import ImageQt
        from PySide6.QtGui import QImage
        self.before = QImage(ImageQt(before)).copy() if before is not None else None
        self.after = QImage(ImageQt(after)).copy() if after is not None else None
        self.message = message
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        col = (w - 16) / 2
        for k, (img, label) in enumerate(((self.before, "Antes"), (self.after, "Depois"))):
            area = QRectF(k * (col + 16), 22, col, h - 22)
            p.setPen(T.color("secondary"))
            p.setFont(font(12.5, 600))
            p.drawText(QRectF(area.x(), 0, col, 18), Qt.AlignCenter, label)
            if img is None or img.isNull():
                p.setPen(T.color("secondary"))
                p.drawText(area, Qt.AlignCenter | Qt.TextWordWrap, self.message)
                continue
            s = min(area.width() / img.width(), area.height() / img.height())
            tw, th = img.width() * s, img.height() * s
            target = QRectF(area.x() + (area.width() - tw) / 2, area.y() + (area.height() - th) / 2, tw, th)
            p.drawImage(target, img)
            p.setPen(QPen(T.color("thumb_border"), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target)


def dewarp_dialog(app, item):
    """Corrigir páginas curvas (lombada, papel ondulado): prévia, escolha das páginas e cópia corrigida."""
    import dewarp
    if not dewarp.available():
        app.show_error("A correção de curvatura não está disponível nesta instalação (faltam os arquivos do modelo).")
        return
    total = item.page_count or pdfops.page_count(item.path)
    ov = SheetOverlay(app, 640)
    sheet_header(ov, "Corrigir páginas curvas")
    card = TileCard()
    card.lay.setSpacing(8)
    card.lay.addWidget(Label("Para fotos de livros e revistas (página curvada perto da lombada), papel ondulado ou "
                             "dobrado. O texto fica reto, o que também melhora o OCR. Em páginas que já estão retas "
                             "(scanner de mesa), não use: a margem pode ser cortada.", 13, 400, "secondary"))
    preview = _Preview()
    card.lay.addWidget(preview)
    nav = QHBoxLayout()
    prev_b, next_b = QPushButton("‹ Página anterior"), QPushButton("Próxima página ›")
    page_label = Label("", 13, 600, wrap=False)
    for b in (prev_b, next_b):
        b.setCursor(Qt.PointingHandCursor)
        b.setFont(font(13, 600))
        b.setStyleSheet(f"QPushButton {{ background: {T.hex('search')}; border: none; border-radius: 8px; "
                        f"padding: 6px 12px; color: {T.color('blue').name()}; }}"
                        f"QPushButton:disabled {{ color: {T.hex('placeholder')}; }}")
    nav.addWidget(prev_b)
    nav.addStretch(1)
    nav.addWidget(page_label)
    nav.addStretch(1)
    nav.addWidget(next_b)
    card.lay.addLayout(nav)
    card.lay.addWidget(Label("Quais páginas corrigir? Deixe em branco para todas, ou digite, por exemplo: 1, 3-5",
                             13, 400, "secondary"))
    field = QLineEdit()
    field.setPlaceholderText(f"Todas (1-{total})")
    card.lay.addWidget(field)
    info = Label("", 13, 500, "teal")
    card.lay.addWidget(info)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    btn = PrimaryButton("Corrigir e criar cópia", "teal")
    wrap.addWidget(btn)
    wrap.addWidget(Label("O original não muda: o resultado é um PDF novo, com “- corrigido” no nome. "
                         "As páginas corrigidas viram imagem; depois, o app oferece o OCR.", 13, 400, "secondary"))
    ov.lay.addLayout(wrap)
    state = {"page": 1, "pages": list(range(1, total + 1))}

    def show_page():
        n = state["page"]
        page_label.setText(f"Prévia da página {n} de {total}")
        prev_b.setEnabled(n > 1)
        next_b.setEnabled(n < total)
        preview.set_images(None, None, "Preparando a prévia…")
        QApplication.processEvents()
        try:
            pil, _size = dewarp.render_page(item.path, n - 1, dpi=110)
            preview.set_images(pil, dewarp.unwarp(pil))
        except Exception as exc:  # noqa: BLE001
            preview.set_images(None, None, f"Não foi possível gerar a prévia: {exc}")

    def update():
        t = field.text().strip()
        try:
            state["pages"] = list(range(1, total + 1)) if not t else pdfops.parse_page_selection(t, total)
            info.role = "teal"
            info._apply()
            n = len(state["pages"])
            info.setText("Todas as páginas serão corrigidas." if not t else
                         f"{pages_text(n)} {'será corrigida' if n == 1 else 'serão corrigidas'}.")
            btn.setEnabled(n > 0)
        except ValueError as exc:
            state["pages"] = []
            info.role = "red"
            info._apply()
            info.setText(str(exc))
            btn.setEnabled(False)

    prev_b.clicked.connect(lambda: (state.__setitem__("page", state["page"] - 1), show_page()))
    next_b.clicked.connect(lambda: (state.__setitem__("page", state["page"] + 1), show_page()))
    field.textChanged.connect(update)
    btn.clicked.connect(lambda: ov.done(True))
    update()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(50, show_page)
    if not ov.run():
        return
    pages = state["pages"]
    lib = app.lib
    tmp = lib.temp_path()
    try:
        fixed = app.run_with_progress("Corrigindo as páginas…",
                                      lambda progress: dewarp.dewarp_pdf(item.path, tmp, pages, progress))
        new = lib.adopt(tmp, f"{item.name} - corrigido", item.folder)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        app.show_error(f"Não foi possível corrigir: {exc}")
        return
    idx = alert(app, "Usar OCR agora?",
                f"{pages_text(fixed)} {'corrigida' if fixed == 1 else 'corrigidas'} em “{new.name}”. "
                "Com o texto reto, o OCR reconhece melhor. Fazer o OCR do PDF corrigido agora?",
                [("Mais tarde", "cancel"), ("Sim", "default")])
    if idx == 1:
        app.start_ocr(new)
    else:
        lib.set_pending_ocr(new, True)
    app.open_document(new.id)


# --- Senha do app ------------------------------------------------------------------------

def set_app_password(app, change=False):
    if change:
        idx, cur = alert(app, "Mudar a senha do Prumo", "Digite a senha atual.",
                         [("Cancelar", "cancel"), ("Continuar", "default")], text="", placeholder="Senha atual",
                         secret=True)
        if idx != 1:
            return
        if not app._verify_lock(cur):
            app.show_error("Senha atual incorreta.")
            return
    ov = SheetOverlay(app, 420)
    sheet_header(ov, "Nova senha do Prumo" if change else "Criar senha do Prumo")
    card = TileCard()
    pw1, pw2 = QLineEdit(), QLineEdit()
    for e, ph in ((pw1, "Senha"), (pw2, "Repita a senha")):
        e.setEchoMode(QLineEdit.Password)
        e.setPlaceholderText(ph)
        card.lay.addWidget(e)
    info = Label("", 13, 500, "red")
    card.lay.addWidget(info)
    card.lay.addWidget(Label("Guarde a senha num lugar seguro. Se esquecer, dá para desfazer o bloqueio pelos ajustes do "
                             "Windows (passo a passo no LEIA-ME); os PDFs não são afetados.", 13, 400, "secondary"))
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    btn = PrimaryButton("Salvar senha", "purple")
    btn.setEnabled(False)
    wrap.addWidget(btn)
    ov.lay.addLayout(wrap)
    ov.focus_widget = pw1

    def check():
        a, b = pw1.text(), pw2.text()
        info.setText("Use pelo menos 4 caracteres." if a and len(a) < 4 else
                     "As senhas não são iguais." if b and a != b else "")
        btn.setEnabled(len(a) >= 4 and a == b)
    pw1.textChanged.connect(check)
    pw2.textChanged.connect(check)
    btn.clicked.connect(lambda: ov.done(True))
    pw2.returnPressed.connect(lambda: btn.isEnabled() and ov.done(True))
    if ov.run():
        app.set_lock_password(pw1.text())
        app.toast("Senha salva. O Prumo vai pedir a senha ao abrir (e Ctrl+L bloqueia na hora).")
        app.current().refresh()


def remove_app_password(app):
    idx, cur = alert(app, "Remover a senha do Prumo", "Digite a senha atual para remover o bloqueio.",
                     [("Cancelar", "cancel"), ("Remover", "destructive")], text="", placeholder="Senha atual",
                     secret=True)
    if idx != 1:
        return
    if not app._verify_lock(cur):
        app.show_error("Senha incorreta.")
        return
    app.set_lock_password(None)
    app.toast("Senha removida: o Prumo abre sem pedir senha.")
    app.current().refresh()


# --- Senha no PDF ------------------------------------------------------------------------

def password_strength(pw: str) -> tuple[str, str]:
    """Força da senha (texto e cor), para orientar: letras maiúsculas e minúsculas, números e símbolos."""
    if not pw:
        return ("Dica: misture letras, números e símbolos (ex.: Caso2026!Ana).", "secondary")
    kinds = sum(bool(f(pw)) for f in (lambda s: any(c.islower() for c in s), lambda s: any(c.isupper() for c in s),
                                       lambda s: any(c.isdigit() for c in s), lambda s: any(not c.isalnum() for c in s)))
    score = kinds + (len(pw) >= 8) + (len(pw) >= 12)
    if len(pw) < 6 or score <= 2:
        return ("Senha fraca: use 8 ou mais caracteres, com letras e números.", "red")
    if score <= 4:
        return ("Senha média. Fica mais forte com mais caracteres, números e símbolos.", "orange")
    return ("Senha forte.", "green")


def protect_dialog(app, item):
    """Cria uma cópia do PDF com senha (AES-256, o padrão de PDF), que abre em qualquer leitor com a senha."""
    ov = SheetOverlay(app, 460)
    sheet_header(ov, "Proteger com senha")
    card = TileCard()
    card.lay.setSpacing(8)
    card.lay.addWidget(Label(f"“{item.name}”", 15, 600))
    card.lay.addWidget(Label("A cópia protegida só abre com a senha, em qualquer leitor de PDF (Adobe, Edge, Chrome, "
                             "iPhone). Usa a criptografia padrão de PDF (AES-256). A senha pode ter letras, números e "
                             "símbolos; maiúsculas e minúsculas fazem diferença.", 13, 400, "secondary"))
    pw1, pw2 = QLineEdit(), QLineEdit()
    for e, ph in ((pw1, "Senha (letras, números e símbolos)"), (pw2, "Repita a senha")):
        e.setEchoMode(QLineEdit.Password)
        e.setPlaceholderText(ph)
        card.lay.addWidget(e)
    show = QCheckBox("Mostrar a senha")
    show.toggled.connect(lambda on: [e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password) for e in (pw1, pw2)])
    card.lay.addWidget(show)
    strength = Label("", 13, 600, "secondary")
    card.lay.addWidget(strength)
    info = Label("", 13, 500, "red")
    card.lay.addWidget(info)
    trash = QCheckBox("Mandar o original (sem senha) para a Lixeira")
    trash.setChecked(True)
    card.lay.addWidget(trash)
    warn = Label("Importante: se você esquecer a senha, não há como abrir o PDF, nem pelo Prumo. Guarde a senha "
                 "num lugar seguro. Evite acentos e “ç” na senha: alguns leitores de PDF não os entendem.",
                 13, 500, "orange")
    card.lay.addWidget(warn)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    btn = PrimaryButton("Proteger", "purple")
    btn.setEnabled(False)
    wrap.addWidget(btn)
    ov.lay.addLayout(wrap)
    ov.focus_widget = pw1

    def check():
        a, b = pw1.text(), pw2.text()
        msg = ""
        if a and len(a) < 4:
            msg = "Use pelo menos 4 caracteres."
        elif b and a != b:
            msg = "As senhas não são iguais."
        info.setText(msg)
        label, color = password_strength(a)
        strength.role = color
        strength._apply()
        strength.setText(label)
        btn.setEnabled(bool(a) and a == b and len(a) >= 4)
    pw1.textChanged.connect(check)
    pw2.textChanged.connect(check)
    btn.clicked.connect(lambda: ov.done(True))
    pw2.returnPressed.connect(lambda: btn.isEnabled() and ov.done(True))
    if not ov.run():
        return
    password = pw1.text()
    lib = app.lib
    tmp = lib.temp_path()
    try:
        pdfops.protect(item.path, tmp, password)
        new = lib.adopt(tmp, f"{item.name} - protegido", item.folder)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        app.show_error(f"Não foi possível proteger: {exc}")
        return
    if trash.isChecked():
        app.attempt(lambda: lib.delete([lib.item(item.id)] if lib.item(item.id) else []))
        app.back()
    app.toast(f"PDF protegido: {new.name}", "Abrir", lambda: app.open_document(new.id))


def unprotect_dialog(app, item):
    """Cria uma cópia sem senha (com a senha atual), para fazer OCR, organizar páginas etc."""
    pw = app.ask_pdf_password(item, "Remover a senha")
    if pw is None:
        return
    lib = app.lib
    tmp = lib.temp_path()
    try:
        pdfops.unprotect(item.path, tmp, pw)
        name = item.name[:-len(" - protegido")] if item.name.endswith(" - protegido") else f"{item.name} - sem senha"
        new = lib.adopt(tmp, name, item.folder)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        app.show_error(f"Não foi possível remover a senha: {exc}")
        return
    app.toast(f"Cópia sem senha: {new.name}", "Abrir", lambda: app.open_document(new.id))


# --- Escolher páginas (remover, extrair) --------------------------------------

class PageTile(QAbstractButton):
    double_clicked = Signal()

    def __init__(self, thumbs, item, index):
        super().__init__()
        self.item, self.index = item, index
        self.thumb = Thumb(self, thumbs)
        self.checked_ = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setToolTip("Clique para marcar; dois cliques mostram a página grande")

    def mouseDoubleClickEvent(self, e):
        # o segundo clique desfaz a marcação do primeiro; a página abre grande
        super().mouseDoubleClickEvent(e)
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int((w - 16) * 1.38) + 34

    def sizeHint(self):
        return QSize(130, self.heightForWidth(130))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(8, 8, w - 16, h - 42)
        if self.checked_ or self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.color("blue")) if self.checked_ else T.color("tile"))
            if self.checked_:
                c = QColor(T.color("blue"))
                c.setAlpha(40)
                p.setBrush(c)
            p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        self.thumb.paint(p, r, self.item.path, self.item.version, self.index, 4)
        if self.checked_:
            p.setPen(QPen(T.color("blue"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 5, 5)
            cr = QRectF(r.right() - 30, r.bottom() - 30, 24, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(T.color("blue"))
            p.drawEllipse(cr)
            paint_glyph(p, cr.adjusted(4, 4, -4, -4), "check", QColor("white"), 3)
        p.setPen(T.color("blue") if self.checked_ else T.color("secondary"))
        p.setFont(font(13, 600))
        p.drawText(QRectF(0, h - 32, w, 26), Qt.AlignCenter, str(self.index + 1))


class PagePickerScreen(Screen):
    """Escolha de páginas por miniatura ou digitando (1, 3-5, 10-fim)."""

    large_title = False

    def __init__(self, app, item_id: str, mode: str):
        super().__init__(app)
        self.item_id, self.mode = item_id, mode
        self.item = app.lib.item(item_id)
        self.add_back()
        self.big_title.hide()
        self.total = self.item.page_count or pdfops.page_count(self.item.path)
        self.selected: set[int] = set()
        self.set_title("Remover páginas" if mode == "remove" else "Extrair páginas")
        self.big_title.hide()

        card = TileCard()
        card.lay.addWidget(Label(f"“{self.item.name}” · {pages_text(self.total)}", 14, 600))
        card.lay.addWidget(Label("Clique nas páginas, arraste o mouse sobre várias ou digite, por exemplo: 1, 3-5, 10-fim. "
                                 "Dois cliques mostram a página grande.", 13, 400, "secondary"))
        self.field = QLineEdit()
        self.field.setPlaceholderText("Páginas")
        card.lay.addWidget(self.field)
        self.error = Label("", 12.5, 500, "red")
        self.error.hide()
        card.lay.addWidget(self.error)
        row = QHBoxLayout()
        for text, fn in (("Todas", self._all), ("Nenhuma", self._none), ("Inverter", self._invert)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(font(14, 600))
            b.setStyleSheet(f"QPushButton {{ background: {T.hex('search')}; border: none; border-radius: 8px; "
                            f"padding: 7px 14px; color: {T.color('blue').name()}; }}")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        card.lay.addLayout(row)
        self.content.addWidget(card)
        self.grid = FlowGrid(min_col=118, max_cols=12)
        self.tiles = []
        for i in range(self.total):
            t = PageTile(app.hub.thumbs, self.item, i)
            t.clicked.connect(lambda _c=False, n=i + 1: self._toggle(n))
            t.double_clicked.connect(lambda i=i: self.preview(i))
            self.tiles.append(t)
            self.grid.add(t)
        self.content.addWidget(self.grid)
        self.finish_content()
        from rubberband import RubberBand, rect_in
        self._band_base: set[int] = set()
        self.band = RubberBand(self.body, self.scroll,
                               lambda: [(t.index + 1, rect_in(self.body, t)) for t in self.tiles],
                               self._band_select,
                               lambda add: setattr(self, "_band_base", set(self.selected) if add else set()))
        self.action = PrimaryButton("", "red" if mode == "remove" else "indigo")
        self.action.setParent(self)
        self.action.clicked.connect(self._confirm)
        self._typing = False
        self.field.textEdited.connect(self._typed)
        self._sync()

    def refresh(self):
        pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = min(520, self.width() - 2 * MARGIN)
        self.action.setFixedWidth(w)
        self.action.move((self.width() - w) // 2, self.height() - 50 - 16)
        self.action.raise_()

    def _toggle(self, n):
        self.selected.symmetric_difference_update({n})
        self._sync()

    def _band_select(self, keys: set, _additive: bool, _final: bool):
        self.selected = self._band_base | keys
        self._sync()

    def preview(self, i: int):
        from page_view import PagePreviewOverlay
        n = self.total
        verb = "remover" if self.mode == "remove" else "extrair"

        def label(k):
            mark = f" · marcada para {verb}" if (k + 1) in self.selected else ""
            return f"Página {k + 1} de {n}{mark}"
        ov = PagePreviewOverlay(self.app, self.item.path, [(k, 0) for k in range(n)], i, label)
        self._preview = ov
        ov.open()

    def _all(self):
        self.selected = set(range(1, self.total + 1))
        self._sync()

    def _none(self):
        self.selected = set()
        self._sync()

    def _invert(self):
        self.selected = set(range(1, self.total + 1)) - self.selected
        self._sync()

    def _typed(self, text):
        if not text.strip():
            self.selected = set()
            self.error.hide()
        else:
            try:
                self.selected = set(pdfops.parse_page_selection(text, self.total))
                self.error.hide()
            except ValueError as exc:
                self.error.setText(str(exc))
                self.error.show()
        self._typing = True
        self._sync()
        self._typing = False

    def _sync(self):
        for t in self.tiles:
            t.checked_ = (t.index + 1) in self.selected
            t.update()
        if not self._typing:
            self.field.setText(pdfops.format_ranges(sorted(self.selected)))
            self.error.hide()
        n = len(self.selected)
        verb = "Remover" if self.mode == "remove" else "Extrair"
        self.action.set_title(f"{verb} {pages_text(n)}" if n else f"{verb} páginas")
        ok = n > 0 and not (self.mode == "remove" and n >= self.total)
        self.action.setEnabled(ok)

    def _confirm(self):
        pages = sorted(self.selected)
        app, lib, item = self.app, self.app.lib, self.item
        if self.mode == "remove" and blocked_signed(app, item):
            return
        if self.mode == "remove":
            idx = alert(app, f"Remover {pages_text(len(pages))}?",
                        "Dá para voltar atrás com “Desfazer última alteração”, na tela do PDF.",
                        [("Cancelar", "cancel"), ("Remover", "destructive")])
            if idx != 1:
                return
            if app.attempt(lambda: lib.modify(item, lambda p: pdfops.remove(p, pages)), busy="Removendo…"):
                app.back()
                n = len(pages)
                app.toast(f"{pages_text(n)} removida{'s' if n != 1 else ''}. Use “Desfazer” se precisar.")
        else:
            label = pdfops.format_ranges(pages)
            name = f"{item.name} - págs. {label}" if len(label) <= 40 else f"{item.name} - {len(pages)} páginas"
            out = {}

            def run():
                dest = lib.unique_path(item.folder, name)
                pdfops.extract(item.path, dest, pages)
                out["item"] = lib.register(dest)
            if app.attempt(run, busy="Extraindo…"):
                app.back()
                new = out.get("item")
                if new:
                    app.toast(f"Novo PDF: {new.name}", "Abrir", lambda: app.open_document(new.id))


# --- Combinar ---------------------------------------------------------------------

class _MergeRow(QWidget):
    def __init__(self, screen, item, index, count):
        super().__init__()
        self.screen, self.item = screen, item
        self.thumb = Thumb(self, screen.app.hub.thumbs)
        self.setFixedHeight(64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(56, 0, 8, 0)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = Label(item.name, 15, 600, wrap=False)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addStretch(1)
        col.addWidget(name)
        col.addWidget(Label(pages_text(item.page_count) if item.page_count else "…", 12, 400, "secondary"))
        col.addStretch(1)
        lay.addLayout(col, 1)
        for glyph, tip, delta, enabled in (("back", "Subir", -1, index > 0), ("back", "Descer", 1, index < count - 1)):
            b = QPushButton()
            b.setToolTip(tip)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(enabled)
            ic = glyph_icon("back", T.color("blue") if enabled else T.color("placeholder"), 18)
            pm = ic.pixmap(18, 18)
            pm = pm.transformed(QTransform().rotate(90 if delta < 0 else -90))
            b.setIcon(pm)
            b.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 17px; }"
                            f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}")
            b.clicked.connect(lambda _c=False, d=delta: screen.move_item(item.id, d))
            lay.addWidget(b)
        rm = QPushButton()
        rm.setToolTip("Tirar da lista")
        rm.setFixedSize(34, 34)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setIcon(glyph_icon("x", T.color("red"), 18))
        rm.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 17px; }"
                         f"QPushButton:hover {{ background: {T.hex('tile_hover')}; }}")
        rm.clicked.connect(lambda: screen.remove_item(item.id))
        lay.addWidget(rm)

    def paintEvent(self, _):
        p = QPainter(self)
        self.thumb.paint(p, QRectF(14, 12, 30, 40), self.item.path, self.item.version)


class MergeScreen(Screen):
    large_title = False

    def __init__(self, app, preselection=None):
        super().__init__(app)
        self.add_back()
        self.big_title.hide()
        self.set_title("Combinar PDFs")
        self.big_title.hide()
        self.chosen: list[str] = list(preselection or [])
        intro = TileCard()
        intro.lay.addWidget(Label("Escolha os PDFs e use as setas para definir a ordem. "
                                  "O resultado é um PDF novo; os originais não mudam.", 14))
        self.content.addWidget(intro)
        self.header = SectionTitle("PDFs")
        self.content.addWidget(self.header)
        self.list_card = TileCard(padding=0)
        self.list_card.lay.setSpacing(0)
        self.content.addWidget(self.list_card)
        self.content.addWidget(SectionTitle("Nome do novo PDF"))
        self.name = QLineEdit("PDF combinado")
        self.content.addWidget(self.name)
        self.button = PrimaryButton("Combinar", "purple")
        self.button.clicked.connect(self._merge)
        self.content.addWidget(self.button)
        self.finish_content()

    def items(self):
        return [i for i in (self.app.lib.item(x) for x in self.chosen) if i]

    def refresh(self):
        items = self.items()
        self.chosen = [i.id for i in items]
        lay = self.list_card.lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for i, it in enumerate(items):
            lay.addWidget(_MergeRow(self, it, i, len(items)))
        add = QPushButton("  " + ("Adicionar mais PDFs" if items else "Escolher PDFs"))
        add.setIcon(glyph_icon("plus", T.color("blue"), 18))
        add.setCursor(Qt.PointingHandCursor)
        add.setFont(font(16, 600))
        add.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {T.color('blue').name()};"
                          " text-align: left; padding: 16px 16px; }")
        add.clicked.connect(self._choose)
        lay.addWidget(add)
        total = sum(i.page_count or 0 for i in items)
        self.header.setText(f"{len(items)} PDFS · {pages_text(total).upper()}" if items else "PDFS")
        self.button.setEnabled(len(items) >= 2)

    def move_item(self, id, delta):
        i = self.chosen.index(id)
        j = i + delta
        if 0 <= j < len(self.chosen):
            self.chosen[i], self.chosen[j] = self.chosen[j], self.chosen[i]
            self.refresh()

    def remove_item(self, id):
        self.chosen.remove(id)
        self.refresh()

    def _choose(self):
        picked = choose_documents(self.app, "Escolher PDFs", multiple=True, excluding=set(self.chosen),
                                  allow_import=True)
        if picked:
            self.chosen.extend(i.id for i in picked)
            self.refresh()

    def _merge(self):
        items = self.items()
        if len(items) < 2:
            return
        name = self.name.text().strip() or "PDF combinado"
        folder = items[0].folder
        out = {}

        def run():
            import core
            dest = self.app.lib.unique_path(folder, name)
            core.merge_pdfs([i.path for i in items], dest, bookmarks=True)
            out["item"] = self.app.lib.register(dest)
        if self.app.attempt(run, busy="Combinando…"):
            self.chosen = []
            self.refresh()
            new = out.get("item")
            if new:
                self.app.toast(f"PDF combinado: {new.name}", "Abrir", lambda: self.app.open_document(new.id))


def _origins(app, exclude_folder=None):
    """Origens do seletor: as abas da tela inicial e as pastas."""
    out = [("Todos os PDFs", ("list", "all")), ("Recentes", ("list", "recent")),
           ("Favoritos", ("list", "favorites")), ("Com OCR", ("list", "ocr")),
           ("Aguardando OCR", ("list", "pending"))]
    if exclude_folder != "":
        out.append(("Sem pasta", ("folder", "")))
    for f in app.lib.folders:
        if f.path != exclude_folder:
            out.append(("    " * f.path.count("/") + "Pasta " + f.name, ("folder", f.path)))
    return out


def choose_documents(app, title, multiple=False, excluding=frozenset(), allow_import=False,
                     import_folder: str = "", exclude_folder: str | None = None, only=None):
    """
    Escolha de PDFs: da biblioteca (filtrando por aba ou pasta) ou, com `allow_import`,
    do computador, que entram na biblioteca em `import_folder`. Devolve a lista ou None.
    """
    ov = SheetOverlay(app, 680)
    ok = sheet_header(ov, title, confirm="Adicionar" if multiple else None)
    selected: list[str] = []
    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 0, 16, 16)
    wrap.setSpacing(10)
    if allow_import:
        comp = WideTile("Do computador…", "computer", "blue",
                        subtitle="PDF, foto, Word, Excel… (o que não for PDF é convertido na hora)")
        comp.clicked.connect(lambda: ov.done("import"))
        wrap.addWidget(comp)
        wrap.addWidget(SectionTitle("Ou escolha no Prumo"))
    row = QHBoxLayout()
    row.setSpacing(8)
    search = SearchField("Buscar PDF")
    row.addWidget(search, 1)
    origin = QComboBox()
    origin.setMinimumWidth(190)
    origin.setFixedHeight(40)
    for label, data in _origins(app, exclude_folder):
        origin.addItem(label, data)
    row.addWidget(origin)
    wrap.addLayout(row)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setMinimumHeight(min(520, int(app.height() * 0.62) - (90 if allow_import else 0)))
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    col = QVBoxLayout(body)
    col.setContentsMargins(0, 0, 0, 0)
    scroll.setWidget(body)
    wrap.addWidget(scroll)
    ov.lay.addLayout(wrap)
    tiles = []

    def update_ok():
        if ok is not None:
            ok.setText(f"Adicionar ({len(selected)})" if selected else "Adicionar")
            ok.setEnabled(bool(selected))

    def pool():
        kind, key = origin.currentData()
        lib = app.lib
        base = lib.items_for(key) if kind == "list" else lib.items_in_folder(key)
        out = [i for i in base if i.id not in excluding]
        if exclude_folder is not None:
            out = [i for i in out if i.folder != exclude_folder]
        if only is not None:
            out = [i for i in out if only(i)]
        return out

    def build():
        while col.count():
            w = col.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        tiles.clear()
        items = pool()
        q = search.text().strip()
        docs = app.lib.search(q, items) if q else sorted(items, key=lambda i: -i.modified)
        if not docs:
            msg = ("Use “Do computador…” para escolher um arquivo do Windows." if allow_import
                   else "Não há outros PDFs aqui.")
            col.addWidget(EmptyState("docs", "Nenhum PDF aqui", msg))
        else:
            g = FlowGrid(min_col=180, max_cols=3)
            for it in docs:
                if multiple:
                    t = make_doc_tile(app, it, show_folder=True, menu=False, on_click=lambda it=it: toggle(it))
                    t.set_selection(it.id in selected)
                else:
                    t = make_doc_tile(app, it, show_folder=True, menu=False, on_click=lambda it=it: ov.done([it]))
                tiles.append(t)
                g.add(t)
            col.addWidget(g)
        col.addStretch(1)

    def toggle(it):
        if it.id in selected:
            selected.remove(it.id)
        else:
            selected.append(it.id)
        for t in tiles:
            if t.item.id == it.id:
                t.set_selection(it.id in selected)
        update_ok()

    if multiple:
        from rubberband import RubberBand, rect_in
        band_base: list[str] = []

        def band_start(additive):
            band_base[:] = list(selected) if additive else []

        def band_select(keys, _additive, _final):
            order = [t.item.id for t in tiles]
            selected[:] = band_base + [k for k in order if k in keys and k not in band_base]
            for t in tiles:
                t.set_selection(t.item.id in selected)
            update_ok()
        ov._band = RubberBand(body, scroll, lambda: [(t.item.id, rect_in(body, t)) for t in tiles if t.isVisible()],
                              band_select, band_start)

    search.debounced.connect(lambda _t: build())
    origin.currentIndexChanged.connect(lambda _i: build())
    if ok is not None:
        ok.clicked.connect(lambda: ov.done([app.lib.item(x) for x in selected if app.lib.item(x)]))
    build()
    update_ok()
    ov.focus_widget = search.edit
    res = ov.run()
    if res == "import":
        return app.pick_and_import(import_folder, multiple) or None
    return res


# --- Ajustes ----------------------------------------------------------------------

def open_cloud_signin(name: str) -> None:
    """Abre o aplicativo da nuvem (para entrar na conta) ou a página oficial para instalá-lo."""
    import subprocess

    import backup
    if name == "OneDrive":
        exe = backup.onedrive_exe()
        if exe is not None:
            try:
                subprocess.Popen([str(exe)], close_fds=True)
                return
            except OSError:
                pass
    info = backup.cloud_app(name)
    if info:
        QDesktopServices.openUrl(QUrl(info["url"]))


def cloud_dialog(app):
    """Escolher a nuvem do backup e da sincronização (iCloud Drive, Google Drive, OneDrive, Dropbox)."""
    import backup
    while True:
        clouds = backup.cloud_folders()
        found: dict[str, Path] = {}
        for name, folder in clouds:
            found.setdefault(name, folder)
        current = backup.cloud_of(app.lib.root, clouds)

        ov = SheetOverlay(app, 560, max_height=760)
        sheet_header(ov, "Escolher a nuvem", cancel="Fechar")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 4, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(Label(
            "Os PDFs ficam numa pasta “Prumo PDF” dentro da nuvem escolhida: é o backup e também a "
            "sincronização. No outro aparelho (iPhone ou outro computador), escolha a mesma nuvem no Prumo e os "
            "PDFs, as pastas e os favoritos aparecem lá.", 13.5))
        lay.addWidget(Label(
            "1. Toque em “Entrar ou instalar” e entre na sua conta pelo aplicativo da nuvem.  "
            "2. Volte aqui e toque em “Procurar de novo”.  3. Toque em “Usar”.", 13, 400, "secondary"))
        for info in backup.CLOUD_APPS:
            name = info["name"]
            card = TileCard()
            card.lay.setSpacing(6)
            top = QHBoxLayout()
            top.addWidget(Label(name, 16, 600), 1)
            if name == current:
                state = Label("Em uso", 13, 600, "green", wrap=False)
            elif name in found:
                state = Label("Conectado neste computador", 13, 600, "green", wrap=False)
            else:
                state = Label("Não encontrado", 13, 600, "secondary", wrap=False)
            top.addWidget(state)
            card.lay.addLayout(top)
            if name in found:
                card.lay.addWidget(Label(str(found[name]), 12, 400, "secondary"))
            else:
                card.lay.addWidget(Label(f"Instale o {info['app']} e entre na sua conta.", 13, 400, "secondary"))
            card.lay.addWidget(Label(info["iphone"], 13, 400, "secondary"))
            row = QHBoxLayout()
            signin = QPushButton("Entrar ou instalar…")
            signin.setCursor(Qt.PointingHandCursor)
            signin.setFont(font(14, 600))
            signin.setStyleSheet(f"QPushButton {{ background: {T.hex('search')}; border: none; border-radius: 8px; "
                                 f"padding: 8px 14px; color: {T.color('blue').name()}; }}")
            signin.clicked.connect(lambda _c=False, n=name: open_cloud_signin(n))
            row.addWidget(signin)
            if name in found and name != current:
                use = QPushButton(f"Usar o {name}")
                use.setCursor(Qt.PointingHandCursor)
                use.setFont(font(14, 600))
                use.setStyleSheet(f"QPushButton {{ background: {T.color('blue').name()}; border: none; "
                                  "border-radius: 8px; padding: 8px 14px; color: white; }")
                use.clicked.connect(lambda _c=False, n=name: ov.done(("use", n)))
                row.addWidget(use)
            row.addStretch(1)
            card.lay.addLayout(row)
            lay.addWidget(card)
        row = QHBoxLayout()
        again = PrimaryButton("Procurar de novo", "blue")
        again.clicked.connect(lambda: ov.done(("again", None)))
        row.addWidget(again)
        other = PrimaryButton("Outra pasta…", "gray")
        other.clicked.connect(lambda: ov.done(("other", None)))
        row.addWidget(other)
        lay.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget "
                             "{ background: transparent; }")
        scroll.setWidget(body)
        scroll.setMinimumHeight(min(660, body.sizeHint().height() + 8))
        ov.lay.addWidget(scroll)
        result = ov.run()
        if not result:
            return
        kind, name = result
        if kind == "again":
            continue
        if kind == "other":
            app.change_library()
        elif kind == "use":
            app.change_library_to(found[name] / "Prumo PDF")
        app.current().refresh()
        return


class SettingsScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.add_back()
        self.set_title("Ajustes")
        self.finish_content()

    def refresh(self):
        app, lib = self.app, self.app.lib
        self.clear_after_title(1)
        c = self.content
        import backup
        clouds = backup.cloud_folders()
        cloud = backup.cloud_of(lib.root, clouds)

        def small_button(text, fn, color="blue"):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(font(14, 600))
            btn.setStyleSheet(f"QPushButton {{ background: {T.hex('search')}; border: none; border-radius: 8px; "
                              f"padding: 8px 14px; color: {T.color(color).name()}; }}")
            btn.clicked.connect(fn)
            return btn

        def status_row(glyph, color, title, text):
            row = QHBoxLayout()
            ic = Label("")
            ic.setPixmap(glyph_icon(glyph, T.color(color), 22).pixmap(22, 22))
            ic.setFixedWidth(28)
            row.addWidget(ic, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(Label(title, 16, 600))
            col.addWidget(Label(text, 13, 400, "secondary"))
            row.addLayout(col, 1)
            return row

        c.addWidget(SectionTitle("Backup e sincronização"))
        card = TileCard()
        if cloud:
            info = backup.cloud_app(cloud) or {}
            card.lay.addLayout(status_row("check", "green", f"Backup e sincronização no {cloud}",
                                          f"Os PDFs ficam numa pasta do {cloud}: tudo o que você salva aqui vai para a "
                                          "nuvem e aparece nos outros aparelhos com o Prumo usando a mesma pasta. "
                                          + info.get("iphone", "")))
        else:
            card.lay.addLayout(status_row("warning", "orange", "Só neste computador",
                                          "Sem backup e sem sincronização: se o computador estragar ou for perdido, "
                                          "os PDFs vão junto. Escolha uma nuvem para guardar e sincronizar os PDFs."))
        path = Label(str(lib.root), 13, 400, "secondary")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.lay.addWidget(path)
        choose = PrimaryButton("Trocar de nuvem…" if cloud else "Escolher nuvem…", "blue")
        choose.clicked.connect(lambda: cloud_dialog(app))
        card.lay.addWidget(choose)
        row = QHBoxLayout()
        row.addWidget(small_button("Abrir no Explorador", lambda: app.reveal(lib.root)))
        row.addWidget(small_button("Usar outra pasta…", app.change_library))
        row.addStretch(1)
        card.lay.addLayout(row)
        card.lay.addWidget(Label(
            "Os PDFs ficam como arquivos comuns nessa pasta: dá para abrir, copiar e editar com qualquer programa. "
            "Os favoritos e a ligação com as cópias de OCR vão junto, na subpasta oculta “.prumo”, e também "
            "sincronizam com os outros aparelhos.", 13, 400, "secondary"))
        c.addWidget(card)

        c.addWidget(SectionTitle("Cópia de segurança"))
        card = TileCard()
        last = app.setting("last_backup", None)
        try:
            last_text = f"Última cópia: {date_text(float(last))}." if last else "Nenhuma cópia feita ainda."
        except (TypeError, ValueError):
            last_text = "Nenhuma cópia feita ainda."
        card.lay.addWidget(Label("Uma cópia completa (PDFs, pastas e favoritos) numa pasta comum, por exemplo num "
                                 "pendrive ou HD externo. " + last_text, 13.5))
        row = QHBoxLayout()
        row.addWidget(small_button("Fazer uma cópia agora…", app.backup_now))
        row.addWidget(small_button("Restaurar de uma cópia…", app.restore_from))
        row.addStretch(1)
        card.lay.addLayout(row)
        c.addWidget(card)

        c.addWidget(SectionTitle("Segurança"))
        card = TileCard()
        import security
        on = app.lock_enabled
        card.lay.addLayout(status_row("lock" if on else "lock_open", "purple" if on else "secondary",
                                      "Senha para abrir o Prumo: ligada" if on else "Senha para abrir o Prumo: desligada",
                                      "O Prumo pede a senha ao abrir e depois de um tempo sem uso (Ctrl+L bloqueia na hora)."
                                      if on else "Qualquer pessoa com acesso a este computador abre o Prumo."))
        row = QHBoxLayout()
        if on:
            row.addWidget(small_button("Mudar senha…", lambda: set_app_password(app, change=True)))
            row.addWidget(small_button("Remover senha…", lambda: remove_app_password(app), "red"))
        else:
            row.addWidget(small_button("Criar senha…", lambda: set_app_password(app)))
        row.addStretch(1)
        card.lay.addLayout(row)
        if on:
            idle = QComboBox()
            for minutes, label in security.IDLE_OPTIONS:
                idle.addItem(label, minutes)
            idle.setCurrentIndex(max(0, idle.findData(int(app.setting("app_lock_idle", 10) or 0))))
            idle.currentIndexChanged.connect(lambda _i: (app.set_setting("app_lock_idle", idle.currentData()),
                                                         app._restart_idle()))
            card.lay.addWidget(idle)
        card.lay.addWidget(Label(
            "A senha bloqueia a tela do Prumo. Os PDFs continuam como arquivos comuns na pasta da biblioteca: para "
            "proteger um arquivo em si (por exemplo, antes de enviar), use “Proteger com senha” na tela do PDF, que "
            "usa a criptografia padrão de PDF (AES-256) e abre em qualquer leitor com a senha.", 13, 400, "secondary"))
        c.addWidget(card)

        import sign_ui
        sign_ui.settings_section(app, c, SectionTitle, small_button)

        c.addWidget(SectionTitle("Windows"))
        card = TileCard()
        card.lay.addWidget(Label(
            "O Prumo aparece em “Abrir com” nos PDFs e, no botão direito de fotos e arquivos do Word, Excel e "
            "PowerPoint, em “Converter em PDF com o Prumo”. Para abrir todo PDF no Prumo com dois cliques, "
            "escolha o Prumo PDF como aplicativo padrão para .pdf nas configurações do Windows.", 13.5))
        row = QHBoxLayout()
        row.addWidget(small_button("Aplicativos padrão do Windows…",
                                   lambda: QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))))
        row.addStretch(1)
        card.lay.addLayout(row)
        c.addWidget(card)

        c.addWidget(SectionTitle("OCR"))
        card = TileCard()
        card.lay.addWidget(Label("Idioma dos documentos", 16, 600))
        lang = QComboBox()
        lang.addItem("Português", "por")
        lang.addItem("Português + Inglês", "por+eng")
        lang.setCurrentIndex(max(0, lang.findData(app.setting("ocr_language", "por"))))
        lang.currentIndexChanged.connect(lambda _i: app.set_setting("ocr_language", lang.currentData()))
        card.lay.addWidget(lang)
        prec = QCheckBox("Precisão máxima (bem mais lento)")
        prec.setChecked(bool(app.setting("max_precision", False)))
        prec.toggled.connect(lambda v: app.set_setting("max_precision", v))
        card.lay.addWidget(prec)
        card.lay.addWidget(Label(
            "O OCR usa o Tesseract e roda inteiramente neste computador. Páginas com baixa confiança são "
            "marcadas para revisão; mesmo assim, confira nomes, datas, números e valores no original.",
            13, 400, "secondary"))
        c.addWidget(card)

        c.addWidget(SectionTitle("Fotos"))
        card = TileCard()
        dw = QCheckBox("Ao converter fotos em PDF, corrigir páginas curvas")
        dw.setChecked(bool(app.setting("dewarp_photos", False)))
        dw.toggled.connect(lambda v: app.set_setting("dewarp_photos", v))
        card.lay.addWidget(dw)
        card.lay.addWidget(Label(
            "Para fotos de livros e revistas (curvatura perto da lombada) e de papel ondulado: o texto fica reto e o "
            "OCR acerta mais. Vale para fotos de câmera (JPG e HEIC). Em fotos de páginas já retas, deixe desligado: "
            "a margem pode ser cortada. Também dá para corrigir um PDF pronto, na tela dele, em “Corrigir páginas "
            "curvas”. A correção usa o modelo UVDoc e roda inteiramente neste computador.", 13, 400, "secondary"))
        c.addWidget(card)

        c.addWidget(SectionTitle("Aparência"))
        card = TileCard()
        look = QComboBox()
        for label, key in (("Igual ao Windows", "system"), ("Claro", "light"), ("Escuro", "dark")):
            look.addItem(label, key)
        look.setCurrentIndex(max(0, look.findData(app.setting("appearance", "system"))))
        look.currentIndexChanged.connect(lambda _i: app.set_appearance(look.currentData()))
        card.lay.addWidget(look)
        c.addWidget(card)

        c.addWidget(SectionTitle("Sobre"))
        card = TileCard()
        for glyph, text in (("lock", "Tudo é processado neste computador. O Prumo PDF não coleta dados e não envia "
                                     "arquivos para a internet; só sai do computador o que você compartilhar ou "
                                     "o que a sua nuvem sincronizar."),
                            ("folder", "Os PDFs ficam na pasta da biblioteca, visível no Explorador de Arquivos.")):
            row = QHBoxLayout()
            ic = Label("")
            ic.setPixmap(glyph_icon(glyph, T.color("blue"), 18).pixmap(18, 18))
            ic.setFixedWidth(24)
            row.addWidget(ic, 0, Qt.AlignTop)
            row.addWidget(Label(text, 14), 1)
            card.lay.addLayout(row)
        import core
        card.lay.addWidget(Label("Desenvolvido por Color Software", 14, 600))
        card.lay.addWidget(Label(f"Prumo PDF {core.APP_VERSION}", 12, 400, "secondary"))
        c.addWidget(card)
        self.finish_content()
