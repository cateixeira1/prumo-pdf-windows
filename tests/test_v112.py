"""Testes da versão 1.12.0: carimbo da assinatura, numeração sem sobreposição, "Sem OCR" e folhas rolantes."""

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

from PySide6.QtWidgets import QApplication  # noqa: E402

from fixtures import digital_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])


def page_text(path, i):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        pg = pdf[i]
        tp = pg.get_textpage()
        t = tp.get_text_range()
        tp.close()
        pg.close()
        return t
    finally:
        pdf.close()


class StampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_v112_"))
        os.environ["PRUMO_CERT_DIR"] = str(self.tmp / "certs")
        os.environ["PRUMO_A1_STORE"] = "file"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stamp_layout_fits_and_wraps(self):
        import signing
        inner_w = signing.STAMP_W - 2 * signing.STAMP_PAD_X
        for name in ("ANA", "JOSÉ DA CONCEIÇÃO ANTÔNIO",
                     "MARIA APARECIDA DE FÁTIMA SOUZA DOS SANTOS OLIVEIRA LIMA"):
            size, lead, lines = signing.stamp_layout(name)
            self.assertIn(size, (8, 7, 6))
            self.assertLessEqual(len(lines) * lead, signing.STAMP_H - 2 * signing.STAMP_PAD_Y)
            for ln in lines:
                self.assertLessEqual(signing._text_width(ln, size), inner_w, ln)
        _, _, lines = signing.stamp_layout("MARIA APARECIDA DE FÁTIMA SOUZA DOS SANTOS OLIVEIRA LIMA")
        self.assertGreaterEqual(len(lines), 4, "nome longo quebra em duas linhas")

    def test_stamp_is_visible_in_prumo_render(self):
        import demo
        import services
        import signing
        unsigned = digital_pdf(self.tmp / "a.pdf", 1)
        signed = self.tmp / "b.pdf"
        pfx = self.tmp / "c.pfx"
        pfx.write_bytes(demo.demo_pfx("MARIA DE TESTE:12345678909", "senha123"))
        info = signing.import_a1(pfx, "senha123")
        signing.sign_file(unsigned, signed, signing.file_signer(info, "senha123"), info.name,
                          signing.SignOptions(position="bottom_right"))
        a = services.render_page(unsigned, 0, 600)
        b = services.render_page(signed, 0, 600)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual((a.width(), a.height()), (b.width(), b.height()))
        diff = 0
        for y in range(int(b.height() * 0.75), b.height()):
            for x in range(int(b.width() * 0.4), b.width()):
                if a.pixel(x, y) != b.pixel(x, y):
                    diff += 1
        self.assertGreater(diff, 300, "o carimbo aparece no leitor do Prumo")


class NumberingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_v112n_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_renumber_replaces_same_position(self):
        import pdfops
        p = digital_pdf(self.tmp / "n.pdf", 3)
        pdfops.number_pages(p, fmt="n", position="bottom_center")
        pdfops.number_pages(p, fmt="pagina_de", position="bottom_center")
        t = page_text(p, 1)
        self.assertIn("Página 2 de 3", t)
        self.assertEqual(t.count("Página 2 de 3"), 1)
        self.assertEqual(pdfops.LAST_NUMBERING.replaced, 3)

    def test_other_position_is_kept(self):
        import pdfops
        p = digital_pdf(self.tmp / "n.pdf", 2)
        pdfops.number_pages(p, fmt="pagina_de", position="bottom_left")
        pdfops.number_pages(p, fmt="pagina_de", position="bottom_right")
        self.assertEqual(pdfops.LAST_NUMBERING.replaced, 0)
        self.assertEqual(page_text(p, 0).count("Página 1 de 2"), 2)

    def test_avoids_printed_number_on_first_pages(self):
        from fpdf import FPDF
        import pdfops
        import pypdfium2 as pdfium
        pdf = FPDF(format="A4")
        pdf.set_font("Helvetica", size=12)
        for n in range(1, 4):
            pdf.add_page()
            pdf.set_auto_page_break(False)
            pdf.cell(0, 10, f"Texto {n}")
            if n <= 2:  # número já impresso embaixo, no centro, nas páginas 1 e 2
                pdf.set_y(-15)
                pdf.cell(0, 10, str(n), align="C")
        p = self.tmp / "imp.pdf"
        pdf.output(str(p))
        pdfops.number_pages(p, fmt="n", position="bottom_center")
        self.assertEqual(pdfops.LAST_NUMBERING.numbered, 3)
        self.assertTrue(pdfops.LAST_NUMBERING.moved, "páginas 1 e 2 tiveram o número deslocado")
        doc = pdfium.PdfDocument(str(p))
        try:
            for i in (0, 1):
                pg = doc[i]
                tp = pg.get_textpage()
                rects = []
                for k in range(tp.count_rects()):
                    rects.append(tp.get_rect(k))
                tp.close()
                pg.close()
                # nenhum retângulo de texto do pé pode cobrir outro
                foot = [r for r in rects if r[1] < 80]
                for a in range(len(foot)):
                    for b in range(a + 1, len(foot)):
                        ra, rb = foot[a], foot[b]
                        inter = (min(ra[2], rb[2]) > max(ra[0], rb[0])) and (min(ra[3], rb[3]) > max(ra[1], rb[1]))
                        self.assertFalse(inter, f"página {i + 1}: números sobrepostos")
        finally:
            doc.close()


class I18nTests(unittest.TestCase):
    def tearDown(self):
        import i18n
        i18n.set_language("pt")

    def test_catalogs_are_valid_and_placeholders_match(self):
        import json
        import i18n
        for code in i18n.CODES:
            if code == "pt":
                continue
            f = ROOT / "app" / "locales" / f"{code}.json"
            self.assertTrue(f.exists(), code)
            cat = json.loads(f.read_text(encoding="utf-8"))
            self.assertTrue(cat, code)
            for pt, tr in cat.items():
                self.assertEqual(pt.count("{}"), tr.count("{}"), f"{code}: {pt!r}")
        en = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(en["Sem OCR"], "No OCR")
        self.assertGreater(len(en), 300)
        self.assertFalse((ROOT / "app" / "locales" / "se.json").exists())

    def test_translate_exact_pattern_and_fallback(self):
        import i18n
        i18n.set_language("de")
        self.assertEqual(i18n.tr("Salvar"), "Speichern")
        self.assertEqual(i18n.tr("Sem OCR"), "Ohne OCR")
        self.assertEqual(i18n.tr("Página 2 de 7"), "Seite 2 von 7")
        self.assertEqual(i18n.tr("12 páginas"), "12 Seiten")
        self.assertEqual(i18n.tr("Nenhum PDF sem OCR"), "Keine PDFs ohne OCR")
        # texto fora do catálogo fica como está (o teste test_i18n garante que todo texto da interface tem tradução)
        self.assertEqual(i18n.tr("Texto que não existe no catálogo"), "Texto que não existe no catálogo")
        i18n.set_language("pt")
        self.assertEqual(i18n.tr("Salvar"), "Salvar")

    def test_system_language_mapping_and_qt_hooks(self):
        import i18n
        from PySide6.QtWidgets import QComboBox, QLabel, QPushButton
        self.assertEqual(i18n.resolve("ja"), "ja")
        self.assertEqual(i18n.resolve("xx"), "en")
        i18n.set_language("fi")
        i18n.install_hooks()
        self.assertEqual(QPushButton("Salvar").text(), "Tallenna")
        lab = QLabel()
        lab.setText("Buscar")
        self.assertEqual(lab.text(), "Hae")
        box = QComboBox()
        box.addItem("Sem OCR", "pending")
        self.assertEqual((box.itemText(0), box.itemData(0)), ("Ei OCR:ää", "pending"))
        i18n.set_language("pt")
        self.assertEqual(QPushButton("Salvar").text(), "Salvar")

    def test_ocr_language_values(self):
        import ocr_langs
        self.assertEqual(ocr_langs.parse("por+eng"), ["por", "eng"])
        self.assertEqual(ocr_langs.parse("xxx"), ["por"])
        self.assertEqual(ocr_langs.join(["deu", "fra", "deu", "spa", "jpn", "fin"]), "deu+fra+spa+jpn")
        codes = {c for c, _ in ocr_langs.LANGS}
        self.assertTrue({"deu", "fra", "spa", "eng", "jpn", "chi_sim", "chi_tra", "nor", "swe", "dan", "fin"} <= codes)


class DefaultAppTests(unittest.TestCase):
    def test_settings_uri_for_installer_and_store(self):
        import default_app
        os.environ.pop("PRUMO_FORCE_PACKAGED", None)
        self.assertEqual(default_app.settings_uri(), "ms-settings:defaultapps?registeredAppMachine=Prumo%20PDF")
        os.environ["PRUMO_FORCE_PACKAGED"] = "1"
        try:
            self.assertEqual(default_app.settings_uri(),
                             "ms-settings:defaultapps?registeredAUMID=ColorSoftware.PrumoPDF_597630k0h63h8%21PrumoPDF")
        finally:
            os.environ.pop("PRUMO_FORCE_PACKAGED", None)

    def test_should_offer_rules(self):
        import core
        import default_app
        os.environ.pop("PRUMO_NO_PROMPTS", None)
        real = default_app.is_default_pdf_app
        try:
            default_app.is_default_pdf_app = lambda: False
            on_windows = os.name == "nt"
            self.assertEqual(default_app.should_offer(lambda k, d=None: d), on_windows)
            self.assertFalse(default_app.should_offer(lambda k, d=None: "never" if k == "default_pdf_prompt" else d))
            self.assertFalse(default_app.should_offer(
                lambda k, d=None: core.APP_VERSION if k == "default_pdf_prompt_version" else d))
            default_app.is_default_pdf_app = lambda: True
            self.assertFalse(default_app.should_offer(lambda k, d=None: d))
        finally:
            default_app.is_default_pdf_app = real

    def test_detects_default_handler_name(self):
        import default_app
        real = default_app.default_pdf_exe
        try:
            default_app.default_pdf_exe = lambda: r"C:\Program Files\Prumo PDF\PrumoPDF.exe"
            self.assertTrue(default_app.is_default_pdf_app())
            default_app.default_pdf_exe = lambda: r"C:\Program Files\Adobe\Acrobat.exe"
            self.assertFalse(default_app.is_default_pdf_app())
            default_app.default_pdf_exe = lambda: None
            self.assertIsNone(default_app.is_default_pdf_app())
        finally:
            default_app.default_pdf_exe = real


class UiTests(unittest.TestCase):
    def test_sem_ocr_label(self):
        from library import LISTS
        self.assertEqual(LISTS["pending"], "Sem OCR")
        src = (ROOT / "app" / "screens.py").read_text(encoding="utf-8")
        self.assertNotIn("Aguardando OCR", src)
        self.assertIn("Sem OCR", src)

    def test_version(self):
        import core
        self.assertEqual(core.APP_VERSION, "1.15.0")


if __name__ == "__main__":
    unittest.main()
