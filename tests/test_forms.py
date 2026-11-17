"""Preencher formulários: campos AcroForm, caixas de texto e marcas, achatar ("Finalizar") e a tela."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import forms  # noqa: E402
from fixtures import digital_pdf, form_pdf  # noqa: E402

VALUES = {"nome": "Caio Fernandes Teixeira", "obs": "Paciente relata dor abdominal há três dias. " * 3,
          "cpf": "12345678901", "valor": "R$ 1.234,56", "aceito": True, "sexo": "M", "estado": "RJ",
          "cor": "Verde", "cidade": "São Paulo"}


def _filled(tmp_path, boxes=None) -> Path:
    src = form_pdf(tmp_path / "ficha.pdf")
    out = tmp_path / "preenchido.pdf"
    shutil.copy(src, out)
    forms.save(out, VALUES, boxes or [])
    return out


def _text(path, page=0) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        p = pdf[page]
        tp = p.get_textpage()
        return tp.get_text_range()
    finally:
        pdf.close()


def _render(path, page=0, forms_on=True):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    if forms_on:
        pdf.init_forms()
    try:
        return pdf[page].render(scale=1.0, may_draw_forms=forms_on).to_pil().convert("L")
    finally:
        pdf.close()


def test_reads_every_field_type(tmp_path):
    d = forms.load(form_pdf(tmp_path / "f.pdf"))
    kinds = {f.name: f.kind for f in d.fields}
    assert kinds == {"nome": "text", "obs": "text", "cpf": "text", "valor": "text", "aceito": "check",
                     "sexo": "radio", "estado": "combo", "cor": "list", "cidade": "text"}
    f = {x.name: x for x in d.fields}
    assert f["obs"].multiline and f["obs"].size == 10 and f["obs"].color == (0.0, 0.0, 1.0)
    assert f["cpf"].comb and f["cpf"].maxlen == 11
    assert f["valor"].align == 2
    assert [o for o, _ in f["sexo"].options] == ["F", "M"]
    assert f["estado"].options[1] == ("RJ", "Rio de Janeiro")
    assert f["cidade"].widgets[0].page == 1
    assert d.boxes == [] and not d.xfa


def test_values_are_saved_in_the_fields(tmp_path):
    import pypdf
    out = _filled(tmp_path)
    got = {k: v.get("/V") for k, v in pypdf.PdfReader(str(out), strict=True).get_fields().items()}
    assert got["nome"] == "Caio Fernandes Teixeira"
    assert got["aceito"] == "/Yes" and got["sexo"] == "/M"
    assert got["estado"] == "RJ" and got["cor"] == "Verde" and got["cidade"] == "São Paulo"
    assert {f.name: f.value for f in forms.load(out).fields} == VALUES


def test_appearance_shows_the_value_in_any_reader(tmp_path):
    """O valor fica desenhado na aparência do campo (o leitor não precisa redesenhar)."""
    import pikepdf
    out = _filled(tmp_path)
    with pikepdf.open(str(out)) as pdf:
        assert not pdf.Root.AcroForm.get("/NeedAppearances", False)
        for name in ("nome", "cidade"):
            fld = next(f for f in pdf.Root.AcroForm.Fields if str(f.get("/T")) == name)
            data = fld.AP.N.read_bytes()
            assert b"Tj" in data and fld.AP.N.Resources.Font.F1.Encoding == "/WinAnsiEncoding"
        nome = next(f for f in pdf.Root.AcroForm.Fields if str(f.get("/T")) == "cidade")
        assert "S\xe3o Paulo".encode("cp1252") in nome.AP.N.read_bytes()
    # pdfium com os formulários ligados desenha a página com o texto preenchido
    before = _render(tmp_path / "ficha.pdf")
    after = _render(out)
    assert before.tobytes() != after.tobytes()


def test_boxes_round_trip_and_stay_editable(tmp_path):
    boxes = [forms.Box(0, 300, 120, text="Nome: Caio\nOAB/SP 483.995", size=14, bold=True, color="blue"),
             forms.Box(0, 420, 120, kind="check", size=16),
             forms.Box(1, 100, 300, kind="cross", size=20, color="red"),
             forms.Box(1, 200, 200, text="Times €", font="times", size=18)]
    out = _filled(tmp_path, boxes)
    back = forms.load(out).boxes
    assert [(b.page, round(b.x, 2), round(b.y, 2), b.kind, b.text, b.font, b.bold, b.size, b.color) for b in back] == \
        [(0, 300.0, 120.0, "text", "Nome: Caio\nOAB/SP 483.995", "helvetica", True, 14.0, "blue"),
         (0, 420.0, 120.0, "check", "", "helvetica", False, 16.0, "black"),
         (1, 100.0, 300.0, "cross", "", "helvetica", False, 20.0, "red"),
         (1, 200.0, 200.0, "text", "Times €", "times", False, 18.0, "black")]
    assert all(b.id.startswith(("prumo-tx-", "prumo-mk-")) for b in back)
    # gravar de novo troca as caixas (não duplica); apagar uma tira do PDF
    forms.save(out, VALUES, back[1:])
    assert len(forms.load(out).boxes) == 3
    # é uma anotação de texto padrão, com aparência pronta
    import pikepdf
    with pikepdf.open(str(out)) as pdf:
        ft = [a for p in pdf.pages for a in p.get("/Annots", []) if a.get("/Subtype") == "/FreeText"]
        assert len(ft) == 3 and all("/AP" in a and "/DA" in a for a in ft)


def test_flatten_makes_everything_part_of_the_page(tmp_path):
    import pikepdf
    out = _filled(tmp_path, [forms.Box(0, 300, 120, text="Escrito à mão", size=14)])
    flat = tmp_path / "final.pdf"
    n = forms.flatten(out, flat)
    assert n >= 10
    with pikepdf.open(str(flat)) as pdf:
        assert "/AcroForm" not in pdf.Root
        assert not [a for p in pdf.pages for a in p.get("/Annots", []) if a.get("/Subtype") in ("/Widget", "/FreeText")]
    assert forms.load(flat).fields == [] and forms.load(flat).boxes == []
    # a página achatada (sem formulários) fica igual à preenchida com os formulários ligados
    a = _render(out, forms_on=True)
    b = _render(flat, forms_on=False)
    diff = sum(1 for x, y in zip(a.tobytes(), b.tobytes()) if abs(x - y) > 60)
    assert diff < a.width * a.height * 0.002, diff
    text = _text(flat)
    assert "Caio Fernandes Teixeira" in text and "Escrito à mão" in text


def test_flatten_keeps_highlights(tmp_path):
    import annotations
    out = _filled(tmp_path)
    annotations.add_to_file(out, [(0, [(60, 760, 300, 775)], "yellow", "trecho")])
    flat = tmp_path / "final.pdf"
    forms.flatten(out, flat)
    assert annotations.read_marks(flat)[0][0].text == "trecho"


def test_rotated_pages_keep_text_upright(tmp_path):
    for rot in (90, 180, 270):
        src = form_pdf(tmp_path / f"r{rot}.pdf", rotate=rot)
        out = tmp_path / f"r{rot}_f.pdf"
        shutil.copy(src, out)
        forms.save(out, {}, [forms.Box(0, 50, 50, text="Em pé", size=16), forms.Box(0, 50, 90, kind="check")])
        back = forms.load(out).boxes
        assert [(round(b.x, 1), round(b.y, 1)) for b in back] == [(50.0, 50.0), (50.0, 90.0)]
        flat = tmp_path / f"r{rot}_flat.pdf"
        forms.flatten(out, flat)
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(flat))
        img = pdf[0].render(scale=1.0).to_pil().convert("L")
        pdf.close()
        # o texto fica perto do canto de cima à esquerda da página como ela aparece
        crop = img.crop((40, 40, 140, 75))
        assert min(crop.tobytes()) < 100, rot


def test_page_geometry_round_trip():
    for rot in (0, 90, 180, 270):
        g = forms.PageGeo((10.0, 20.0, 610.0, 820.0), rot)
        for u, v in ((0, 0), (100, 50), (300.5, 700.25)):
            x, y = g.to_pdf(u, v)
            assert g.to_display(x, y) == pytest.approx((u, v))


def test_text_outside_winansi_is_reported_and_dropped():
    assert forms.unsupported("Ação 日本 €") == "日本"
    assert forms.clean("Ação 日本 €") == "Ação  €"
    w, h = forms.box_size("Linha 1\nLinha 2", "helvetica", False, 12)
    assert h == pytest.approx(2 * 12 * forms.LINE + 2 * forms.BOX_PAD)
    assert w > forms.text_width("Linha 1", "helvetica", False, 12)


def test_pdf_without_fields_and_xfa(tmp_path):
    d = forms.load(digital_pdf(tmp_path / "p.pdf", 1))
    assert d.fields == [] and not d.xfa_only
    import pikepdf
    src = form_pdf(tmp_path / "x.pdf")
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm.XFA = pikepdf.Array([pikepdf.String("template"), pdf.make_stream(b"<xdp/>")])
        pdf.save(str(src))
    d = forms.load(src)
    assert d.xfa and not d.xfa_only
    out = tmp_path / "x2.pdf"
    shutil.copy(src, out)
    forms.save(out, {"nome": "Teste"}, [])
    with pikepdf.open(str(out)) as pdf:
        assert "/XFA" not in pdf.Root.AcroForm   # senão os leitores mostram o XFA, sem o valor novo


def test_base_copy_hides_only_editable_parts(tmp_path):
    import pikepdf
    import annotations
    out = _filled(tmp_path, [forms.Box(0, 300, 120, text="caixa")])
    annotations.add_to_file(out, [(0, [(60, 760, 300, 775)], "yellow", "")])
    base = tmp_path / "base.pdf"
    forms.make_base(out, base)
    with pikepdf.open(str(base)) as pdf:
        subs = [str(a.get("/Subtype")) for p in pdf.pages for a in p.get("/Annots", [])]
    assert subs == ["/Highlight"]


# --- na interface ---------------------------------------------------------------------

def _gui(tmp):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import ios_theme
    ios_theme.T.setup("light")
    from app_window import MainWindow
    from library import Library
    root = tmp / "Biblioteca"
    root.mkdir()
    form_pdf(root / "Ficha.pdf")
    digital_pdf(root / "Papel.pdf", 1)
    w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.IniFormat), Library(root, local_dir=tmp / "local"))
    w.resize(1100, 860)
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


def _type(widget, text):
    """Digita como o teclado (QTest.keyClicks só aceita ASCII)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    for ch in text:
        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(kind, Qt.Key_unknown, Qt.NoModifier, ch))


def test_gui_fill_save_undo_and_finalize(tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    import forms_ui
    w = _gui(tmp_path)
    try:
        assert _wait(lambda: len(w.lib.items) == 2 and all(i.meta.signature for i in w.lib.items))
        item = next(i for i in w.lib.items if i.name == "Ficha")
        w.home()
        assert w.current().fill.title == "Preencher formulário"   # cartão na tela inicial
        s = forms_ui.open_form(w, item)
        assert isinstance(w.current(), forms_ui.FormScreen) and s.tool == "select"
        _wait(lambda: False, 0.5)
        line = next(x for x in s.view.widgets if isinstance(x, forms_ui._LineField) and x.field.name == "nome")
        line.setFocus()
        _type(line, "Maria Ação")
        line.editingFinished.emit()
        assert s.values["nome"] == "Maria Ação" and s.dirty
        chk = next(x for x in s.view.widgets if isinstance(x, forms_ui._Toggle) and x.field.kind == "check")
        chk.click()
        radio = [x for x in s.view.widgets if isinstance(x, forms_ui._Toggle) and x.field.kind == "radio"]
        radio[0].click()
        assert s.values["aceito"] is True and s.values["sexo"] == "F"
        radio[1].click()
        assert s.values["sexo"] == "M"
        # letra que a fonte do PDF não tem: some e avisa
        _type(line, "日")
        assert s.values["nome"] == "Maria Ação"
        # caixa de texto livre
        s.set_tool("text")
        r = s.view.page_rect(0)
        sc = s.view.scale(0)
        QTest.mouseClick(s.view, Qt.LeftButton, pos=r.topLeft().toPoint() + QPoint(int(400 * sc), int(100 * sc)))
        assert s.view.editor is not None
        _type(s.view.editor, "Assinatura")
        s.set_style(bold=True, color="red", size=14.0)
        s.view.finish_edit()
        assert [(b.text, b.bold, b.color, b.size) for b in s.boxes] == [("Assinatura", True, "red", 14.0)]
        # marca ✓ e desfazer/refazer
        s.set_tool("check")
        QTest.mouseClick(s.view, Qt.LeftButton, pos=r.topLeft().toPoint() + QPoint(int(500 * sc), int(100 * sc)))
        assert [b.kind for b in s.boxes] == ["text", "check"]
        s.undo()
        assert [b.kind for b in s.boxes] == ["text"]
        s.redo()
        assert [b.kind for b in s.boxes] == ["text", "check"]
        # arrastar a caixa
        b = s.boxes[0]
        x0 = b.x
        start = s.view.box_rect(b).center().toPoint()
        QTest.mousePress(s.view, Qt.LeftButton, pos=start)
        QTest.mouseMove(s.view, start + QPoint(40, 0))
        QTest.mouseRelease(s.view, Qt.LeftButton, pos=start + QPoint(40, 0))
        assert b.x > x0 + 10
        # apagar a caixa escolhida
        s.view.select(s.boxes[1])
        s.delete_selected()
        assert [b.kind for b in s.boxes] == ["text"]
        # salvar: grava no PDF e a tela do PDF ganha "Desfazer última alteração"
        assert s.save()
        assert not s.dirty
        saved = forms.load(w.lib.item(item.id).path)
        assert {f.name: f.value for f in saved.fields}["nome"] == "Maria Ação"
        assert [bx.text for bx in saved.boxes] == ["Assinatura"]
        assert w.lib.can_undo(w.lib.item(item.id))
        assert forms_ui.json.loads(w.setting("form_style"))["color"] == "red"   # lembra a formatação
        # finalizar: cópia achatada, original continua editável
        import ios_kit
        old = forms_ui.alert
        forms_ui.alert = lambda *a, **k: 0
        try:
            s.finalize()
        finally:
            forms_ui.alert = old
        final = next((i for i in w.lib.items if i.name == "Ficha - preenchido"), None)
        assert final is not None, [i.name for i in w.lib.items]
        assert forms.load(final.path).fields == []
        assert forms.load(w.lib.item(item.id).path).fields
        # sair com mudança não salva pergunta (aqui: descartar)
        s.values["nome"] = "Outra"
        forms_ui.alert = lambda *a, **k: 1
        try:
            w.back()
        finally:
            forms_ui.alert = old
        assert not isinstance(w.current(), forms_ui.FormScreen)
        assert {f.name: f.value for f in forms.load(w.lib.item(item.id).path).fields}["nome"] == "Maria Ação"
        _ = ios_kit
        # PDF sem campos: começa na ferramenta de texto
        papel = next(i for i in w.lib.items if i.name == "Papel")
        s2 = forms_ui.open_form(w, papel)
        assert s2.tool == "text" and not s2.view.widgets
        w.back(force=True)
        # leitor e menu ⋮ têm a função
        import reader
        rd = reader.ReaderScreen(w, item.id)
        w.push(rd)
        assert _wait(lambda: rd.text is not None, 30)
        rd.panel.update_state()
        assert rd.panel.buttons["fill"].isEnabled()
        w.back(force=True)
    finally:
        w.hub.shutdown()
        w.close()


def test_signed_or_locked_pdf_is_refused(tmp_path):
    import forms_ui
    w = _gui(tmp_path)
    try:
        assert _wait(lambda: len(w.lib.items) == 2 and all(i.meta.signature for i in w.lib.items))
        item = next(i for i in w.lib.items if i.name == "Ficha")
        toasts = []
        w.toast = lambda text, *a, **k: toasts.append(text)
        item.meta.signed = 1
        assert forms_ui.open_form(w, item) is None
        item.meta.signed = 0
        item.meta.locked = True
        assert forms_ui.open_form(w, item) is None
        assert len(toasts) == 2
    finally:
        w.hub.shutdown()
        w.close()


def test_boxes_made_on_the_iphone_are_read_and_replaced(tmp_path):
    """O iPhone grava a caixa de texto como /FreeText (o PDFKit pode não guardar o /PrumoStyle: vale o /DA) e as
    marcas como traços (/Ink) com /NM "prumo-mk-"."""
    import pikepdf
    src = digital_pdf(tmp_path / "p.pdf", 1)
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        page.obj.Annots = pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FreeText, Rect=[100, 700, 220, 720],
                NM=pikepdf.String("prumo-tx-aaaaaaaaaaaaaaaa"), Contents=pikepdf.String("Feito no iPhone"),
                DA=pikepdf.String("/Helvetica-Bold 14 Tf 0.05 0.2 0.62 rg"))),
            pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Ink, Rect=[300, 700, 320, 720],
                NM=pikepdf.String("prumo-mk-bbbbbbbbbbbbbbbb"), Contents=pikepdf.String("✗"),
                InkList=[[304, 704, 316, 716]])),
        ])
        pdf.save(str(src))
    boxes = forms.load(src).boxes
    assert [(b.kind, b.text, b.bold, b.size, b.color) for b in boxes] == [
        ("text", "Feito no iPhone", True, 14.0, "blue"), ("cross", "", False, 20.0, "black")]
    forms.save(src, {}, boxes)
    with pikepdf.open(str(src)) as pdf:
        subs = [str(a.Subtype) for a in pdf.pages[0].Annots]
    assert subs == ["/FreeText", "/FreeText"]          # trocadas pela forma do Windows, sem duplicar
    assert [b.id for b in forms.load(src).boxes] == ["prumo-tx-aaaaaaaaaaaaaaaa", "prumo-mk-bbbbbbbbbbbbbbbb"]


def test_pdf_saved_by_the_iphone(tmp_path):
    """PDF de verdade gravado pelo PDFKit no iPhone (teste FormTests, CI de 17/11/2026). O PDFKit grava no /AcroForm
    cópias soltas dos campos (não os mesmos objetos da página) e não grava o /NM das caixas."""
    import pikepdf
    src = Path(__file__).resolve().parent / "data" / "iphone_formulario.pdf"
    out = tmp_path / "ip.pdf"
    shutil.copy(src, out)
    d = forms.load(out)
    assert {f.name: f.value for f in d.fields} == {"nome": "Maria Ação", "aceito": True}
    forms.save(out, {"nome": "Outro nome", "aceito": False}, d.boxes)
    assert {f.name: f.value for f in forms.load(out).fields} == {"nome": "Outro nome", "aceito": False}
    # as caixas sem /NM e sem /PrumoID (antes da correção do iPhone) não são do Prumo: ficam como estão
    with pikepdf.open(str(out)) as pdf:
        subs = sorted(str(a.Subtype) for p in pdf.pages for a in p.Annots)
    assert subs.count("/Ink") == 3 and subs.count("/FreeText") == 1
