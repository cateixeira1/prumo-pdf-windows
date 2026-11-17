"""PDFs de teste gerados na hora: digital (texto selecionável) e escaneado (só imagem)."""

from __future__ import annotations

import io
from pathlib import Path

PARAS = [
    "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CÍVEL DO FORO CENTRAL.",
    "A autora vem propor a presente AÇÃO DE INDENIZAÇÃO em face do hospital réu, "
    "pela demora no diagnóstico de sepse após o procedimento cirúrgico.",
]


def _font() -> str | None:
    for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return p
    return None


def digital_pdf(path: Path, pages: int = 3, label: str = "") -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    font = _font()
    if font:
        pdf.add_font("Base", "", font)
        pdf.set_font("Base", size=12)
    else:
        pdf.set_font("Helvetica", size=12)
    for n in range(pages):
        pdf.add_page()
        for p in PARAS:
            pdf.multi_cell(0, 7, p)
            pdf.ln(3)
        pdf.cell(0, 10, f"{label} Página {n + 1}".strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def scanned_pdf(path: Path, pages: int = 2) -> Path:
    """Renderiza um PDF digital como imagem: sem nenhum texto selecionável."""
    import img2pdf
    import pypdfium2 as pdfium

    src = digital_pdf(path.with_name(path.stem + "_src.pdf"), pages)
    doc = pdfium.PdfDocument(str(src))
    imgs = []
    for i in range(len(doc)):
        im = doc[i].render(scale=150 / 72).to_pil().convert("L")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
        imgs.append(buf.getvalue())
    doc.close()
    src.unlink()
    path.write_bytes(img2pdf.convert(imgs))
    return path


def form_pdf(path: Path, rotate: int = 0) -> Path:
    """PDF com campos de formulário (AcroForm) feitos à mão: texto, várias linhas, pente, caixa de marcar,
    botões de opção, lista suspensa e lista. Os campos vêm sem valor e com aparência própria (borda)."""
    import pikepdf

    src = digital_pdf(path.with_name(path.stem + "_src.pdf"), 2)
    pdf = pikepdf.open(str(src))
    src_name = src
    helv = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica,
                                                Encoding=pikepdf.Name.WinAnsiEncoding))
    zadb = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.ZapfDingbats))
    fields = pikepdf.Array()

    def ap(content: bytes, w, h, font=None):
        s = pikepdf.Stream(pdf, content)
        s.Type, s.Subtype, s.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, [0, 0, w, h]
        s.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(ZaDb=zadb)) if font else pikepdf.Dictionary()
        return pdf.make_indirect(s)

    def border(w, h):
        return ap(f"0 0 0 RG 1 w 0.5 0.5 {w - 1} {h - 1} re S".encode(), w, h)

    def widget(page, rect, **extra):
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        d = pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, Rect=list(rect), F=4,
                               P=pdf.pages[page].obj, MK=pikepdf.Dictionary(BC=[0, 0, 0]), **extra)
        if "AP" not in extra:
            d.AP = pikepdf.Dictionary(N=border(w, h))
        return d

    def add(field, page, widgets=None):
        ref = pdf.make_indirect(field)
        fields.append(ref)
        for wd in (widgets or [ref]):
            pg = pdf.pages[page].obj
            if "/Annots" not in pg:
                pg.Annots = pikepdf.Array()
            pg.Annots.append(wd)
        return ref

    def text(name, page, rect, da="/Helv 0 Tf 0 g", ff=0, **extra):
        d = widget(page, rect, FT=pikepdf.Name.Tx, T=pikepdf.String(name), DA=pikepdf.String(da), Ff=ff, **extra)
        return add(d, page)

    text("nome", 0, (60, 620, 400, 642))
    text("obs", 0, (60, 520, 400, 600), da="/Helv 10 Tf 0 0 1 rg", ff=1 << 12)
    text("cpf", 0, (60, 480, 280, 500), ff=1 << 24, MaxLen=11, Q=0)
    text("valor", 0, (300, 480, 400, 500), Q=2)
    on = ap(b"q BT /ZaDb 12 Tf 2 3 Td (4) Tj ET Q", 16, 16, font=True)
    off = ap(b"", 16, 16)
    chk = widget(0, (60, 440, 76, 456), FT=pikepdf.Name.Btn, T=pikepdf.String("aceito"), V=pikepdf.Name.Off,
                 AS=pikepdf.Name.Off, DA=pikepdf.String("/ZaDb 0 Tf 0 g"),
                 AP=pikepdf.Dictionary(N=pikepdf.Dictionary(Yes=on, Off=off)))
    add(chk, 0)
    radio = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Btn, T=pikepdf.String("sexo"), Ff=(1 << 15) | (1 << 14),
                                                 V=pikepdf.Name.Off, Kids=pikepdf.Array()))
    kids = []
    for k, state in enumerate(("F", "M")):
        on_r = ap(b"q 0 g 8 8 m 8 10.2 6.2 12 4 12 c 1.8 12 0 10.2 0 8 c 0 5.8 1.8 4 4 4 c 6.2 4 8 5.8 8 8 c f Q", 16, 16)
        kid = pdf.make_indirect(widget(0, (100 + 60 * k, 400, 116 + 60 * k, 416), Parent=radio, AS=pikepdf.Name.Off,
                                       AP=pikepdf.Dictionary(N=pikepdf.Dictionary({"/" + state: on_r, "/Off": off}))))
        radio.Kids.append(kid)
        kids.append(kid)
    fields.append(radio)
    for kid in kids:
        pg = pdf.pages[0].obj
        pg.Annots.append(kid)
    text_ch = widget(0, (60, 360, 200, 380), FT=pikepdf.Name.Ch, T=pikepdf.String("estado"), Ff=1 << 17,
                     DA=pikepdf.String("/Helv 11 Tf 0 g"),
                     Opt=pikepdf.Array([pikepdf.Array([pikepdf.String("SP"), pikepdf.String("São Paulo")]),
                                        pikepdf.Array([pikepdf.String("RJ"), pikepdf.String("Rio de Janeiro")]),
                                        pikepdf.Array([pikepdf.String("MG"), pikepdf.String("Minas Gerais")])]))
    add(text_ch, 0)
    lst = widget(0, (220, 320, 400, 380), FT=pikepdf.Name.Ch, T=pikepdf.String("cor"),
                 DA=pikepdf.String("/Helv 10 Tf 0 g"), Opt=pikepdf.Array([pikepdf.String(c) for c in ("Azul", "Verde", "Vermelho")]))
    add(lst, 0)
    text("cidade", 1, (60, 620, 300, 642))
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=fields, DA=pikepdf.String("/Helv 0 Tf 0 g"),
                                           DR=pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=helv, ZaDb=zadb)))
    if rotate:
        for p in pdf.pages:
            p.Rotate = rotate
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(path))
    pdf.close()
    src_name.unlink()
    return path
