"""Telas do Prumo PDF para Windows, na mesma organização do app do iPhone."""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIntValidator, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QHBoxLayout,
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
    tile.clicked.connect(on_click or (lambda: app.open_document(item.id)))
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
        self.tools = FlowGrid(max_cols=4)  # 8 cartões: 2 ou 4 colunas

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
        add(g, "favorites", "Favoritos", "star", "pink", True,
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
                   "split": "Dividir qual PDF?"}

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


def run_tool(app, key, title):
    """Escolhe o PDF (do computador ou da biblioteca) e abre a ferramenta pedida."""
    multiple = key == "ocr"
    picked = choose_documents(app, title, multiple=multiple, allow_import=True,
                              only=(app.lib.needs_ocr_attention if key == "ocr" else None))
    if not picked:
        return
    item = picked[0]
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
        self.label.setText("Clique nos PDFs" if n == 0 else f"{n} selecionado{'s' if n != 1 else ''}")
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
        self.finish_content()

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

    def set_selecting(self, on: bool):
        self.selecting = on
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
            paint_badge(p, bx, y, "OCR", T.color("green"))


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
        tile("Ler", "book", "blue", lambda: app.read(item), subtitle="Páginas, modo leitor e busca")
        tile("Compartilhar", "share", "green", lambda: app.actions.share([item]),
             subtitle="Copiar, exportar, Explorador")
        tile("OCR", "textscan", "orange", lambda: self._ocr(item), count=self._ocr_count(item),
             subtitle=self._ocr_subtitle(item, busy), rounded=True)
        tile("Organizar páginas", "grid", "purple", lambda: app.organize(item),
             count=str(pages) if pages else None, subtitle="Arrastar, girar, excluir", rounded=True)
        tile("Incluir páginas", "plusrect", "teal", lambda: include_pages_dialog(app, item),
             subtitle="De outro PDF ou do computador", rounded=True)
        tile("Remover páginas", "minusrect", "red", lambda: app.push(PagePickerScreen(app, item.id, "remove")),
             rounded=True)
        tile("Dividir em partes", "scissors", "pink", lambda: split_dialog(app, item))
        tile("Extrair páginas", "docplus", "indigo", lambda: app.push(PagePickerScreen(app, item.id, "extract")))
        tile("Renomear", "pencil", "gray", lambda: app.actions.rename(item))
        tile("Mover", "folder", "brown", lambda: app.actions.move([item]), subtitle=item.folder_name)
        tile("Favorito" if item.meta.favorite else "Favoritar", "star", "yellow",
             lambda: lib.set_favorite(item, not item.meta.favorite), rounded=True, selected=item.meta.favorite)
        tile("Duplicar", "duplicate", "gray", lambda: self._duplicate(item), rounded=True)
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
        lib = self.app.lib
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

    def _duplicate(self, item):
        res = {}
        if self.app.attempt(lambda: res.setdefault("c", self.app.lib.duplicate(item))) and res.get("c"):
            self.app.toast(f"Cópia criada: {res['c'].name}", "Abrir", lambda: self.app.open_document(res["c"].id))

    def _undo(self, item):
        idx = alert(self.app, "Desfazer a última alteração?",
                    "O PDF volta a ficar como estava antes da última mudança nas páginas.",
                    [("Cancelar", "cancel"), ("Desfazer", "default")])
        if idx == 1 and self.app.attempt(lambda: self.app.lib.undo(item)):
            self.app.toast("Alteração desfeita.")


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


# --- Escolher páginas (remover, extrair) --------------------------------------

class PageTile(QAbstractButton):
    def __init__(self, thumbs, item, index):
        super().__init__()
        self.item, self.index = item, index
        self.thumb = Thumb(self, thumbs)
        self.checked_ = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

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
        card.lay.addWidget(Label("Clique nas páginas ou digite, por exemplo: 1, 3-5, 10-fim", 13, 400, "secondary"))
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
            self.tiles.append(t)
            self.grid.add(t)
        self.content.addWidget(self.grid)
        self.finish_content()
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

        c.addWidget(SectionTitle("Biblioteca e backup"))
        card = TileCard()
        if cloud:
            card.lay.addLayout(status_row("check", "green", f"Backup no {cloud}",
                                          f"Os PDFs ficam numa pasta do {cloud}: tudo o que você salva aqui vai para a "
                                          "nuvem e aparece nos outros computadores e no celular."))
        else:
            card.lay.addLayout(status_row("warning", "orange", "Só neste computador",
                                          "Se o computador estragar ou for perdido, os PDFs vão junto. Leve a biblioteca "
                                          "para uma nuvem (abaixo) ou faça cópias de segurança de vez em quando."))
        path = Label(str(lib.root), 13, 400, "secondary")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.lay.addWidget(path)
        if clouds and not cloud:
            card.lay.addWidget(Label("Nuvens encontradas neste computador:", 13, 600))
            row = QHBoxLayout()
            for name, folder in clouds:
                row.addWidget(small_button(f"Levar para o {name}",
                                           lambda _c=False, f=folder: app.change_library_to(f / "Prumo PDF")))
            row.addStretch(1)
            card.lay.addLayout(row)
        elif not clouds and not cloud:
            card.lay.addWidget(Label("Nenhuma nuvem encontrada. Instale o OneDrive, o Google Drive para computador, o "
                                     "iCloud para Windows ou o Dropbox e volte aqui.", 13, 400, "secondary"))
        row = QHBoxLayout()
        row.addWidget(small_button("Abrir no Explorador", lambda: app.reveal(lib.root)))
        row.addWidget(small_button("Mudar pasta…", app.change_library))
        row.addStretch(1)
        card.lay.addLayout(row)
        card.lay.addWidget(Label(
            "Os PDFs ficam como arquivos comuns nessa pasta: dá para abrir, copiar e editar com qualquer programa. "
            "Os favoritos e a ligação com as cópias de OCR vão junto, na subpasta oculta “.prumo”.",
            13, 400, "secondary"))
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
        card.lay.addWidget(Label(f"Prumo PDF {core.APP_VERSION}", 12, 400, "secondary"))
        c.addWidget(card)
        self.finish_content()
