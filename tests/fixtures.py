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
