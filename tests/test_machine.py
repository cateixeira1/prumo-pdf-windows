"""
Prumo adaptado ao computador onde roda: perfil da máquina (núcleos, memória, bateria), OCR com a
quantidade certa de páginas e prioridade abaixo do normal, caches com limite em bytes, miniaturas em
degraus e limpeza do cache no disco.
"""

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

from PySide6.QtCore import QEventLoop, QRunnable, QThreadPool, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import machine  # noqa: E402
from fixtures import digital_pdf, scanned_pdf  # noqa: E402
from machine import GB, MB, Machine  # noqa: E402

app = QApplication.instance() or QApplication([])


def wait(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return cond()


def M(logical=8, physical=4, total=16 * GB, avail=8 * GB, battery=False, saver=False) -> Machine:
    return Machine(logical, physical, total, avail, battery, saver)


class ProfileTests(unittest.TestCase):
    def test_measures_this_computer(self):
        m = machine.current()
        self.assertGreaterEqual(m.logical, 1)
        self.assertTrue(1 <= m.physical <= m.logical, m)
        self.assertGreater(m.total_ram, 512 * MB, "a memória do computador foi lida")
        self.assertTrue(0 < m.avail_ram <= m.total_ram, m)
        self.assertIsInstance(m.describe(), str)

    @unittest.skipUnless(sys.platform == "win32", "só no Windows")
    def test_windows_apis(self):
        self.assertGreaterEqual(machine._physical_windows() or 0, 1, "GetLogicalProcessorInformationEx")
        total, avail = machine._memory()
        self.assertGreater(total, 0, "GlobalMemoryStatusEx")
        on_battery, saver = machine._power()
        self.assertIsInstance(on_battery, bool)
        self.assertIsInstance(saver, bool)


class OcrJobsTests(unittest.TestCase):
    def test_leaves_one_processor_free(self):
        self.assertEqual(machine.ocr_jobs(False, M(logical=8, physical=4)), 7)
        self.assertEqual(machine.ocr_jobs(False, M(logical=1, physical=1)), 1)

    def test_battery(self):
        self.assertEqual(machine.ocr_jobs(False, M(logical=8, physical=4, battery=True)), 2)
        self.assertEqual(machine.ocr_jobs(False, M(logical=2, physical=1, battery=True)), 1)
        self.assertEqual(machine.ocr_jobs(False, M(logical=16, physical=8, battery=True, saver=True)), 1)

    def test_free_memory_limits_pages(self):
        # 4 GB com 1 GB livre: uma página por vez
        self.assertEqual(machine.ocr_jobs(False, M(logical=8, total=4 * GB, avail=1 * GB)), 1)
        # 8 GB com 3 GB livres: (3 GB - 0,8 GB de reserva) / 250 MB = 9; com precisão máxima, / 400 MB = 5
        m = M(logical=16, physical=8, total=8 * GB, avail=3 * GB)
        self.assertEqual(machine.ocr_jobs(False, m), 9)
        self.assertEqual(machine.ocr_jobs(True, m), 5)

    def test_unknown_memory_uses_processors_only(self):
        self.assertEqual(machine.ocr_jobs(False, M(logical=6, total=0, avail=0)), 5)


class BudgetTests(unittest.TestCase):
    def test_page_cache(self):
        self.assertEqual(machine.page_cache_bytes(M(total=2 * GB, avail=1500 * MB)), 96 * MB)
        self.assertEqual(machine.page_cache_bytes(M(total=8 * GB, avail=4 * GB)), int(8 * GB / 24))
        self.assertEqual(machine.page_cache_bytes(M(total=64 * GB, avail=40 * GB)), 640 * MB)
        self.assertEqual(machine.page_cache_bytes(M(total=8 * GB, avail=512 * MB)), 96 * MB, "apertado")

    def test_thumbs(self):
        self.assertEqual(machine.thumb_cache_bytes(M(total=1 * GB)), 32 * MB)
        self.assertEqual(machine.thumb_cache_bytes(M(total=8 * GB)), 128 * MB)
        self.assertEqual(machine.thumb_cache_bytes(M(total=64 * GB)), 256 * MB)
        b = machine.thumb_disk_bytes(tempfile.gettempdir())
        self.assertTrue(32 * MB <= b <= 256 * MB)

    def test_threads(self):
        self.assertEqual(machine.onnx_threads(M(physical=2)), 2)
        self.assertEqual(machine.onnx_threads(M(physical=8)), 7)
        self.assertEqual(machine.thumb_threads(M(logical=2)), 1)
        self.assertEqual(machine.thumb_threads(M(logical=8)), 2)


class PriorityTests(unittest.TestCase):
    def test_ocr_process_and_children_below_normal(self):
        """O processo do OCR fica abaixo do normal, e o que ele abre (o tesseract) também."""
        if sys.platform == "win32":
            probe = ("import ctypes; k=ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype=ctypes.c_void_p; "
                     "k.GetPriorityClass.argtypes=[ctypes.c_void_p]; print(k.GetPriorityClass(k.GetCurrentProcess()))")
            expected = str(machine.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            probe = "import os; print(os.nice(0))"
            expected = None
        code = (f"import sys; sys.path.insert(0, {str(ROOT / 'app')!r}); import machine, ocr_worker, subprocess; "
                f"assert machine.lower_priority(); ocr_worker._no_console_windows(); "
                f"print(subprocess.run([sys.executable, '-c', {probe!r}], capture_output=True, text=True).stdout.strip())")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        if expected is not None:
            self.assertEqual(out.stdout.strip(), expected)
        else:
            self.assertGreaterEqual(int(out.stdout.strip()), 5)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_mach_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_is_native_qt_format_and_same_pixels(self):
        import pypdfium2 as pdfium

        import services
        for path in (digital_pdf(self.tmp / "d.pdf", 1), scanned_pdf(self.tmp / "s.pdf", 1)):
            img = services.render_page(path, 0, 400)
            self.assertEqual(img.format(), QImage.Format_RGB32)
            doc = pdfium.PdfDocument(str(path))
            pil = doc[0].render(scale=400 / doc[0].get_width(), rev_byteorder=True).to_pil().convert("RGB")
            doc.close()
            self.assertEqual((img.width(), img.height()), pil.size)
            for x, y in ((10, 10), (img.width() // 2, img.height() // 3), (img.width() - 5, img.height() - 5)):
                c = img.pixelColor(x, y)
                self.assertEqual((c.red(), c.green(), c.blue()), pil.getpixel((x, y)), (x, y))

    def test_newest_request_runs_first(self):
        """QThreadPool com prioridade crescente: o pedido mais recente sai primeiro (rolagem rápida)."""
        order, gate = [], [False]

        class Job(QRunnable):
            def __init__(self, n):
                super().__init__()
                self.n = n

            def run(self):
                if self.n == 0:
                    while not gate[0]:
                        time.sleep(0.01)
                order.append(self.n)

        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        pool.start(Job(0), 0)
        time.sleep(0.1)
        for n, prio in ((1, 1), (2, 2), (3, 2), (4, 3)):
            pool.start(Job(n), prio)
        gate[0] = True
        pool.waitForDone(5000)
        self.assertEqual(order, [0, 4, 2, 3, 1], "mais recente primeiro; mesma pintura, na ordem pedida")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_cache_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_px_bucket_and_keys(self):
        import services
        self.assertEqual(services.px_bucket(100), 112)
        self.assertEqual(services.px_bucket(187), 192)
        self.assertEqual(services.px_bucket(600), 640)
        self.assertEqual({services.px_bucket(px) for px in range(181, 193)}, {192},
                         "redimensionar a janela pixel a pixel não pede miniatura nova")
        k1 = services.Thumbnails.key("a.pdf", "v", 0, 185)
        k2 = services.Thumbnails.key("a.pdf", "v", 0, 190)
        self.assertEqual(k1, k2)

    def test_thumbnails_budget_and_best(self):
        import services
        t = services.Thumbnails(self.tmp, budget=1 * MB)
        t.KEEP_MIN = 3
        img = QImage(200, 300, QImage.Format_RGB32)          # 240 KB
        img.fill(0xFFFFFFFF)
        for page in range(10):
            t._done(t.key("a.pdf", "v", page, 200), img.copy())
        self.assertLessEqual(t.used, 1 * MB)
        self.assertEqual(t.used, sum(i.sizeInBytes() for i in t.mem.values()))
        self.assertTrue(all(any(b is v for v in t.mem.values()) for b in t.best.values()))
        # pedido de outro tamanho para uma página já pronta: devolve a que existe enquanto desenha a nova
        got = t.get("a.pdf", "v", 9, 600)
        self.assertIsNotNone(got)
        t.pool.clear()
        t.pool.waitForDone(5000)

    def test_page_cache_budget_keeps_visible_pages(self):
        import reader
        pdf = digital_pdf(self.tmp / "p.pdf", 8)
        c = reader.PageCache(pdf, budget=1)                    # nada cabe: sobram as KEEP_MIN mais recentes
        for i in range(8):
            c.get(i, 300)
        self.assertTrue(wait(lambda: not c.pending, 60))
        self.assertEqual(len(c.mem), reader.PageCache.KEEP_MIN)
        self.assertEqual(sorted(k[0] for k in c.mem), sorted(k[0] for k in list(c.mem)[-4:]))
        self.assertEqual(c.used, sum(i.sizeInBytes() for i in c.mem.values()))
        c.shutdown()

    def test_page_cache_skips_pages_no_longer_on_screen(self):
        import reader
        pdf = digital_pdf(self.tmp / "q.pdf", 2)
        c = reader.PageCache(pdf, budget=64 * MB)
        ready = []
        c.ready.connect(ready.append)
        c.wanted[(0, 320)] = time.monotonic() - 10            # pedida há 10 s e não mais
        job = reader._Render(c.path, 0, 320, c.signals, None, c.generation, c.wanted)
        c.pending.add((0, 320))
        job.run()
        self.assertTrue(wait(lambda: ready, 10))
        self.assertNotIn((0, 320), c.pending)
        self.assertNotIn((0, 320), c.mem, "não desenhou a página que saiu da tela")
        c.shutdown()

    def test_prune_thumb_cache(self):
        import services
        old = time.time() - 200 * 86400
        for i in range(5):                                    # antigas: saem
            f = self.tmp / f"old{i}.png"
            f.write_bytes(b"x" * 1000)
            os.utime(f, (old, old))
        for i in range(10):                                   # recentes, 10 KB cada
            f = self.tmp / f"new{i}.png"
            f.write_bytes(b"x" * 10_000)
            t = time.time() - (10 - i) * 60
            os.utime(f, (t, t))
        removed, _ = services.prune_thumb_cache(self.tmp, budget=200_000)
        self.assertEqual(removed, 5)
        self.assertEqual(len(list(self.tmp.glob("*.png"))), 10)
        removed, _ = services.prune_thumb_cache(self.tmp, budget=80_000)   # passou do limite: desce a 3/4
        left = sorted(p.name for p in self.tmp.glob("*.png"))
        self.assertEqual(len(left), 6)
        self.assertEqual(left, [f"new{i}" + ".png" for i in range(4, 10)], "ficam as mais recentes")


class LibraryScanTests(unittest.TestCase):
    def test_reload_fingerprint_matches_scan(self):
        from library import Library
        tmp = Path(tempfile.mkdtemp(prefix="prumo_scan_"))
        try:
            root = tmp / "Biblioteca"
            digital_pdf(root / "b.pdf", 1)
            digital_pdf(root / "Pasta" / "a.pdf", 1)
            digital_pdf(root / "Pasta" / "Sub" / "c.pdf", 1)
            lib = Library(root, local_dir=tmp / "local")
            self.assertEqual(lib._tree, lib._scan_tree(), "uma passada pela pasta basta")
            self.assertFalse(lib.reload_if_changed())
            digital_pdf(root / "Pasta" / "d.pdf", 1)
            self.assertTrue(lib.reload_if_changed())
            self.assertEqual(lib._tree, lib._scan_tree())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
