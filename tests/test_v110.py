"""Testes da versão 1.10.0: barra de seleção, botão direito, desfazer/refazer, modo Texto e assinatura digital."""

from __future__ import annotations

import os
import shutil
import subprocess
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
from PySide6.QtGui import QMouseEvent, QTextCursor  # noqa: E402
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


def mouse(widget, typ, pos, button, buttons):
    pos = QPointF(pos)
    glob = QPointF(widget.mapToGlobal(pos.toPoint()))
    return QMouseEvent(typ, pos, pos, glob, button, buttons, Qt.NoModifier)


def validate(path, root_der):
    """Confere as assinaturas com o pyHanko, tendo o certificado de teste como raiz confiável."""
    from asn1crypto import x509 as ax
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    out = []
    with open(path, "rb") as f:
        r = PdfFileReader(f)
        for sig in r.embedded_signatures:
            vc = ValidationContext(trust_roots=[ax.Certificate.load(root_der)])
            out.append(validate_pdf_signature(sig, vc))
    return out


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_v110_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reflow_mapped_keeps_positions(self):
        import reader_text
        text = "Primeira  linha com\r\npalavra hifeni-\r\nzada e mais texto aqui no fim.\r\n\r\nOutro parágrafo."
        paras = reader_text.reflow_mapped(text)
        self.assertEqual([p for p, _ in paras], reader_text.reflow(text))
        self.assertEqual(paras[0][0], "Primeira linha com palavra hifenizada e mais texto aqui no fim.")
        for para, idx in paras:
            self.assertEqual(len(para), len(idx))
            for ch, k in zip(para, idx):
                if k >= 0 and ch != " ":
                    self.assertEqual(text[k], ch)
        self.assertEqual(reader_text.runs([5, 1, 2, 3, 9]), [(1, 4), (5, 6), (9, 10)])

    def test_history_undo_redo_and_created_files(self):
        from library import Library
        from reader_history import ReaderHistory
        lib = Library(self.tmp / "Biblioteca", local_dir=self.tmp / "local")
        src = digital_pdf(self.tmp / "src" / "Doc.pdf", 2)
        shutil.copy(src, lib.root / "Doc.pdf")
        lib.reload()
        item = lib.items[0]
        before = item.path.read_bytes()
        h = ReaderHistory(lib)
        files = h.begin([item])
        lib.modify(item, lambda p: Path(p).write_bytes(Path(p).read_bytes() + b"\n% mudou\n"))
        self.assertTrue(h.commit("Mudança", files))
        after = lib.item(item.id).path.read_bytes()
        self.assertNotEqual(before, after)
        h.undo()
        self.assertEqual(lib.item(item.id).path.read_bytes(), before)
        self.assertTrue(h.can_redo)
        h.redo()
        self.assertEqual(lib.item(item.id).path.read_bytes(), after)
        # nada mudou: não guarda
        files = h.begin([lib.item(item.id)])
        self.assertFalse(h.commit("Nada", files))
        # arquivo criado pela ação: desfazer tira da biblioteca, refazer traz de volta
        files = h.begin([])
        new_path = lib.root / "Doc - resumo.pdf"
        shutil.copy(src, new_path)
        new = lib.register(new_path)
        self.assertTrue(h.commit("Resumo", files, [new]))
        h.undo()
        self.assertIsNone(lib.item_by_path("Doc - resumo.pdf"))
        h.redo()
        self.assertIsNotNone(lib.item_by_path("Doc - resumo.pdf"))
        h.close()

    def _cert(self, name="MARIA DE TESTE:12345678909", password="senha123"):
        import demo
        os.environ["PRUMO_CERT_DIR"] = str(self.tmp / "certs")
        pfx = self.tmp / "cert.pfx"
        pfx.write_bytes(demo.demo_pfx(name, password))
        return pfx

    def test_import_a1_and_wrong_password(self):
        import signing
        from pdfops import UserError
        pfx = self._cert()
        with self.assertRaises(UserError):
            signing.import_a1(pfx, "errada")
        info = signing.import_a1(pfx, "senha123")
        self.assertEqual(info.name, "MARIA DE TESTE")
        self.assertEqual(info.doc, "12345678909")
        saved = signing.saved_certificates()
        self.assertEqual([c.id for c in saved], [info.id])
        with self.assertRaises(UserError):
            signing.file_signer(saved[0], "errada")
        signing.remove_certificate(saved[0])
        self.assertEqual(signing.saved_certificates(), [])

    def test_sign_copy_then_second_signature(self):
        import signing
        from library import Library
        lib = Library(self.tmp / "Biblioteca", local_dir=self.tmp / "local")
        digital_pdf(lib.root / "Contrato.pdf", 3)
        lib.reload()
        item = lib.items[0]
        info = signing.import_a1(self._cert(), "senha123")
        signer = signing.file_signer(info, "senha123")
        signed = signing.sign_item(lib, item, signer, info.name, signing.SignOptions(reason="Teste"))
        self.assertEqual(signed.name, "Contrato - assinado")
        self.assertEqual(signing.signature_count(signed.path), 1)
        self.assertEqual(lib.item(signed.id).meta.signed, 1)
        self.assertEqual(signing.signature_count(item.path), 0, "o original continua sem assinatura")
        self.assertEqual(signing.docmdp_level(signed.path), 2, "assinatura de certificação (DocMDP)")
        st = validate(signed.path, info.der)
        self.assertEqual(len(st), 1)
        self.assertTrue(st[0].intact and st[0].valid, st[0].pretty_print_details())
        self.assertTrue(st[0].trusted)
        data = signed.path.read_bytes()
        self.assertIn(b"/ETSI.CAdES.detached", data)
        self.assertIn(b"/DocMDP", data)
        # segunda assinatura: no mesmo arquivo, sem invalidar a primeira
        info2 = signing.import_a1(self._cert("JOAO DA SILVA"), "senha123")
        signed2 = signing.sign_item(lib, lib.item(signed.id), signing.file_signer(info2, "senha123"), info2.name,
                                    signing.SignOptions(position="bottom_right"))
        self.assertEqual(signed2.id, signed.id)
        self.assertEqual(signing.signature_count(signed2.path), 2)
        self.assertTrue(signed2.path.read_bytes().startswith(data), "atualização incremental")
        st1 = validate(signed2.path, info.der)
        st2 = validate(signed2.path, info2.der)
        self.assertTrue(st1[0].intact and st1[0].valid and st1[0].docmdp_ok)
        self.assertTrue(st2[1].intact and st2[1].valid)
        self.assertIn(b"/FieldMDP", signed2.path.read_bytes())
        names = [d["name"] for d in signing.describe_signatures(signed2.path)]
        self.assertEqual(names, ["MARIA DE TESTE", "JOAO DA SILVA"])

    def test_invisible_signature_and_rotated_page(self):
        import pikepdf

        import signing
        src = digital_pdf(self.tmp / "Girado.pdf", 2)
        with pikepdf.open(src, allow_overwriting_input=True) as pdf:
            pdf.pages[-1].obj["/Rotate"] = 90
            pdf.save(src)
        info = signing.import_a1(self._cert(), "senha123")
        for stamp in (False, True):
            out = self.tmp / f"assinado-{stamp}.pdf"
            signing.sign_file(src, out, signing.file_signer(info, "senha123"), info.name,
                              signing.SignOptions(stamp=stamp))
            st = validate(out, info.der)
            self.assertTrue(st[0].intact and st[0].valid)

    @unittest.skipUnless(sys.platform == "win32", "certificados do Windows só existem no Windows")
    def test_windows_store_certificate(self):
        """O mesmo caminho do A3: a chave fica no Windows e a assinatura é feita por ele."""
        import signing
        pfx = self._cert("CERTIFICADO DO WINDOWS")
        ps = (f"$p = ConvertTo-SecureString -String 'senha123' -AsPlainText -Force; "
              f"(Import-PfxCertificate -FilePath '{pfx}' -CertStoreLocation Cert:\\CurrentUser\\My -Password $p)"
              f".Thumbprint")
        thumb = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True,
                               text=True).stdout.strip().splitlines()[-1].strip()
        try:
            found = [c for c in signing.windows_certificates() if c.thumbprint == thumb]
            self.assertEqual(len(found), 1, f"certificado {thumb} não apareceu")
            info = found[0]
            self.assertEqual(info.name, "CERTIFICADO DO WINDOWS")
            src = digital_pdf(self.tmp / "Win.pdf", 1)
            out = self.tmp / "Win - assinado.pdf"
            signing.sign_file(src, out, signing.windows_signer(info), info.name, signing.SignOptions())
            st = validate(out, info.der)
            self.assertTrue(st[0].intact and st[0].valid, st[0].pretty_print_details())
        finally:
            subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            f"Remove-Item Cert:\\CurrentUser\\My\\{thumb} -DeleteKey"], capture_output=True)


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app_window
        import ios_kit
        import ios_theme
        import organize
        import screens
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_v110_gui_"))
        cls.alerts = []
        cls._orig = (ios_kit.alert, app_window.alert, screens.alert, organize.alert)

        def fake_alert(win, title, message="", buttons=(), text=None, **kw):
            cls.alerts.append(f"{title}: {message}")
            return (0, "") if text is not None else 0
        ios_kit.alert = app_window.alert = screens.alert = organize.alert = fake_alert
        from app_window import MainWindow
        from library import Library
        cls.win = MainWindow(QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat),
                             Library(cls.tmp / "Biblioteca", local_dir=cls.tmp / "local"))
        cls.win.resize(1300, 860)
        cls.win.show()
        cls.win.import_paths([digital_pdf(cls.tmp / "src" / "Laudo.pdf", 3),
                              digital_pdf(cls.tmp / "src" / "Contrato.pdf", 2)])
        assert wait(lambda: len(cls.win.lib.items) == 2 and all(i.page_count for i in cls.win.lib.items), 60)

    @classmethod
    def tearDownClass(cls):
        import app_window
        import ios_kit
        import organize
        import screens
        cls.win.hub.shutdown()
        cls.win.close()
        ios_kit.alert, app_window.alert, screens.alert, organize.alert = cls._orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.alerts.clear()

    def no_alerts(self, where=""):
        msgs = list(self.alerts)
        self.alerts.clear()
        self.assertEqual(msgs, [], f"alerta inesperado {where}")

    def by(self, name):
        return next((i for i in self.win.lib.items if i.name == name), None)

    def test_page_mode_toolbar_right_drag_and_history(self):
        import annotations
        from reader import ReaderScreen
        w = self.win
        w.home()
        item = self.by("Laudo")
        r = ReaderScreen(w, item.id)
        w.push(r)
        pump(300)
        self.assertFalse(r.undo_btn.isEnabled())
        # selecionar mostra a minibarra; sem destaque, "Desfazer destaque" fica escondido
        text = r.text.page_text(0)
        a = text.index("AÇÃO")
        r.view.select_range((0, a), (0, a + len("AÇÃO DE INDENIZAÇÃO")))
        r.selection_done()
        self.assertTrue(r.selbar.isVisible())
        self.assertTrue(r.selbar.unmark_btn.isHidden())
        r.selbar._open_popup()
        self.assertTrue(r.selbar.popup.isVisible())
        self.assertEqual(len(r.selbar.popup.dots), 5)
        r.selbar.popup.dots[2].click()                      # azul
        self.assertFalse(r.selbar.isVisible() or r.selbar.popup.isVisible(), "tudo some ao escolher a cor")
        self.no_alerts("ao destacar pela barra")
        marks = annotations.read_marks(w.lib.item(item.id).path)
        self.assertEqual(annotations.color_key(marks[0][0].color), "blue")
        self.assertEqual(r.last_color(), "blue")
        self.assertTrue(r.undo_btn.isEnabled())
        # desfazer o destaque só de uma parte: o resto continua destacado
        b = text.index("INDENIZAÇÃO")
        r.view.select_range((0, b), (0, b + len("INDENIZAÇÃO")))
        r.selection_done()
        self.assertFalse(r.selbar.unmark_btn.isHidden())
        r.unhighlight_selection()
        self.no_alerts("ao desfazer parte do destaque")
        marks = annotations.read_marks(w.lib.item(item.id).path)[0]
        self.assertEqual(len(marks), 1)
        self.assertIn("AÇÃO", marks[0].text)
        self.assertNotIn("INDENIZAÇÃO", marks[0].text)
        # desfazer e refazer
        r.undo()
        self.assertIn("INDENIZAÇÃO", annotations.read_marks(w.lib.item(item.id).path)[0][0].text)
        self.assertTrue(r.redo_btn.isEnabled())
        r.redo()
        self.assertNotIn("INDENIZAÇÃO", annotations.read_marks(w.lib.item(item.id).path)[0][0].text)
        r.undo()
        r.undo()
        self.assertEqual(annotations.read_marks(w.lib.item(item.id).path), {})
        self.assertFalse(r.undo_btn.isEnabled())
        # botão direito: arrastar destaca com a última cor; um clique só abre o menu
        menus = []
        r.context_menu = lambda pos, mark=None: menus.append(pos)
        v = r.view
        geom = r.text.geom(1)
        boxes = r.text._entry(1)[3]
        k0 = r.text.page_text(1).index("autora")
        p0 = v.to_screen(1, boxes[k0]).center()
        p1 = v.to_screen(1, boxes[k0 + 12]).center()
        _ = geom
        v.mousePressEvent(mouse(v, QEvent.MouseButtonPress, p0, Qt.RightButton, Qt.RightButton))
        v.mouseMoveEvent(mouse(v, QEvent.MouseMove, (p0 + p1) / 2, Qt.NoButton, Qt.RightButton))
        v.mouseMoveEvent(mouse(v, QEvent.MouseMove, p1, Qt.NoButton, Qt.RightButton))
        v.mouseReleaseEvent(mouse(v, QEvent.MouseButtonRelease, p1, Qt.RightButton, Qt.NoButton))
        self.no_alerts("com o botão direito")
        self.assertEqual(menus, [], "arrastar não abre o menu")
        marks = annotations.read_marks(w.lib.item(item.id).path)
        self.assertEqual(annotations.color_key(marks[1][0].color), "blue", "a última cor usada")
        v.mousePressEvent(mouse(v, QEvent.MouseButtonPress, p0, Qt.RightButton, Qt.RightButton))
        v.mouseReleaseEvent(mouse(v, QEvent.MouseButtonRelease, p0, Qt.RightButton, Qt.NoButton))
        self.assertEqual(len(menus), 1, "um clique abre o menu")
        del r.context_menu
        r.undo()
        w.back()
        self.no_alerts("ao sair")

    def test_text_mode_has_the_same_functions(self):
        import annotations
        import summary
        from reader import ReaderScreen, TextReaderScreen
        w = self.win
        w.home()
        item = self.by("Contrato")
        r = ReaderScreen(w, item.id)
        w.push(r)
        pump(200)
        r.switch_to("text", item.id)
        t = w.current()
        self.assertIsInstance(t, TextReaderScreen)
        pump(200)
        self.assertIsNotNone(t.sidebar)
        self.assertIsNotNone(t.panel)
        self.assertTrue(t.sidebar.isVisible() and t.panel.isVisible())
        self.assertIn("page_mode", t.panel.buttons)
        # selecionar no texto corrido e destacar: vai para o PDF, na página certa
        plain = t.browser.toPlainText()
        a = plain.index("demora no diagnóstico")
        c = t.browser.textCursor()
        c.setPosition(a)
        c.setPosition(a + len("demora no diagnóstico"), QTextCursor.KeepAnchor)
        t.browser.setTextCursor(c)
        self.assertEqual(t.selection_text().replace("\r\n", " ").replace("\n", " "), "demora no diagnóstico")
        t.selection_done()
        self.assertTrue(t.selbar.isVisible())
        t.highlight_selection("pink")
        self.no_alerts("ao destacar no modo texto")
        marks = annotations.read_marks(w.lib.item(item.id).path)
        self.assertEqual(list(marks), [0])
        self.assertEqual(annotations.color_key(marks[0][0].color), "pink")
        self.assertIn("demora", marks[0][0].text)
        self.assertIn("diagn", marks[0][0].text)
        self.assertTrue(t.browser.extraSelections(), "o destaque aparece no texto")
        # o destaque continua ao trocar de modo, e o desfazer vem junto
        t.switch_to("page", item.id)
        r = w.current()
        self.assertTrue(r.history.can_undo)
        self.assertEqual(len(r.view.marks.get(0, [])), 1)
        r.switch_to("text", item.id)
        t = w.current()
        # resumo a partir do modo texto, e desfazer apaga o resumo criado
        b = t.browser.toPlainText().index("hospital réu")
        c = t.browser.textCursor()
        c.setPosition(b)
        c.setPosition(b + len("hospital réu"), QTextCursor.KeepAnchor)
        t.browser.setTextCursor(c)
        t.add_to_summary()
        self.no_alerts("ao criar o resumo no modo texto")
        self.assertIsNotNone(summary.find_summary(w.lib, w.lib.item(item.id)))
        t.undo()
        self.assertIsNone(summary.find_summary(w.lib, w.lib.item(item.id)))
        t.redo()
        self.assertIsNotNone(summary.find_summary(w.lib, w.lib.item(item.id)))
        t.undo()
        t.undo()
        self.assertEqual(annotations.read_marks(w.lib.item(item.id).path), {})
        self.assertEqual(len(t.page_pos), 2, "um título de página para cada página")
        w.back()
        self.no_alerts("ao sair")

    def test_signed_pdf_is_read_only(self):
        import signing
        from reader import SIGNED_MSG, ReaderScreen
        w = self.win
        os.environ["PRUMO_CERT_DIR"] = str(self.tmp / "certs")
        import demo
        pfx = self.tmp / "c.pfx"
        pfx.write_bytes(demo.demo_pfx("ANA TESTE", "x1"))
        info = signing.import_a1(pfx, "x1")
        item = self.by("Contrato")
        signed = signing.sign_item(w.lib, item, signing.file_signer(info, "x1"), info.name, signing.SignOptions())
        r = ReaderScreen(w, signed.id)
        w.push(r)
        pump(200)
        self.assertEqual(r.edit_block(), SIGNED_MSG)
        before = signed.path.read_bytes()
        r.view.select_range((0, 0), (0, 10))
        r.highlight_selection("yellow")
        self.assertEqual(signed.path.read_bytes(), before, "PDF assinado não muda")
        self.assertFalse(r.panel.buttons["crop"].isEnabled())
        w.back()
        self.no_alerts()


if __name__ == "__main__":
    unittest.main()
