"""Testes da conversão de outros arquivos em PDF (versão 1.3.0)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])


def pdf_pages(path):
    import pypdf
    return pypdf.PdfReader(str(path)).pages


def pdf_text(path):
    return " ".join((p.extract_text() or "") for p in pdf_pages(path))


def make_docx(path: Path, paragraphs, heading="Petição inicial"):
    """Um .docx mínimo e válido (sem bibliotecas extras)."""
    body = f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{heading}</w:t></w:r></w:p>'
    for t in paragraphs:
        body += f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
    body += ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Data</w:t></w:r></w:p></w:tc>'
             '<w:tc><w:p><w:r><w:t>Valor</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return path


class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_conv_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def img(self, name, size=(1200, 800), mode="RGB", color=(200, 30, 30), exif_orientation=None):
        from PIL import Image
        im = Image.new(mode, size, color)
        p = self.tmp / name
        if exif_orientation:
            ex = Image.Exif()
            ex[0x0112] = exif_orientation
            im.save(p, exif=ex.tobytes())
        else:
            im.save(p)
        return p

    def test_kinds_and_filter(self):
        import convert
        self.assertEqual(convert.kind("a.JPG"), "image")
        self.assertEqual(convert.kind("a.docx"), "word")
        self.assertEqual(convert.kind("a.xlsx"), "excel")
        self.assertEqual(convert.kind("a.pptx"), "powerpoint")
        self.assertEqual(convert.kind("a.pdf"), "pdf")
        self.assertIsNone(convert.kind("a.exe"))
        self.assertIn("*.heic", convert.dialog_filter())

    def test_images_combined_and_oriented(self):
        import convert
        landscape = self.img("paisagem.jpg", (1600, 1000))
        rotated = self.img("girada.jpg", (1600, 1000), exif_orientation=6)   # foto de celular "deitada"
        png = self.img("transparente.png", (500, 700), "RGBA", (0, 0, 255, 120))
        res = convert.convert([landscape, rotated, png], combine_images=True, combined_name="Fotos",
                              work_dir=self.tmp / "w1")
        self.assertEqual(res.failed, [])
        self.assertEqual(len(res.created), 1)
        self.assertEqual(res.names, ["Fotos"])
        self.assertTrue(res.from_images)
        pages = pdf_pages(res.created[0])
        self.assertEqual(len(pages), 3)
        w0, h0 = float(pages[0].mediabox.width), float(pages[0].mediabox.height)
        w1, h1 = float(pages[1].mediabox.width), float(pages[1].mediabox.height)
        self.assertGreater(w0, h0, "imagem larga vai para A4 deitado")
        self.assertGreater(h1, w1, "a rotação da foto (EXIF) é respeitada")
        self.assertAlmostEqual(max(w0, h0), 841.89, delta=1.5)

    def test_images_one_pdf_each(self):
        import convert
        a, b = self.img("a.png"), self.img("b.bmp")
        res = convert.convert([a, b], combine_images=False, work_dir=self.tmp / "w2")
        self.assertEqual(res.names, ["a", "b"])
        self.assertEqual([len(pdf_pages(p)) for p in res.created], [1, 1])

    def test_heic_from_iphone(self):
        import convert
        try:
            import pillow_heif
            from PIL import Image
            pillow_heif.register_heif_opener()
            p = self.tmp / "IMG_0001.HEIC"
            Image.new("RGB", (800, 600), (10, 120, 90)).save(p, format="HEIF")
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"sem codificador HEIF aqui: {exc}")
        res = convert.convert([p], work_dir=self.tmp / "w3")
        self.assertEqual(res.failed, [])
        self.assertEqual(len(pdf_pages(res.created[0])), 1)

    def test_multipage_tiff(self):
        import convert
        from PIL import Image
        p = self.tmp / "digitalizacao.tif"
        frames = [Image.new("L", (850, 1100), v) for v in (255, 200, 150)]
        frames[0].save(p, save_all=True, append_images=frames[1:])
        res = convert.convert([p], work_dir=self.tmp / "w4")
        self.assertEqual(len(pdf_pages(res.created[0])), 3)

    def test_text_and_html(self):
        import convert
        txt = self.tmp / "anotações.txt"
        txt.write_text("Prazo para contestação: 15 dias úteis.\n" * 120, encoding="cp1252")
        html = self.tmp / "pagina.html"
        html.write_text("<h1>Laudo</h1><p>Paciente com <b>sepse</b> após cirurgia.</p>"
                        "<table><tr><td>Data</td><td>Valor</td></tr></table>", encoding="utf-8")
        res = convert.convert([txt, html], work_dir=self.tmp / "w5")
        self.assertEqual(res.failed, [])
        self.assertEqual(res.kinds, ["text", "html"])
        self.assertGreater(len(pdf_pages(res.created[0])), 1, "texto longo ocupa várias páginas A4")
        self.assertIn("contestação", pdf_text(res.created[0]))
        self.assertIn("sepse", pdf_text(res.created[1]))

    def test_docx(self):
        import convert
        p = make_docx(self.tmp / "Petição.docx", ["A autora vem propor ação de indenização.",
                                                   "Requer a citação do réu."])
        res = convert.convert([p], work_dir=self.tmp / "w6")
        self.assertEqual(res.failed, [])
        text = pdf_text(res.created[0])
        self.assertIn("indenização", text)
        self.assertIn("Petição inicial", text)
        if convert.office_app_for(p) is None and convert.find_libreoffice() is None:
            self.assertEqual(res.simplified, ["Petição.docx"])

    def test_spreadsheet_without_office_reports_clearly(self):
        import convert
        p = self.tmp / "planilha.xlsx"
        p.write_bytes(b"PK\x03\x04 not really a spreadsheet")
        res = convert.convert([p], work_dir=self.tmp / "w7")
        if convert.office_app_for(p) is None and convert.find_libreoffice() is None:
            self.assertEqual(res.created, [])
            self.assertIn("Excel", res.failed[0][1])
            self.assertIn("LibreOffice", res.failed[0][1])
        else:
            self.assertEqual(len(res.created) + len(res.failed), 1)


class ConvertFlow(unittest.TestCase):
    """Fluxo na janela: converter duas fotos num PDF só e marcar para OCR depois."""

    def test_window_flow(self):
        import ios_theme
        ios_theme.T.setup("light")
        tmp = Path(tempfile.mkdtemp(prefix="prumo_conv_flow_"))
        try:
            from app_window import MainWindow
            from library import Library
            import app_window
            w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.IniFormat),
                           Library(tmp / "Biblioteca", local_dir=tmp / "local"))
            w.resize(1000, 760)
            w.show()
            from PIL import Image
            src = tmp / "src"
            src.mkdir()
            for n in ("1", "2"):
                Image.new("RGB", (900, 1200), "white").save(src / f"foto{n}.jpg")
            make_docx(src / "Contrato.docx", ["Cláusula primeira."])
            answers = [0, (1, "Fotos do prontuário"), 0]   # um PDF só; nome; OCR "Mais tarde"
            orig = app_window.alert
            app_window.alert = lambda *a, **k: answers.pop(0) if answers else 0
            try:
                w.import_paths([src / "foto1.jpg", src / "foto2.jpg", src / "Contrato.docx"])
            finally:
                app_window.alert = orig
            names = sorted(i.name for i in w.lib.items)
            self.assertEqual(names, ["Contrato", "Fotos do prontuário"])
            fotos = next(i for i in w.lib.items if i.name == "Fotos do prontuário")
            self.assertTrue(fotos.meta.pending_ocr)
            self.assertEqual(len(pdf_pages(fotos.path)), 2)
            end = time.time() + 30
            while time.time() < end and w.lib.item(fotos.id).meta.text_status is None:
                loop = QEventLoop()
                QTimer.singleShot(50, loop.quit)
                loop.exec()
            self.assertEqual(w.lib.item(fotos.id).meta.text_status, "scanned")
            self.assertIn(w.lib.item(fotos.id), w.lib.items_for("pending"))
            w.hub.shutdown()
            w.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
