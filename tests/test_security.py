"""Testes da etapa 6: senha para abrir o Prumo e senha no PDF (versão 1.7.0)."""

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

from fixtures import digital_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])


def wait(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(40, loop.quit)
        loop.exec()
    return False


class PasswordHashTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        import security
        a, b = security.hash_password("Prumo2026"), security.hash_password("Prumo2026")
        self.assertNotEqual(a, b, "cada senha tem o seu valor aleatório")
        self.assertNotIn("Prumo2026", a, "a senha não é guardada")
        self.assertTrue(security.verify_password("Prumo2026", a))
        self.assertFalse(security.verify_password("prumo2026", a))
        self.assertFalse(security.verify_password("Prumo2026", ""))
        self.assertFalse(security.verify_password("Prumo2026", "lixo$1$2"))


class PdfPasswordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_sec_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_protect_with_aes256_and_unprotect(self):
        import pikepdf

        import pdfops
        src = digital_pdf(self.tmp / "Laudo.pdf", 3)
        locked = self.tmp / "Laudo - protegido.pdf"
        pdfops.protect(src, locked, "Sigilo#2026")
        self.assertTrue(pdfops.is_encrypted(locked))
        self.assertFalse(pdfops.is_encrypted(src))
        with self.assertRaises(pikepdf.PasswordError):
            pikepdf.open(locked)
        with pikepdf.open(locked, password="Sigilo#2026") as pdf:
            self.assertEqual(pdf.encryption.R, 6, "AES-256 (R=6), o padrão mais forte de PDF")
            self.assertEqual(len(pdf.pages), 3)
        self.assertTrue(pdfops.check_password(locked, "Sigilo#2026"))
        self.assertFalse(pdfops.check_password(locked, "sigilo#2026"))
        with self.assertRaises(pdfops.UserError):
            pdfops.unprotect(locked, self.tmp / "x.pdf", "errada")
        opened = self.tmp / "Laudo - sem senha.pdf"
        pdfops.unprotect(locked, opened, "Sigilo#2026")
        self.assertFalse(pdfops.is_encrypted(opened))
        self.assertEqual(pdfops.page_count(opened), 3)


class LockedFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ios_theme
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_lock_"))
        from app_window import MainWindow
        from library import Library
        import pdfops
        src = digital_pdf(cls.tmp / "src" / "Contrato.pdf", 4)
        lib_root = cls.tmp / "Biblioteca"
        lib_root.mkdir()
        pdfops.protect(src, lib_root / "Contrato - protegido.pdf", "abc123")
        cls.win = MainWindow(QSettings(str(cls.tmp / "s.ini"), QSettings.IniFormat),
                             Library(lib_root, local_dir=cls.tmp / "local"))
        cls.win.resize(1000, 760)
        cls.win.show()
        assert wait(lambda: all(i.meta.signature for i in cls.win.lib.items), 60)

    @classmethod
    def tearDownClass(cls):
        cls.win.hub.shutdown()
        cls.win.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def item(self):
        return next(i for i in self.win.lib.items if i.name == "Contrato - protegido")

    def test_locked_pdf_is_recognized(self):
        import screens
        it = self.item()
        self.assertTrue(it.meta.locked)
        self.assertFalse(self.win.lib.needs_ocr_attention(it), "PDF com senha não vai para Aguardando OCR")
        tile = screens.make_doc_tile(self.win, it)
        self.assertIn(("Com senha", "purple"), tile._badges())

    def test_reader_opens_with_password(self):
        import app_window
        from reader import ReaderScreen
        w = self.win
        w.home()
        orig = app_window.alert
        answers = [(1, "errada"), (1, "abc123")]
        app_window.alert = lambda *a, **k: answers.pop(0)
        try:
            w.read(self.item())
        finally:
            app_window.alert = orig
        r = w.current()
        self.assertIsInstance(r, ReaderScreen)
        self.assertEqual(len(r.view.sizes), 4)
        self.assertEqual(answers, [], "pediu de novo depois da senha errada")
        w.back()

    def test_unprotect_creates_copy(self):
        import screens
        w = self.win
        orig = w.ask_pdf_password
        w.ask_pdf_password = lambda item, title=None: "abc123"
        try:
            screens.unprotect_dialog(w, self.item())
        finally:
            w.ask_pdf_password = orig
        copy = next(i for i in w.lib.items if i.name == "Contrato")
        self.assertTrue(wait(lambda: w.lib.item(copy.id).meta.signature is not None))
        self.assertFalse(w.lib.item(copy.id).meta.locked)

    def test_app_lock(self):
        w = self.win
        w.home()
        self.assertFalse(w.lock_enabled)
        w.set_lock_password("senha-forte")
        self.assertTrue(w.lock_enabled)
        w.lock_now()
        self.assertTrue(w.is_locked)
        # arquivos que chegam travado esperam a senha
        outside = digital_pdf(self.tmp / "Downloads" / "Sentença.pdf", 2)
        w.handle_external([str(outside)])
        self.assertIsNone(next((i for i in w.lib.items if i.name == "Sentença"), None))
        w.lock.field.setText("errada")
        w.lock._try()
        self.assertTrue(w.is_locked)
        self.assertEqual(w.lock.error.text(), "Senha incorreta.")
        w.lock.field.setText("senha-forte")
        w.lock._try()
        self.assertFalse(w.is_locked)
        self.assertIsNotNone(next((i for i in w.lib.items if i.name == "Sentença"), None))
        w.home()
        w.set_lock_password(None)
        self.assertFalse(w.lock_enabled)
        w.lock_now()
        self.assertFalse(w.is_locked)


if __name__ == "__main__":
    unittest.main()
