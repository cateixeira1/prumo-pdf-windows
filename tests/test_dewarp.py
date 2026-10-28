"""Testes da etapa 5: correção de páginas curvas com o modelo UVDoc (versão 1.6.0)."""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import digital_pdf  # noqa: E402


def text_page(width=1240, height=1754):
    """Página A4 (150 dpi) com texto corrido em português."""
    from PIL import Image, ImageDraw, ImageFont
    page = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(page)
    font = None
    for f in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            font = ImageFont.truetype(f, 30)
            break
    text = ("A autora foi internada para cirurgia eletiva e apresentou febre persistente, dor abdominal intensa e "
            "alteração dos sinais vitais, sem que a equipe adotasse as providências diagnósticas necessárias. ") * 6
    words, lines, cur = text.split(), [], ""
    for w in words:
        if d.textlength(cur + " " + w, font=font) > width - 200:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    y = 120
    for ln in lines[:36]:
        d.text((100, y), ln, fill="black", font=font)
        y += 42
    return page


def curved_photo(page, canvas=(1500, 2000), strength=0.06):
    """Simula a foto de uma página curvada perto da lombada, sobre um fundo escuro."""
    from PIL import Image
    W, H = page.size

    def src(u, v):
        bend = strength * math.sin(math.pi * u) * (0.6 + 0.4 * v)
        return (u - 0.06) / 0.88 * W, ((v - 0.05 - bend * (1 - u)) / 0.9) * H
    mesh, G = [], 40
    for i in range(G):
        for j in range(G):
            u0, u1, v0, v1 = j / G, (j + 1) / G, i / G, (i + 1) / G
            box = (round(u0 * canvas[0]), round(v0 * canvas[1]), round(u1 * canvas[0]), round(v1 * canvas[1]))
            mesh.append((box, (*src(u0, v0), *src(u0, v1), *src(u1, v1), *src(u1, v0))))
    return page.transform(canvas, Image.MESH, mesh, resample=Image.BICUBIC, fillcolor=(120, 110, 100))


def good_ocr_words(img, tmp: Path) -> tuple[int, int]:
    import core
    tess = core.find_tesseract()
    if tess is None:
        raise unittest.SkipTest("Tesseract não encontrado")
    p = tmp / "ocr.png"
    img.save(p)
    out = subprocess.run([str(tess), str(p), "-", "-l", "por", "tsv"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    rows = [r.split("\t") for r in out.splitlines()[1:] if r.count("\t") >= 11]
    words = [r for r in rows if r[11].strip()]
    return sum(1 for r in words if float(r[10]) >= 80), len(words)


class DewarpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dewarp
        if not dewarp.available():
            raise unittest.SkipTest("modelo UVDoc ou onnxruntime ausente")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_dewarp_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_grid_shape_and_range(self):
        import dewarp
        g = dewarp.predict_grid(curved_photo(text_page()))
        self.assertEqual(g.shape, (2, 45, 31))
        self.assertTrue(-1.2 < float(g.min()) and float(g.max()) < 1.2)

    def test_curved_page_reads_better_after_correction(self):
        import dewarp
        photo = curved_photo(text_page())
        fixed = dewarp.unwarp(photo)
        self.assertEqual(fixed.size, photo.size)
        good_before, total_before = good_ocr_words(photo, self.tmp)
        good_after, total_after = good_ocr_words(fixed, self.tmp)
        print(f"OCR antes: {good_before}/{total_before} palavras confiáveis; depois: {good_after}/{total_after}")
        self.assertGreater(good_after, good_before)
        self.assertGreaterEqual(good_after / max(1, total_after), 0.9)

    def test_dewarp_pdf_only_touches_chosen_pages(self):
        import img2pdf
        import pikepdf
        import pypdf

        import dewarp
        import pdfops
        digital = digital_pdf(self.tmp / "d.pdf", 2)
        buf = io.BytesIO()
        curved_photo(text_page()).save(buf, "JPEG", quality=90)
        src = self.tmp / "misto.pdf"
        with pikepdf.open(digital) as a, pikepdf.open(io.BytesIO(img2pdf.convert([buf.getvalue()]))) as b, \
                pikepdf.new() as out:
            out.pages.extend([a.pages[0], b.pages[0], a.pages[1]])
            out.save(src)
        dest = self.tmp / "corrigido.pdf"
        steps = []
        n = dewarp.dewarp_pdf(src, dest, pages=[2], progress=lambda i, t, name: steps.append((i, t)))
        self.assertEqual(n, 1)
        self.assertEqual(steps, [(1, 1)])
        self.assertEqual(pdfops.page_count(dest), 3)
        r = pypdf.PdfReader(str(dest))
        self.assertIn("sepse", r.pages[0].extract_text() or "", "as páginas não escolhidas mantêm o texto")
        self.assertIn("sepse", r.pages[2].extract_text() or "")
        w0, h0 = pypdf.PdfReader(str(src)).pages[1].mediabox.width, pypdf.PdfReader(str(src)).pages[1].mediabox.height
        self.assertAlmostEqual(float(r.pages[1].mediabox.width), float(w0), delta=1)
        self.assertAlmostEqual(float(r.pages[1].mediabox.height), float(h0), delta=1)

    def test_convert_photos_with_correction(self):
        import convert
        p = self.tmp / "livro.jpg"
        curved_photo(text_page()).save(p, quality=90)
        res = convert.convert([p], work_dir=self.tmp / "conv", dewarp_photos=True)
        self.assertEqual(res.failed, [])
        self.assertEqual(len(res.created), 1)


if __name__ == "__main__":
    unittest.main()
