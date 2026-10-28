"""Testes da etapa 4: nuvens, cópia de segurança, restauração, "Abrir com" e uma janela só (versão 1.5.0)."""

from __future__ import annotations

import json
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

from fixtures import digital_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms=100):
    end = time.time() + ms / 1000
    while time.time() < end:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()


class CloudTests(unittest.TestCase):
    def test_detects_cloud_folders_and_library_inside_them(self):
        import backup
        tmp = Path(tempfile.mkdtemp())
        saved = {k: os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial", "USERPROFILE",
                                                "LOCALAPPDATA", "APPDATA")}
        try:
            (tmp / "OneDrive").mkdir()
            (tmp / "iCloudDrive").mkdir()
            dbx = tmp / "Caixa Dropbox"
            dbx.mkdir()
            (tmp / "local" / "Dropbox").mkdir(parents=True)
            (tmp / "local" / "Dropbox" / "info.json").write_text(json.dumps({"personal": {"path": str(dbx)}}))
            for k in saved:
                os.environ.pop(k, None)
            os.environ["OneDrive"] = str(tmp / "OneDrive")
            os.environ["USERPROFILE"] = str(tmp)
            os.environ["LOCALAPPDATA"] = str(tmp / "local")
            clouds = backup.cloud_folders()
            names = [n for n, _p in clouds]
            self.assertIn("OneDrive", names)
            self.assertIn("iCloud Drive", names)
            self.assertIn("Dropbox", names)
            self.assertEqual(backup.cloud_of(tmp / "OneDrive" / "Prumo PDF", clouds), "OneDrive")
            self.assertEqual(backup.cloud_of(dbx / "Prumo PDF" / "Clientes", clouds), "Dropbox")
            self.assertIsNone(backup.cloud_of(tmp / "Documentos", clouds))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)


class BackupTests(unittest.TestCase):
    def setUp(self):
        from library import Library
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_bkp_"))
        self.lib = Library(self.tmp / "Biblioteca", local_dir=self.tmp / "local")
        self.lib.create_folder("Clientes")
        digital_pdf(self.lib.folder_path("Clientes") / "Procuração.pdf", 2)
        digital_pdf(self.lib.folder_path("") / "Petição.pdf", 4)
        self.lib.reload()
        self.lib.set_favorite(next(i for i in self.lib.items if i.name == "Procuração"), True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_then_restore_into_empty_library(self):
        import backup
        from library import Library
        dest = self.tmp / "Pendrive"
        dest.mkdir()
        target, n = backup.make_copy(self.lib.root, dest)
        self.assertEqual(n, 2)
        self.assertTrue((target / "Clientes" / "Procuração.pdf").exists())
        self.assertTrue((target / ".prumo" / "library.json").exists(), "favoritos vão junto")
        other = Library(self.tmp / "Outro computador", local_dir=self.tmp / "local2")
        res = backup.restore(target, other)
        self.assertEqual((res.added, res.skipped, res.favorites), (2, 0, 1))
        proc = next(i for i in other.items if i.name == "Procuração")
        self.assertEqual(proc.folder, "Clientes")
        self.assertTrue(proc.meta.favorite)
        # restaurar de novo não duplica nada
        res2 = backup.restore(target, other)
        self.assertEqual((res2.added, res2.skipped), (0, 2))
        self.assertEqual(len(other.items), 2)

    def test_copy_refuses_destination_inside_library(self):
        import backup
        from pdfops import UserError
        with self.assertRaises(UserError):
            backup.make_copy(self.lib.root, self.lib.root / "Clientes")

    def test_restore_from_zip_skips_dangerous_paths(self):
        import backup
        z = self.tmp / "copia.zip"
        pdf = digital_pdf(self.tmp / "x.pdf", 1)
        with zipfile.ZipFile(z, "w") as f:
            f.write(pdf, "Processos/Laudo.pdf")
            f.write(pdf, "../fora.pdf")
        res = backup.restore(z, self.lib)
        self.assertEqual(res.added, 1)
        self.assertIsNotNone(next((i for i in self.lib.items if i.rel == "Processos/Laudo.pdf"), None))
        self.assertFalse((self.tmp / "fora.pdf").exists())

    def test_find_same_file(self):
        import backup
        pet = next(i for i in self.lib.items if i.name == "Petição")
        copy = self.tmp / "baixado.pdf"
        shutil.copy2(pet.path, copy)
        self.assertEqual(backup.find_same_file(copy, self.lib).id, pet.id)
        self.assertIsNone(backup.find_same_file(digital_pdf(self.tmp / "novo.pdf", 9), self.lib))


class ExternalOpenTests(unittest.TestCase):
    def test_open_with_reuses_existing_pdf_and_single_instance_delivers_files(self):
        import ios_theme
        ios_theme.T.setup("light")
        tmp = Path(tempfile.mkdtemp(prefix="prumo_ext_"))
        try:
            import main
            from app_window import MainWindow
            from library import Library
            from reader import ReaderScreen
            w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.IniFormat),
                           Library(tmp / "Biblioteca", local_dir=tmp / "local"))
            w.resize(1000, 760)
            w.show()
            outside = digital_pdf(tmp / "Downloads" / "Sentença.pdf", 3)
            w.handle_external([str(outside)])
            self.assertEqual([i.name for i in w.lib.items], ["Sentença"])
            self.assertIsInstance(w.current(), ReaderScreen)
            w.home()
            w.handle_external([str(outside)])          # o mesmo arquivo de novo: não importa duas vezes
            self.assertEqual(len(w.lib.items), 1)
            w.home()
            # uma janela só: um segundo "processo" entrega os arquivos à janela aberta
            os.environ["USERNAME"] = os.environ.get("USERNAME", "teste") + str(os.getpid())
            server = main.start_instance_server(w, delay_ms=50)
            self.assertTrue(server.isListening())
            other = digital_pdf(tmp / "Downloads" / "Acórdão.pdf", 2)
            self.assertTrue(main._send_to_running({"open": [str(other)], "convert": []}))
            end = time.time() + 5
            while time.time() < end and len(w.lib.items) < 2:
                pump(50)
            self.assertEqual(sorted(i.name for i in w.lib.items), ["Acórdão", "Sentença"])
            server.close()
            w.hub.shutdown()
            w.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
