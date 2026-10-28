"""Testes da versão 1.2.0: tela inicial, estrela, três pontos, pastas, leitor, incluir e organizar páginas."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fixtures import digital_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms=200):
    end = time.time() + ms / 1000
    while time.time() < end:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()


def wait(cond, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(50)
    return False


class PageModelTests(unittest.TestCase):
    def test_move_rotate_delete_undo(self):
        from organize import PageModel
        m = PageModel(6)
        self.assertFalse(m.changed)
        new = m.move([1, 2], 5)          # páginas 2 e 3 para antes da 6
        self.assertEqual([p for p, _ in m.entries], [1, 4, 5, 2, 3, 6])
        self.assertEqual(new, [3, 4])
        m.move([5], 0)                   # a última vai para o início
        self.assertEqual([p for p, _ in m.entries], [6, 1, 4, 5, 2, 3])
        m.rotate([0], 90)
        m.rotate([0], 270)
        self.assertEqual(m.entries[0], (6, 0))
        m.delete([0])
        self.assertEqual(len(m.entries), 5)
        self.assertTrue(m.changed)
        for _ in range(5):
            m.undo()
        self.assertEqual(m.entries, m.original)
        self.assertFalse(m.changed)

    def test_deleting_last_page_counts_as_change(self):
        from organize import PageModel
        m = PageModel(3)
        m.delete([2])
        self.assertTrue(m.changed)

    def test_move_to_end(self):
        from organize import PageModel
        m = PageModel(4)
        m.move([0], 4)
        self.assertEqual([p for p, _ in m.entries], [2, 3, 4, 1])


class Stage1Flows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ios_theme
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_s1_"))
        from app_window import MainWindow
        from library import Library
        settings = QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat)
        cls.win = MainWindow(settings, Library(cls.tmp / "Biblioteca", local_dir=cls.tmp / "local"))
        cls.win.resize(1000, 760)
        cls.win.show()
        src = cls.tmp / "src"
        cls.win.import_paths([digital_pdf(src / "Contrato.pdf", 6), digital_pdf(src / "Laudo.pdf", 4)])
        assert wait(lambda: all(i.page_count for i in cls.win.lib.items), 60)

    @classmethod
    def tearDownClass(cls):
        cls.win.hub.shutdown()
        cls.win.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def by(self, name):
        return next((i for i in self.win.lib.items if i.name == name), None)

    def test_empty_state_message_gets_room_for_every_line(self):
        from ios_kit import EmptyState
        e = EmptyState("docs", "Nenhum PDF", "Importe PDFs pela tela inicial ou arraste-os para esta janela.")
        narrow, wide = e.heightForWidth(300), e.heightForWidth(900)
        self.assertGreater(len(e._lines(300)), 1)
        self.assertGreaterEqual(narrow - wide, 20 * (len(e._lines(300)) - len(e._lines(900))))

    def test_home_has_every_tool_and_no_scan(self):
        w = self.win
        w.home()
        home = w.current()
        for key in ("import", "all", "recent", "pending", "ocr", "favorites", "read", "do_ocr", "organize",
                    "insert", "remove", "extract", "split", "merge"):
            self.assertIn(key, home.tiles)
        self.assertNotIn("scan", home.tiles)
        self.assertFalse(hasattr(w, "scan"))

    def test_star_toggles_favorite(self):
        import screens
        w = self.win
        it = self.by("Contrato")
        tile = screens.make_doc_tile(w, it)
        tile.resize(220, tile.heightForWidth(220))
        tile.show()
        c = tile.star_rect().center()
        for t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            ev = QMouseEvent(t, QPointF(c), QPointF(tile.mapToGlobal(c.toPoint())), Qt.LeftButton,
                             Qt.LeftButton if t == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier)
            (tile.mousePressEvent if t == QEvent.MouseButtonPress else tile.mouseReleaseEvent)(ev)
        self.assertTrue(self.by("Contrato").meta.favorite)
        self.assertIn(self.by("Contrato"), w.lib.items_for("favorites"))
        w.actions.toggle_favorite(self.by("Contrato"))
        self.assertFalse(self.by("Contrato").meta.favorite)
        # os três pontos emitem o pedido de menu (e não abrem o PDF)
        got, opened = [], []
        tile2 = screens.make_doc_tile(w, self.by("Laudo"), on_click=lambda: opened.append(1))
        tile2.resize(220, tile2.heightForWidth(220))
        tile2.menu_clicked.disconnect()
        tile2.menu_clicked.connect(lambda: got.append(1))
        d = tile2.dots_rect().center()
        for t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            ev = QMouseEvent(t, QPointF(d), QPointF(d), Qt.LeftButton,
                             Qt.LeftButton if t == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier)
            (tile2.mousePressEvent if t == QEvent.MouseButtonPress else tile2.mouseReleaseEvent)(ev)
        self.assertEqual(got, [1])
        self.assertEqual(opened, [])

    def _click_in_chooser(self, names, then=None):
        """Clica nos PDFs indicados dentro do seletor aberto (e no "Adicionar", se for de vários)."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from ios_kit import DocTile

        def go():
            ov = [c for c in self.win.children() if c.__class__.__name__ == "SheetOverlay" and c.isVisible()][-1]
            for t in ov.findChildren(DocTile):
                if t.item.name in names:
                    QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, t.rect().center())
            if then:
                then(ov)
        QTimer.singleShot(400, go)

    def test_home_tools_pick_a_pdf_from_prumo(self):
        """Clicar num PDF do seletor abre a ferramenta com esse PDF (antes, nada acontecia)."""
        import screens
        w = self.win
        w.home()
        got = []
        orig = screens.split_dialog
        screens.split_dialog = lambda app, item: got.append(item)
        try:
            self._click_in_chooser({"Contrato"})
            screens.run_tool(w, "split", "Dividir qual PDF?")
        finally:
            screens.split_dialog = orig
        self.assertEqual([i.name for i in got], ["Contrato"])
        # Ler abre o leitor do PDF escolhido
        from reader import ReaderScreen
        self._click_in_chooser({"Laudo"})
        screens.run_tool(w, "read", "Ler qual PDF?")
        self.assertIsInstance(w.current(), ReaderScreen)
        self.assertEqual(w.current().item.name, "Laudo")
        w.home()

    def test_ocr_tool_selects_several_pdfs(self):
        import screens
        from PySide6.QtWidgets import QPushButton
        w = self.win
        w.home()
        started = []
        orig = w.start_ocr
        w.start_ocr = lambda item, quiet=False, allow_signed=False: started.append(item.name)
        orig_need = w.lib.needs_ocr_attention
        w.lib.needs_ocr_attention = lambda item: True        # os PDFs de teste são digitais
        try:
            def confirm(ov):
                b = next(x for x in ov.findChildren(QPushButton) if x.text().startswith("Adicionar ("))
                b.click()
            self._click_in_chooser({"Contrato", "Laudo"}, then=confirm)
            screens.run_tool(w, "ocr", "OCR de quais PDFs?")
        finally:
            w.start_ocr = orig
            w.lib.needs_ocr_attention = orig_need
        self.assertEqual(set(started), {"Contrato", "Laudo"})

    def test_selection_mode_in_lists(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        import screens
        w = self.win
        w.home()
        g = screens.DocumentGridScreen(w, list_id="all")
        w.push(g)
        g.set_selecting(True)
        t = next(t for t in g._tiles if t.item.name == "Contrato")
        QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, t.rect().center())
        self.assertEqual([i.name for i in g.selected_items()], ["Contrato"])
        w.back()

    def test_mouse_wheel_scrolls_without_changing_choices(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QComboBox
        import screens
        w = self.win
        w.home()
        st = screens.SettingsScreen(w)
        w.push(st)
        w.resize(1000, 500)
        pump(300)
        combo = st.findChildren(QComboBox)[0]
        before = combo.currentIndex()
        sb = st.scroll.verticalScrollBar()
        sb.setValue(0)
        pos = QPointF(combo.rect().center())
        ev = QWheelEvent(pos, QPointF(combo.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(combo, ev)
        self.assertEqual(combo.currentIndex(), before, "a roda não troca a opção escolhida")
        self.assertGreater(sb.maximum(), 0, "a tela de Ajustes tem o que rolar")
        self.assertGreater(sb.value(), 0, "a roda rola a tela")
        w.back()
        w.resize(1000, 760)

    def test_credits_and_yellow_favorites(self):
        from PySide6.QtWidgets import QLabel
        import screens
        w = self.win
        w.home()
        home = w.current()
        self.assertEqual(home.tiles["favorites"].color_name, "yellow")
        self.assertIn("Color Software", [l.text() for l in home.findChildren(QLabel)])
        self.assertEqual(w.lock.credit.text(), "Color Software")
        st = screens.SettingsScreen(w)
        w.push(st)
        pump(100)
        self.assertIn("Desenvolvido por Color Software", [l.text() for l in st.findChildren(QLabel)])
        w.back()

    def test_every_home_tool_acts_on_the_chosen_pdf(self):
        """Cada ferramenta da tela inicial: escolher um PDF do Prumo precisa levar à ação."""
        import screens
        w = self.win
        calls = []
        saved = (w.read, w.organize, screens.include_pages_dialog, screens.split_dialog)
        w.read = lambda item, *a, **k: calls.append(("read", item.name))
        w.organize = lambda item, *a, **k: calls.append(("organize", item.name))
        screens.include_pages_dialog = lambda app, item, *a, **k: calls.append(("insert", item.name))
        screens.split_dialog = lambda app, item, *a, **k: calls.append(("split", item.name))
        try:
            for key in ("read", "organize", "insert", "split", "remove", "extract"):
                w.home()
                self._click_in_chooser(["Contrato"])
                w.current().tiles[key].click()
                pump(200)
                if key in ("remove", "extract"):
                    cur = w.current()
                    self.assertIsInstance(cur, screens.PagePickerScreen, key)
                    calls.append((key, w.lib.item(cur.item_id).name))
        finally:
            w.read, w.organize, screens.include_pages_dialog, screens.split_dialog = saved
            w.home()
        self.assertEqual(calls, [(k, "Contrato") for k in ("read", "organize", "insert", "split", "remove",
                                                            "extract")])

    def test_cloud_chooser_uses_the_chosen_cloud(self):
        from PySide6.QtWidgets import QPushButton
        import backup
        import screens
        from ios_kit import SheetOverlay
        w = self.win
        icloud = self.tmp / "iCloudDrive"
        icloud.mkdir(exist_ok=True)
        chosen, opened, seen = [], [], []
        old = (backup.cloud_folders, w.change_library_to, screens.open_cloud_signin)
        backup.cloud_folders = lambda: [("iCloud Drive", icloud)]
        w.change_library_to = lambda p: chosen.append(p)
        screens.open_cloud_signin = lambda n: opened.append(n)
        try:
            def step():
                ov = next(o for o in w.findChildren(SheetOverlay) if o.isVisible())
                buttons = ov.findChildren(QPushButton)
                seen.extend(b.text() for b in buttons)
                [b for b in buttons if b.text() == "Entrar ou instalar…"][1].click()   # Google Drive
                next(b for b in buttons if b.text() == "Usar o iCloud Drive").click()
            QTimer.singleShot(300, step)
            screens.cloud_dialog(w)
        finally:
            backup.cloud_folders, w.change_library_to, screens.open_cloud_signin = old
        self.assertEqual(seen.count("Entrar ou instalar…"), 4)
        self.assertNotIn("Usar o Google Drive", seen, "nuvem não instalada não pode ser usada")
        self.assertEqual(opened, ["Google Drive"])
        self.assertEqual(chosen, [icloud / "Prumo PDF"])

    def test_cloud_signin_pages_are_official(self):
        import backup
        hosts = {c["name"]: c["url"].split("/")[2] for c in backup.CLOUD_APPS}
        self.assertEqual(hosts, {"iCloud Drive": "www.microsoft.com", "Google Drive": "support.google.com",
                                 "OneDrive": "www.microsoft.com", "Dropbox": "www.dropbox.com"})

    def test_copy_and_move_into_folder(self):
        lib = self.win.lib
        lib.create_folder("Cliente A")
        copies = lib.copy_into([self.by("Laudo")], "Cliente A")
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].folder, "Cliente A")
        self.assertIsNotNone(self.by("Laudo"))
        self.assertEqual(sum(1 for i in lib.items if i.name == "Laudo"), 2)

    def test_include_pages_and_undo(self):
        import pdfops
        lib = self.win.lib
        lib.create_folder("Incluir")
        digital_pdf(lib.folder_path("Incluir") / "Alvo.pdf", 3)
        digital_pdf(lib.folder_path("Incluir") / "Fonte.pdf", 8)
        lib.reload()
        alvo, fonte = self.by("Alvo"), self.by("Fonte")
        lib.modify(alvo, lambda p: pdfops.insert(p, fonte.path, pdfops.parse_page_selection("2-4", 8), 2))
        self.assertEqual(pdfops.page_count(self.by("Alvo").path), 6)
        self.assertTrue(lib.can_undo(self.by("Alvo")))
        lib.undo(self.by("Alvo"))
        self.assertEqual(pdfops.page_count(self.by("Alvo").path), 3)

    def test_reader_opens_and_zooms(self):
        from reader import ReaderScreen
        w = self.win
        it = self.by("Contrato")
        r = ReaderScreen(w, it.id)
        w.push(r)
        pump(300)
        self.assertEqual(len(r.view.sizes), 6)
        h1 = r.view.height()
        r.view.step_zoom(1)
        self.assertGreater(r.view.height(), h1)
        r.view.go_to(3)
        pump(100)
        self.assertEqual(r.view.current_page(), 3)
        self.assertTrue(wait(lambda: r.view.cache.best, 30), "nenhuma página renderizada")
        w.back()

    def test_organize_drag_with_mouse_and_save(self):
        import pdfops
        w = self.win
        lib = w.lib
        lib.create_folder("Organizar")
        digital_pdf(lib.folder_path("Organizar") / "Peça.pdf", 9)
        lib.reload()
        it = self.by("Peça")
        w.organize(it)
        scr = w.current()
        pump(300)
        g = scr.grid

        def ev(t, pos, buttons=Qt.LeftButton):
            return QMouseEvent(t, QPointF(pos), QPointF(g.mapToGlobal(pos)), Qt.LeftButton, buttons, Qt.NoModifier)
        start = g.cell_rect(0).center().toPoint()
        target = g.cell_rect(4).center().toPoint() + QPoint(int(g.cell_rect(4).width() / 2), 0)
        g.mousePressEvent(ev(QEvent.MouseButtonPress, start))
        for k in range(1, 6):
            g.mouseMoveEvent(ev(QEvent.MouseMove, start + (target - start) * k / 5))
        self.assertTrue(g.dragging)
        g.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, target, Qt.NoButton))
        self.assertFalse(g.dragging)
        self.assertEqual([p for p, _ in scr.model.entries][:5], [2, 3, 4, 5, 1])
        scr.bar_action("delete")
        self.assertEqual(len(scr.model.entries), 8)
        self.assertTrue(scr.save(go_back=False))
        self.assertEqual(pdfops.page_count(self.by("Peça").path), 8)
        self.assertTrue(lib.can_undo(self.by("Peça")))
        w.back()

    def test_organize_asks_before_leaving_unsaved(self):
        import organize
        w = self.win
        w.home()
        it = self.by("Laudo")
        w.organize(it)
        scr = w.current()
        scr.model.rotate([0], 90)
        orig = organize.alert
        organize.alert = lambda *a, **k: 2   # "Continuar editando"
        try:
            w.back()
            self.assertIs(w.current(), scr)
            organize.alert = lambda *a, **k: 1   # "Descartar"
            w.back()
            self.assertIsNot(w.current(), scr)
        finally:
            organize.alert = orig


if __name__ == "__main__":
    unittest.main()
