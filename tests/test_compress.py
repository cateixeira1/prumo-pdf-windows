"""Comprimir PDF (média e alta): tamanho, qualidade preservada no que importa e casos que não podem mudar."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compress  # noqa: E402
from fixtures import digital_pdf  # noqa: E402


def _scan_a4(path: Path, pages: int = 2, dpi: int = 300, color: bool = True) -> Path:
    """Escaneado típico: páginas A4 com imagem JPEG de 300 dpi."""
    import img2pdf
    import pypdfium2 as pdfium

    src = digital_pdf(path.with_name(path.stem + "_src.pdf"), pages)
    doc = pdfium.PdfDocument(str(src))
    imgs = []
    for i in range(len(doc)):
        im = doc[i].render(scale=dpi / 72).to_pil().convert("RGB" if color else "L")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=92, dpi=(dpi, dpi))
        imgs.append(buf.getvalue())
    doc.close()
    src.unlink()
    a4 = img2pdf.get_layout_fun((img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)))
    path.write_bytes(img2pdf.convert(imgs, layout_fun=a4))
    return path


def _images(path):
    import pikepdf
    with pikepdf.open(str(path)) as pdf:
        return [(int(o.Width), int(o.Height), str(o.get("/Filter")), "/SMask" in o)
                for o in pdf.objects
                if isinstance(o, pikepdf.Stream) and o.get("/Subtype") == pikepdf.Name.Image
                and o.objgen not in {x.get("/SMask").objgen for x in pdf.objects
                                     if isinstance(x, pikepdf.Stream) and "/SMask" in x}]


def test_scan_medium_and_high(tmp_path):
    src = _scan_a4(tmp_path / "scan.pdf", 2)
    med = compress.compress(src, tmp_path / "m.pdf", "medium")
    high = compress.compress(src, tmp_path / "h.pdf", "high")
    assert med.after < med.before * 0.5          # 300 → 150 dpi: bem menor
    assert high.after < med.after                # alta reduz mais que a média
    assert med.images_changed == 2 and high.images_changed == 2
    # A4 = 8,27 pol: 150 dpi ≈ 1240 px; 96 dpi ≈ 794 px de largura
    for w, _h, flt, _ in _images(tmp_path / "m.pdf"):
        assert 1200 <= w <= 1280 and flt == "/DCTDecode"
    for w, _h, _f, _ in _images(tmp_path / "h.pdf"):
        assert 760 <= w <= 830
    import pypdfium2 as pdfium
    for name in ("m.pdf", "h.pdf"):
        doc = pdfium.PdfDocument(str(tmp_path / name))
        assert len(doc) == 2
        doc[1].render(scale=0.5)                 # abre e desenha
        doc.close()


def test_text_and_annotations_kept(tmp_path):
    """PDF com texto e destaque: o texto continua selecionável e o destaque continua lá."""
    import pikepdf
    import pypdfium2 as pdfium

    src = digital_pdf(tmp_path / "d.pdf", 2)
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        annot = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Highlight, Rect=[50, 700, 300, 720],
            QuadPoints=[50, 720, 300, 720, 50, 700, 300, 700], C=[1, 1, 0]))
        pdf.pages[0].obj.Annots = pdf.make_indirect(pikepdf.Array([annot]))
        pdf.save(str(src))
    r = compress.compress(src, tmp_path / "out.pdf", "high")
    assert r.after <= r.before
    doc = pdfium.PdfDocument(str(tmp_path / "out.pdf"))
    text = doc[0].get_textpage().get_text_range()
    assert "INDENIZAÇÃO" in text
    doc.close()
    with pikepdf.open(str(tmp_path / "out.pdf")) as pdf:
        annots = pdf.pages[0].obj.get("/Annots")
        assert annots is not None and str(annots[0].Subtype) == "/Highlight"


def test_alpha_image_keeps_mask_same_size(tmp_path):
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (2400, 1600), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k in range(0, 2400, 7):
        d.line([(k, 0), (2400 - k, 1600)], fill=(k % 255, (k * 3) % 255, 200, 180), width=3)
    im.save(tmp_path / "a.png")
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(tmp_path / "a.png"), x=10, y=10, w=80)   # 80 mm: muito acima de 150 dpi
    pdf.output(str(tmp_path / "a.pdf"))
    compress.compress(tmp_path / "a.pdf", tmp_path / "o.pdf", "medium")
    import pikepdf
    with pikepdf.open(str(tmp_path / "o.pdf")) as p:
        img = next(o for o in p.objects if isinstance(o, pikepdf.Stream) and "/SMask" in o)
        assert (int(img.Width), int(img.Height)) == (int(img.SMask.Width), int(img.SMask.Height))
        # 80 mm = 3,15 pol; 150 dpi ≈ 472 px
        assert 450 <= int(img.Width) <= 500


def test_screenshot_like_image_stays_lossless(tmp_path):
    """Imagem com poucas cores (captura de tela, gráfico) não vira JPEG: as letras não borram."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (3000, 2000), "white")
    d = ImageDraw.Draw(im)
    for y in range(0, 2000, 40):
        d.rectangle([100, y, 2900, y + 18], fill=(30, 60, 200) if y % 80 else (0, 0, 0))
    im.save(tmp_path / "s.png")
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(tmp_path / "s.png"), x=10, y=10, w=190)
    pdf.output(str(tmp_path / "s.pdf"))
    compress.compress(tmp_path / "s.pdf", tmp_path / "o.pdf", "high")
    assert all(flt == "/FlateDecode" for _w, _h, flt, _ in _images(tmp_path / "o.pdf"))


def test_small_jpeg_left_alone_in_medium(tmp_path):
    """JPEG já em resolução baixa: a média não regrava (só perderia qualidade)."""
    src = _scan_a4(tmp_path / "low.pdf", 1, dpi=120)
    r = compress.compress(src, tmp_path / "o.pdf", "medium")
    assert r.images_changed == 0


def test_encrypted_is_refused(tmp_path):
    import pikepdf
    src = digital_pdf(tmp_path / "d.pdf", 1)
    with pikepdf.open(str(src)) as pdf:
        pdf.save(str(tmp_path / "e.pdf"), encryption=pikepdf.Encryption(owner="x", user="abc", R=6))
    with pytest.raises(compress.CompressError):
        compress.compress(tmp_path / "e.pdf", tmp_path / "o.pdf", "medium")


def test_progress_reports_each_image(tmp_path):
    src = _scan_a4(tmp_path / "scan.pdf", 3)
    seen = []
    compress.compress(src, tmp_path / "o.pdf", "medium", progress=lambda i, n: seen.append((i, n)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


# --- na interface: tela inicial, menu ⋮, tela do PDF e leitor ----------------------------

def _gui_window(tmp):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import ios_theme
    ios_theme.T.setup("light")
    from app_window import MainWindow
    from library import Library
    lib_root = tmp / "Biblioteca"
    lib_root.mkdir()
    _scan_a4(lib_root / "Laudo.pdf", 2)
    w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.IniFormat), Library(lib_root, local_dir=tmp / "local"))
    w.resize(1000, 760)
    w.show()
    return w


def _wait(cond, timeout=60.0):
    import time

    from PySide6.QtCore import QEventLoop, QTimer
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(40, loop.quit)
        loop.exec()
    return False


def _answer_sheet(w, level_title, seen):
    """Quando a folha abrir: anota os textos, escolhe o nível e clica em Comprimir."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QRadioButton

    from ios_kit import PrimaryButton, SheetOverlay

    def step():
        ov = next((o for o in w.findChildren(SheetOverlay) if o.isVisible()), None)
        if ov is None:
            QTimer.singleShot(100, step)
            return
        radios = ov.findChildren(QRadioButton)
        seen.extend(r.text() for r in radios)
        next(r for r in radios if r.text() == level_title).setChecked(True)
        seen.append(("checked", [r.text() for r in radios if r.isChecked()]))
        next(b for b in ov.findChildren(PrimaryButton) if b.title == "Comprimir").click()
    QTimer.singleShot(300, step)


def test_gui_compress_flows(tmp_path):
    import screens
    w = _gui_window(tmp_path)
    try:
        assert _wait(lambda: w.lib.items and all(i.meta.signature for i in w.lib.items))
        item = w.lib.items[0]
        before = item.path.stat().st_size
        # botão na tela inicial
        w.home()
        assert "compress" in w.current().tiles
        # linha no menu ⋮
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMenu
        texts = []

        def grab_menu():
            m = next((x for x in QApplication.topLevelWidgets() if isinstance(x, QMenu) and x.isVisible()), None)
            if m is None:
                QTimer.singleShot(100, grab_menu)
                return
            texts.extend(a.text() for a in m.actions())
            m.close()
        QTimer.singleShot(200, grab_menu)
        w.actions.context_menu(w.current(), item, w.current().rect().center())
        assert "Comprimir PDF…" in texts
        # o diálogo, em compressão alta
        seen = []
        _answer_sheet(w, "Compressão alta", seen)
        screens.compress_dialog(w, item)
        assert "Compressão média" in seen and "Compressão alta" in seen
        assert ("checked", ["Compressão alta"]) in seen
        copy = next((i for i in w.lib.items if i.name == "Laudo - comprimido"), None)
        assert copy is not None, [i.name for i in w.lib.items]
        assert copy.path.stat().st_size < before * 0.3
        assert item.path.stat().st_size == before, "o original não pode mudar"
        assert w.setting("compress_level") == "high", "a escolha fica lembrada"
        # comprimir de novo a cópia já comprimida: nada a ganhar, avisa e não cria outra cópia
        seen2, alerts = [], []
        _answer_sheet(w, "Compressão alta", seen2)
        old_alert = screens.alert
        screens.alert = lambda _w, title, *a, **k: alerts.append(title)
        try:
            n = len(w.lib.items)
            screens.compress_dialog(w, w.lib.item(copy.id))
        finally:
            screens.alert = old_alert
        assert alerts == ["O PDF já está compacto"]
        assert len(w.lib.items) == n
        import i18n
        assert i18n.strip_suffix("Laudo - comprimido", "{} - comprimido") == "Laudo"
        assert i18n.strip_suffix("Laudo - compressed", "{} - comprimido") == "Laudo"   # nome vindo de outro idioma
        # botão no leitor
        import reader
        r = reader.ReaderScreen(w, item.id)
        w.push(r)
        assert _wait(lambda: r.text is not None, 30)
        r.panel.update_state()
        assert r.panel.buttons["compress"].isEnabled()
        w.back(force=True)
    finally:
        w.hub.shutdown()
        w.close()


def test_gray_flate_scan_becomes_jpeg(tmp_path):
    """Escaneado em cinza gravado sem perda (Flate): tem muitos tons, então vira JPEG e reduz bastante."""
    import pypdfium2 as pdfium
    from fpdf import FPDF

    src = digital_pdf(tmp_path / "d.pdf", 1)
    doc = pdfium.PdfDocument(str(src))
    from PIL import Image
    page = doc[0].render(scale=300 / 72).to_pil().convert("L")
    noise = Image.effect_noise(page.size, 18).convert("L")            # grão do papel, como num escaneado
    Image.blend(page, noise, 0.12).save(tmp_path / "g.png")
    doc.close()
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.image(str(tmp_path / "g.png"), x=0, y=0, w=210, h=297)
    pdf.output(str(tmp_path / "gray.pdf"))
    r = compress.compress(tmp_path / "gray.pdf", tmp_path / "o.pdf", "medium")
    assert r.images_changed == 1 and r.after < r.before * 0.6
    assert [flt for _w, _h, flt, _ in _images(tmp_path / "o.pdf")] == ["/DCTDecode"]
