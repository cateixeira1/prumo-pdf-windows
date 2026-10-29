"""Testes da versão 1.9.0: destaques, seleção de texto, resumo, cortar/girar, numerar, retângulo de seleção."""

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


def pump(ms=100):
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
        pump(40)
    return False


def page_text(path, index, password=None) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path), password=password)
    try:
        tp = pdf[index].get_textpage()
        return tp.get_text_range() or ""
    finally:
        pdf.close()


def send(widget, typ, local, button=Qt.LeftButton, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    local = QPointF(local)
    glob = QPointF(widget.mapToGlobal(local.toPoint()))
    QApplication.sendEvent(widget, QMouseEvent(typ, local, local, glob, button, buttons, mods))


def drag(host, a, b, steps=8):
    """Aperta no widget sob `a` (coordenadas do host), arrasta até `b` e solta."""
    target = host.childAt(QPoint(int(a[0]), int(a[1]))) or host
    send(target, QEvent.MouseButtonPress, target.mapFrom(host, QPoint(int(a[0]), int(a[1]))))
    for k in range(1, steps + 1):
        x = a[0] + (b[0] - a[0]) * k / steps
        y = a[1] + (b[1] - a[1]) * k / steps
        send(target, QEvent.MouseMove, target.mapFrom(host, QPoint(int(x), int(y))), button=Qt.NoButton)
        pump(20)
    send(target, QEvent.MouseButtonRelease, target.mapFrom(host, QPoint(int(b[0]), int(b[1]))), buttons=Qt.NoButton)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_v19_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_page_geometry_with_crop_and_rotation(self):
        import pikepdf
        import pypdfium2 as pdfium
        import reader_text as rt
        p = digital_pdf(self.tmp / "g.pdf", 2)
        with pikepdf.open(p, allow_overwriting_input=True) as pdf:
            pdf.pages[1].obj["/Rotate"] = 90
            pdf.pages[1].obj["/CropBox"] = pikepdf.Array([20, 30, 575, 812])
            pdf.save(p)
        pdf = pdfium.PdfDocument(str(p))
        page = pdf[1]
        geom = rt.PageGeom(page)
        self.assertAlmostEqual(geom.w, 782, delta=0.5)   # girada: largura = altura do recorte
        self.assertAlmostEqual(geom.h, 555, delta=0.5)
        for x, y in ((20, 30), (575, 812), (275.5, 410.25)):
            u, v = geom.to_view(x, y)
            x2, y2 = geom.to_pdf(u, v)
            self.assertAlmostEqual(x, x2, delta=0.2)
            self.assertAlmostEqual(y, y2, delta=0.2)
        # 90° no sentido horário: o canto de baixo à esquerda do recorte fica no alto à esquerda da tela
        u, v = geom.to_view(20, 30)
        self.assertAlmostEqual(u, 0, delta=0.5)
        self.assertAlmostEqual(v, 0, delta=0.5)
        hits = rt.search_page(pdf, 1, "INDENIZACAO")
        self.assertEqual(len(hits), 1)
        x0, y0, x1, y1 = hits[0].rects[0]
        self.assertTrue(0 <= x0 < x1 <= geom.w + 0.5 and 0 <= y0 < y1 <= geom.h + 0.5)
        self.assertGreater(y1 - y0, x1 - x0, "texto girado: o trecho fica em pé na tela")
        page.close()
        pdf.close()

    def test_text_layer_selection_and_highlight_file(self):
        import annotations
        import reader_text as rt
        p = digital_pdf(self.tmp / "h.pdf", 3)
        layer = rt.TextLayer(p)
        self.assertTrue(layer.has_text(1))
        text = layer.text(1, 0, layer.char_count(1))
        start = text.index("INDENIZA")
        a, b = start, start + len("INDENIZAÇÃO")
        self.assertEqual(layer.text(1, a, b), "INDENIZAÇÃO")
        rects = layer.pdf_rects(1, a, b)
        self.assertTrue(rects)
        # ponto no meio da palavra: a posição fica dentro dela
        x0, y0, x1, y1 = layer.view_rects(1, a, b)[0]
        k = layer.boundary_at(1, (x0 + x1) / 2, (y0 + y1) / 2)
        self.assertTrue(a <= k <= b)
        self.assertEqual(layer.word_at(1, (x0 + x1) / 2, (y0 + y1) / 2), (a, b))
        layer.close()
        names = annotations.add_to_file(p, [(1, rects, "green", "INDENIZAÇÃO")])
        self.assertEqual(len(names), 1)
        marks = annotations.read_marks(p)
        self.assertEqual(list(marks), [1])
        mark = marks[1][0]
        self.assertEqual(mark.ref, names[0][1])
        self.assertEqual(annotations.color_key(mark.color), "green")
        self.assertEqual(mark.text, "INDENIZAÇÃO")
        import pikepdf
        with pikepdf.open(p) as pdf:
            annot = pdf.pages[1].obj["/Annots"][0]
            self.assertEqual(annot["/Subtype"], "/Highlight")
            self.assertIn("/AP", annot)
            self.assertEqual(len(annot["/QuadPoints"]) % 8, 0)
        self.assertTrue(annotations.recolor_in_file(p, 1, mark.ref, "pink"))
        self.assertEqual(annotations.color_key(annotations.read_marks(p)[1][0].color), "pink")
        self.assertEqual(annotations.remove_from_file(p, [(1, mark.ref)]), 1)
        self.assertEqual(annotations.read_marks(p), {})
        self.assertIn("INDENIZAÇÃO", page_text(p, 1), "o texto continua no PDF")

    def test_margins_and_crop_rotate(self):
        import pdfops
        import pypdfium2 as pdfium
        media = (0.0, 0.0, 600.0, 800.0)
        for rot in (0, 90, 180, 270):
            m = (10.0, 20.0, 30.0, 40.0)
            box = pdfops.margins_to_box(media, rot, m)
            back = pdfops.box_to_margins(media, rot, box)
            for x, y in zip(m, back):
                self.assertAlmostEqual(x, y, places=6, msg=f"giro {rot}")
        p = digital_pdf(self.tmp / "c.pdf", 3)
        w0, h0 = pdfium.PdfDocument(str(p)).get_page_size(0)
        mm = 72 / 25.4
        n = pdfops.crop_and_rotate(p, [1, 3], (10 * mm, 20 * mm, 10 * mm, 20 * mm), 0)
        self.assertEqual(n, 2)
        pdf = pdfium.PdfDocument(str(p))
        w1, h1 = pdf.get_page_size(0)
        self.assertAlmostEqual(w1, w0 - 20 * mm, delta=0.5)
        self.assertAlmostEqual(h1, h0 - 40 * mm, delta=0.5)
        self.assertAlmostEqual(pdf.get_page_size(1)[0], w0, delta=0.5, msg="a página 2 não muda")
        pdf.close()
        # girar a página 2 e cortar 15 mm no alto como ela aparece
        pdfops.crop_and_rotate(p, [2], (0, 15 * mm, 0, 0), 90)
        boxes = pdfops.page_boxes(p)
        self.assertEqual(boxes[1]["rotate"], 90)
        l, t, r, b = pdfops.box_to_margins(boxes[1]["media"], 90, boxes[1]["crop"])
        self.assertAlmostEqual(t, 15 * mm, delta=0.01)
        self.assertAlmostEqual(l + r + b, 0, delta=0.01)
        pdf = pdfium.PdfDocument(str(p))
        self.assertAlmostEqual(pdf.get_page_size(1)[0], h0, delta=0.5)        # deitada
        self.assertAlmostEqual(pdf.get_page_size(1)[1], w0 - 15 * mm, delta=0.5)
        pdf.close()
        # página inteira de novo
        pdfops.crop_and_rotate(p, [1], (0, 0, 0, 0), 0)
        self.assertAlmostEqual(pdfium.PdfDocument(str(p)).get_page_size(0)[0], w0, delta=0.5)
        with self.assertRaises(pdfops.UserError):
            pdfops.crop_and_rotate(p, [1], (300, 0, 300, 0), 0)

    def test_number_pages(self):
        import pdfops
        import pikepdf
        p = digital_pdf(self.tmp / "n.pdf", 4)
        with pikepdf.open(p, allow_overwriting_input=True) as pdf:
            pdf.pages[3].obj["/Rotate"] = 90
            pdf.save(p)
        n = pdfops.number_pages(p, fmt="pagina_de", position="bottom_right", start=1, first_page=2)
        self.assertEqual(n, 3)
        self.assertNotIn("Página 1 de", page_text(p, 0))
        self.assertIn("Página 1 de 3", page_text(p, 1))
        self.assertIn("Página 3 de 3", page_text(p, 3))
        # o número fica embaixo à direita, também na página girada
        import pypdfium2 as pdfium
        import reader_text as rt
        pdf = pdfium.PdfDocument(str(p))
        for i in (1, 3):
            hits = rt.search_page(pdf, i, "de 3")
            self.assertTrue(hits, f"página {i + 1}")
            w, h = pdf.get_page_size(i)
            x0, y0, x1, y1 = hits[-1].rects[-1]
            self.assertGreater(y0, h * 0.85, f"página {i + 1}: perto do pé")
            self.assertGreater(x0, w * 0.55, f"página {i + 1}: à direita")
            self.assertLess(y1 - y0, 20, f"página {i + 1}: texto deitado normal (não em pé)")
        pdf.close()
        self.assertEqual(pdfops.number_text("barra", 2, 9), "2/9")

    def test_summary_store_and_labels(self):
        import summary
        self.assertEqual(summary.pages_label([10]), "Trecho extraído da página 10")
        self.assertEqual(summary.pages_label([11, 10]), "Trecho extraído das páginas 10-11")

    def test_password_strength(self):
        import screens
        self.assertEqual(screens.password_strength("1234")[1], "red")
        self.assertEqual(screens.password_strength("caso2026abc")[1], "orange")
        self.assertEqual(screens.password_strength("Caso2026!Ana")[1], "green")


class ReaderFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app_window
        import ios_kit
        import ios_theme
        import organize
        import screens
        ios_theme.T.setup("light")
        # Um alerta de verdade espera um clique e travaria o teste: aqui ele só fica anotado.
        cls.alerts = []
        cls._orig_alerts = (ios_kit.alert, app_window.alert, screens.alert, organize.alert)

        def fake_alert(win, title, message="", buttons=(), text=None, **kw):
            cls.alerts.append(f"{title}: {message}")
            return (0, "") if text is not None else 0
        ios_kit.alert = app_window.alert = screens.alert = organize.alert = fake_alert
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_v19_gui_"))
        from app_window import MainWindow
        from library import Library
        cls.win = MainWindow(QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat),
                             Library(cls.tmp / "Biblioteca", local_dir=cls.tmp / "local"))
        cls.win.resize(1300, 860)
        cls.win.show()
        src = cls.tmp / "src"
        cls.win.import_paths([digital_pdf(src / f"Doc {n}.pdf", 3) for n in range(1, 6)]
                             + [digital_pdf(src / "Laudo.pdf", 4)])
        assert wait(lambda: all(i.page_count for i in cls.win.lib.items), 60)

    @classmethod
    def tearDownClass(cls):
        import app_window
        import ios_kit
        import organize
        import screens
        cls.win.hub.shutdown()
        cls.win.close()
        ios_kit.alert, app_window.alert, screens.alert, organize.alert = cls._orig_alerts
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.alerts.clear()

    def no_alerts(self, where=""):
        """Falha mostrando a mensagem de erro que o app teria mostrado."""
        msgs = list(self.alerts)
        self.alerts.clear()
        self.assertEqual(msgs, [], f"alerta inesperado {where}")

    def by(self, name):
        return next((i for i in self.win.lib.items if i.name == name), None)

    def test_reader_highlight_undo_and_summary(self):
        import annotations
        from reader import ReaderScreen
        w = self.win
        w.home()
        laudo = self.by("Laudo")
        r = ReaderScreen(w, laudo.id)
        w.push(r)
        pump(300)
        self.assertTrue(r.sidebar.isVisible(), "miniaturas à esquerda")
        self.assertTrue(r.panel.isVisible(), "painel à direita")
        r.sidebar.page_clicked.emit(2)
        pump(100)
        self.assertEqual(r.view.current_page(), 2)
        # seleciona "INDENIZAÇÃO" na página 2 e destaca em amarelo
        text = r.text.text(1, 0, r.text.char_count(1))
        a = text.index("INDENIZA")
        r.view.select_range((1, a), (1, a + len("INDENIZAÇÃO")))
        self.assertTrue(r.view.has_selection())
        self.assertEqual(r.selection_text(), "INDENIZAÇÃO")
        r.highlight_selection("yellow")
        self.no_alerts("ao destacar")
        marks = annotations.read_marks(w.lib.item(laudo.id).path)
        self.assertEqual(len(marks.get(1, [])), 1)
        self.assertEqual(len(r.view.marks.get(1, [])), 1, "o leitor vê o destaque novo")
        self.assertFalse(r.view.has_selection())
        self.assertTrue(w.lib.can_undo(w.lib.item(laudo.id)))
        r.undo_highlight()
        self.no_alerts("ao desfazer o destaque")
        self.assertEqual(annotations.read_marks(w.lib.item(laudo.id).path), {})
        # marca-texto: com a cor escolhida, soltar o mouse já destaca
        r.set_tool("highlight", "blue")
        self.assertEqual(r.view.tool, "highlight")
        r.view.select_range((2, 0), (2, 20))
        r.view._pressing = True
        r.view.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5), QPointF(5, 5),
                                             Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.no_alerts("com o marca-texto")
        marks = annotations.read_marks(w.lib.item(laudo.id).path)
        self.assertEqual(annotations.color_key(marks[2][0].color), "blue")
        r.set_tool("select")
        # resumo: dois trechos, de páginas diferentes
        r.view.select_range((0, 0), (1, 30))
        r.add_to_summary()
        self.no_alerts("ao criar o resumo")
        res = self.by("Laudo - resumo")
        self.assertIsNotNone(res)
        r.view.select_range((3, 0), (3, 40))
        r.add_to_summary()
        self.no_alerts("ao aumentar o resumo")
        res = self.by("Laudo - resumo")
        content = "\n".join(page_text(res.path, i) for i in range(res.page_count or 1))
        self.assertEqual(content.count("Resumo de"), 1, "o cabeçalho aparece uma vez")
        self.assertIn("Trecho extraído das páginas 1-2", content)
        self.assertIn("Trecho extraído da página 4", content)
        self.assertIsNotNone(r.summary_item())
        w.back()
        self.no_alerts("ao sair do leitor")

    def test_rubber_band_selects_pdfs(self):
        import screens
        from rubberband import rect_in
        w = self.win
        w.home()
        w.push(screens.DocumentGridScreen(w, list_id="all"))
        pump(300)
        scr = w.current()
        self.assertGreaterEqual(len(scr._tiles), 4)
        r0, r2 = rect_in(scr.body, scr._tiles[0]), rect_in(scr.body, scr._tiles[2])
        drag(scr.body, (r0.center().x(), r0.center().y()), (r2.center().x(), r2.center().y() + 4))
        pump(200)
        scr = w.current()
        self.assertTrue(scr.selecting)
        self.assertEqual(len(scr.selected), 3)
        w.back()
        self.no_alerts()

    def test_organize_preview_and_band(self):
        w = self.win
        w.home()
        item = self.by("Laudo")
        w.organize(item)
        pump(300)
        org = w.current()
        org.preview(1)
        pump(200)
        ov = org._preview
        self.assertTrue(ov.isVisible())
        ov.step(1)
        self.assertEqual(ov.index, 2)
        ov.close_preview()
        items = org._band_items()
        a = items[0][1]
        b = items[2][1]
        drag(org.body, (2, a.top() + 20), (b.center().x(), b.center().y()))
        pump(100)
        self.assertEqual(org.grid.selected, {0, 1, 2})
        self.assertFalse(org.model.changed, "o retângulo só seleciona")
        w.back()
        self.no_alerts()


if __name__ == "__main__":
    unittest.main()
