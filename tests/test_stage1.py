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
