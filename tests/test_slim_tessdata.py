"""O enxugamento dos modelos (build/slim_tessdata.py) não pode mudar o texto reconhecido.

No CI o build guarda os modelos originais em tessdata_full; aqui o OCR roda com os originais e com os
enxutos, nos idiomas mais usados, e o texto tem de sair idêntico."""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(Path(__file__).parent))

import slim_tessdata  # noqa: E402


def _tesseract() -> str | None:
    from app import core

    return core.find_tesseract()


class SlimFormatTests(unittest.TestCase):
    def test_keeps_lstm_and_config_drops_the_rest(self):
        parts = {0: b"cfg", 1: b"unicharset", 13: b"S" * 5000, 17: b"L" * 3000, 18: b"a", 19: b"b",
                 20: b"c", 21: b"d", 22: b"rec", 23: b"v"}
        data = slim_tessdata.build(24, parts)
        out = slim_tessdata.slim_bytes(data)
        _, kept = slim_tessdata.parse(out)
        self.assertEqual(sorted(kept), [0, 17, 18, 19, 20, 21, 22, 23])
        self.assertLess(len(out), len(data))
        self.assertEqual(slim_tessdata.slim_bytes(out), out)         # rodar de novo não muda nada

    def test_file_without_lstm_is_untouched(self):
        data = slim_tessdata.build(24, {0: b"a", 1: b"b"})
        self.assertEqual(slim_tessdata.slim_bytes(data), data)


class SlimOcrEquivalenceTests(unittest.TestCase):
    def test_same_text_with_full_and_slim_models(self):
        full = ROOT / "tessdata_full"
        slim = ROOT / "tessdata"
        exe = _tesseract()
        if not full.is_dir() or not exe:
            self.skipTest("modelos originais (tessdata_full) ou Tesseract ausentes")
        import tempfile

        import pypdfium2 as pdfium
        from fixtures import digital_pdf

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pdf = digital_pdf(tmp / "a.pdf", pages=1)
            doc = pdfium.PdfDocument(str(pdf))
            png = tmp / "a.png"
            doc[0].render(scale=200 / 72).to_pil().convert("L").save(png)
            doc.close()
            checked = 0
            for lang in ("por", "eng"):
                if not (full / f"{lang}.traineddata").exists():
                    continue
                for oem in ("1", "3"):
                    texts = []
                    for folder in (full, slim):
                        r = subprocess.run([exe, str(png), "stdout", "--tessdata-dir", str(folder), "-l", lang,
                                            "--oem", oem, "--psm", "6"], capture_output=True, timeout=240)
                        self.assertEqual(r.returncode, 0, r.stderr.decode(errors="replace"))
                        texts.append(r.stdout.decode("utf-8", errors="replace"))
                    self.assertTrue(texts[0].strip(), f"OCR sem texto ({lang}, oem {oem})")
                    self.assertEqual(texts[0], texts[1], f"o texto mudou com o modelo enxuto ({lang}, oem {oem})")
                    checked += 1
            self.assertGreater(checked, 0)
            # e o arquivo enxuto é de fato menor
            self.assertLess((slim / "por.traineddata").stat().st_size, (full / "por.traineddata").stat().st_size)


if __name__ == "__main__":
    unittest.main()
