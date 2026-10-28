"""Teste da interface nova (sem tela): fluxos principais usando a janela de verdade."""

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

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fixtures import digital_pdf, scanned_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])


def wait(cond, timeout=180.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    return False


class GuiFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ios_theme
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_gui_"))
        from app_window import MainWindow
        from library import Library
        settings = QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat)
        cls.win = MainWindow(settings, Library(cls.tmp / "Biblioteca", local_dir=cls.tmp / "local"))
        cls.win.resize(1000, 760)
        cls.win.show()
        cls.answers = []
        import screens
        import app_window
        cls._orig = (screens.alert, app_window.alert, screens.action_sheet, screens.pick_folder)

        def fake_alert(win, title, message="", buttons=(), text=None, **kw):
            ans = cls.answers.pop(0) if cls.answers else (len(buttons) - 1)
            return ans if text is None else ans
        screens.alert = app_window.alert = fake_alert
        screens.pick_folder = lambda app, title, current: cls.answers.pop(0)

    @classmethod
    def tearDownClass(cls):
        import screens
        import app_window
        screens.alert, app_window.alert, screens.action_sheet, screens.pick_folder = cls._orig
        cls.win.jobs.cancel_all()
        cls.win.hub.shutdown()
        cls.win.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def lib(self):
        return self.win.lib

    def by(self, name):
        return next((i for i in self.lib().items if i.name == name), None)

    def test_flows(self):
        w = self.win
        src = self.tmp / "src"
        w.import_paths([digital_pdf(src / "Petição.pdf", 7), scanned_pdf(src / "Procuração.pdf", 1)])
        self.assertTrue(wait(lambda: all(i.page_count for i in self.lib().items), 60), "análise não terminou")
        home = w.current()
        self.assertTrue(wait(lambda: home.tiles["pending"].count == "1", 10))
        self.assertEqual(home.tiles["all"].count, "2")
        self.assertEqual(home.tiles["pending"].count, "1")

        # busca pelo texto na tela inicial
        home.search.setText("sepse")
        home.refresh()
        self.assertTrue(home.results_box.isVisible() or not home.home_box.isVisible())
        home.search.setText("")

        # tela do documento, renomear
        pet = self.by("Petição")
        w.open_document(pet.id)
        import screens
        self.answers[:] = [(1, "Petição inicial")]
        screens.alert = lambda *a, **k: self.answers.pop(0)
        w.actions.rename(pet)
        self.assertIsNotNone(self.by("Petição inicial"))
        pet = self.by("Petição inicial")

        # dividir em 3 partes: 3 + 2 + 2
        lib = self.lib()
        from pdfops import page_count, split
        out = []
        split(pet.path, 3, lambda n: out.append(lib.unique_path(pet.folder, f"{pet.name} - Parte {n}")) or out[-1])
        lib.reload()
        self.assertEqual([page_count(self.by(f"Petição inicial - Parte {n}").path) for n in (1, 2, 3)], [3, 2, 2])

        # remover páginas pela tela de seleção, e desfazer
        picker = screens.PagePickerScreen(w, pet.id, "remove")
        w.push(picker)
        picker.field.setText("2-3")
        picker._typed("2-3")
        self.assertEqual(picker.selected, {2, 3})
        self.answers[:] = [1]
        picker._confirm()
        self.assertEqual(page_count(self.by("Petição inicial").path), 5)
        self.assertTrue(lib.can_undo(self.by("Petição inicial")))
        w.current().refresh()
        self.answers[:] = [1]
        w.current()._undo(self.by("Petição inicial"))
        self.assertEqual(page_count(self.by("Petição inicial").path), 7)

        # extrair
        picker = screens.PagePickerScreen(w, pet.id, "extract")
        w.push(picker)
        picker._typed("1, 7")
        picker._confirm()
        self.assertIsNotNone(self.by("Petição inicial - págs. 1, 7"))

        # pasta nova e mover
        lib.create_folder("Clientes")
        screens.pick_folder = lambda app, title, current: "Clientes"
        w.actions.move([self.by("Procuração")])
        self.assertEqual(self.by("Procuração").folder, "Clientes")

        # combinar
        m = screens.MergeScreen(w, preselection=[self.by("Petição inicial - Parte 1").id, self.by("Petição inicial - Parte 2").id])
        w.push(m)
        m.refresh()
        m.name.setText("Combinado")
        m._merge()
        self.assertEqual(page_count(self.by("Combinado").path), 5)

        # OCR de verdade (processo separado com Tesseract)
        proc = self.by("Procuração")
        w.start_ocr(proc)
        self.assertTrue(wait(lambda: self.by("Procuração - OCR") is not None and not w.jobs.is_busy(), 240),
                        "OCR não terminou")
        res = self.by("Procuração - OCR")
        self.assertEqual(res.folder, "Clientes")
        self.assertTrue(res.meta.is_ocr_result)
        self.assertEqual(lib.items_for("pending"), [])
        self.assertTrue(wait(lambda: (self.by("Procuração - OCR").meta.text_status or "") == "digital", 60))
        self.assertIn("indenizacao", lib.text(res.id))

        # todas as telas abrem sem erro
        for s in (screens.FoldersScreen(w), screens.SettingsScreen(w),
                  screens.DocumentGridScreen(w, list_id="ocr"), screens.DocumentGridScreen(w, folder="Clientes"),
                  screens.DocumentScreen(w, res.id)):
            w.push(s)
        for _ in range(6):
            w.back()
        w.home()
        self.assertEqual(w.stack.count(), 1)


if __name__ == "__main__":
    unittest.main()
