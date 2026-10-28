"""Testes da etapa 3: modo leitor e busca dentro do PDF (versão 1.4.0)."""

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


def pump(ms=100):
    end = time.time() + ms / 1000
    while time.time() < end:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()


def wait(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(40)
    return False


class TextTests(unittest.TestCase):
    def test_accent_insensitive_search_maps_back(self):
        import reader_text as rt
        text = "A Indenização pelos danos.\nÁREA de INDENIZACAO"
        hits = rt.find_all(text, "indenizacao")
        self.assertEqual([text[a:b] for a, b in hits], ["Indenização", "INDENIZACAO"])
        self.assertEqual([text[a:b] for a, b in rt.find_all(text, "área")], ["ÁREA"])
        self.assertEqual(rt.find_all(text, "   "), [])
        # quebra de linha conta como espaço
        self.assertEqual([text[a:b] for a, b in rt.find_all(text, "danos. area")], ["danos.\nÁREA"])

    def test_reflow_paragraphs(self):
        import reader_text as rt
        t = ("Fatos\nA autora foi internada para cirurgia e apresen-\ntou febre persistente durante a noite e a equipe\n"
             "não adotou providências.\nEXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA\nCÍVEL DO FORO CENTRAL.\n"
             "1. Citação do réu.\n2. Procedência.")
        self.assertEqual(rt.reflow(t), [
            "Fatos",
            "A autora foi internada para cirurgia e apresentou febre persistente durante a noite e a equipe "
            "não adotou providências.",
            "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CÍVEL DO FORO CENTRAL.",
            "1. Citação do réu.",
            "2. Procedência.",
        ])
        self.assertEqual(rt.reflow("  \n \n"), [])

    def test_search_page_rects_inside_page(self):
        import pypdfium2 as pdfium
        import reader_text as rt
        tmp = Path(tempfile.mkdtemp())
        try:
            p = digital_pdf(tmp / "a.pdf", 3)
            pdf = pdfium.PdfDocument(str(p))
            hits = rt.search_page(pdf, 1, "INDENIZACAO")
            self.assertEqual(len(hits), 1)
            x0, y0, x1, y1 = hits[0].rects[0]
            w, h = pdf.get_page_size(1)
            self.assertTrue(0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h)
            self.assertLess(y0, h / 2, "o texto está na metade de cima (origem no alto)")
            pdf.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReaderFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ios_theme
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_reader_"))
        from app_window import MainWindow
        from library import Library
        cls.win = MainWindow(QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat),
                             Library(cls.tmp / "Biblioteca", local_dir=cls.tmp / "local"))
        cls.win.resize(1000, 760)
        cls.win.show()
        src = cls.tmp / "src"
        cls.win.import_paths([digital_pdf(src / "Petição.pdf", 6), scanned_pdf(src / "Procuração.pdf", 1)])
        assert wait(lambda: all(i.page_count for i in cls.win.lib.items), 60)

    @classmethod
    def tearDownClass(cls):
        cls.win.hub.shutdown()
        cls.win.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def by(self, name):
        return next((i for i in self.win.lib.items if i.name == name), None)

    def test_page_search_highlights_and_steps(self):
        from reader import ReaderScreen
        w = self.win
        w.home()
        r = ReaderScreen(w, self.by("Petição").id)
        w.push(r)
        pump(200)
        w._focus_search()                       # Ctrl+F abre a barra de busca do leitor
        self.assertTrue(r.search_bar.isVisible())
        r.search_bar.field.setText("sepse")
        r.run_search()
        self.assertTrue(wait(lambda: r._search_job is None))
        self.assertEqual(len(r.results), 6, "uma ocorrência por página")
        self.assertEqual(r.search_bar.count.text(), "1 de 6")
        r.step(1)
        r.step(1)
        self.assertEqual(r.results[r.index].page, 2)
        self.assertIs(r.view.current_hit, r.results[2])
        r.step(-1)
        self.assertEqual(r.search_bar.count.text(), "2 de 6")
        r.close_search()
        self.assertEqual(r.view.hits, {})
        w.back()

    def test_search_on_scanned_pdf_says_it_has_no_text(self):
        from reader import ReaderScreen
        w = self.win
        w.home()
        r = ReaderScreen(w, self.by("Procuração").id)
        w.push(r)
        r.open_search()
        r.search_bar.field.setText("procuração")
        r.run_search()
        self.assertTrue(wait(lambda: r._search_job is None))
        self.assertEqual(r.results, [])
        self.assertIn("Sem texto", r.search_bar.count.text())
        w.back()

    def test_text_reader_mode(self):
        from reader import TextReaderScreen
        w = self.win
        w.home()
        t = TextReaderScreen(w, self.by("Petição").id)
        w.push(t)
        pump(100)
        self.assertEqual(len(t.pages), 6)
        self.assertIn("Página 3", t.browser.toPlainText())
        t.open_search()
        t.search_bar.field.setText("SEPSE")
        t.run_search()
        self.assertEqual(len(t.matches), 6)
        t.step(1)
        self.assertEqual(t.search_bar.count.text(), "2 de 6")
        a, b = t.matches[1]
        self.assertEqual(t.browser.toPlainText()[a:b].lower(), "sepse")
        before = t.size
        t.set_size(t.size + 2)
        self.assertEqual(t.size, before + 2)
        t.set_bg("sepia")
        t.set_font("serif")
        self.assertEqual(w.setting("reader_bg"), "sepia")
        t.set_bg("white")
        w.back()

    def test_mode_choices_with_ocr_copy(self):
        import reader
        lib = self.win.lib
        pet = self.by("Petição")
        self.assertEqual([c[0] for c in reader.mode_choices(lib, pet)], ["Página", "Texto"])
        copy = lib.duplicate(pet)
        lib.update_after_ocr(pet, copy, [], None)
        pet, copy = lib.item(pet.id), lib.item(copy.id)
        choices = reader.mode_choices(lib, pet)
        self.assertEqual([c[0] for c in choices], ["Original", "Com OCR", "Texto"])
        self.assertEqual(choices[2][1], ("text", copy.id), "o modo leitor usa o texto da cópia com OCR")
        self.assertEqual(reader.text_source(lib, pet).id, copy.id)
        # trocar de modo mantém a página
        r = reader.ReaderScreen(self.win, pet.id)
        self.win.push(r)
        pump(100)
        r.switch_to("text", copy.id)
        self.assertIsInstance(self.win.current(), reader.TextReaderScreen)
        self.win.back()


if __name__ == "__main__":
    unittest.main()
