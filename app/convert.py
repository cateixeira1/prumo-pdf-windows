"""
Transformar outros arquivos em PDF, tudo neste computador (sem internet).

- Imagens (JPG, PNG, HEIC do iPhone, TIFF, BMP, GIF, WebP): cada imagem vira uma página A4,
  na orientação da foto, sem perder qualidade (JPEG entra sem recompressão). Várias imagens
  podem virar um PDF só ou um PDF para cada.
- Texto (TXT, CSV, MD) e páginas HTML: paginação A4 com margens de 2 cm.
- Word, Excel e PowerPoint (DOC/DOCX/RTF/ODT, XLS/XLSX/ODS, PPT/PPTX/ODP): pelo Microsoft
  Office instalado (a mesma conversão do "Salvar como PDF" do Office) ou, sem Office, pelo
  LibreOffice. Sem nenhum dos dois, um .docx ainda é convertido de forma simplificada
  (texto, títulos, listas, tabelas e imagens; o layout pode mudar).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pdfops import UserError

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
TEXT_EXT = {".txt", ".csv", ".md", ".log"}
HTML_EXT = {".html", ".htm"}
WORD_EXT = {".doc", ".docx", ".rtf", ".odt"}
EXCEL_EXT = {".xls", ".xlsx", ".ods"}
POWERPOINT_EXT = {".ppt", ".pptx", ".odp"}
OFFICE_EXT = WORD_EXT | EXCEL_EXT | POWERPOINT_EXT
CONVERTIBLE = IMAGE_EXT | TEXT_EXT | HTML_EXT | OFFICE_EXT

A4_PT = (595.28, 841.89)


def kind(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    for name, group in (("image", IMAGE_EXT), ("text", TEXT_EXT), ("html", HTML_EXT), ("word", WORD_EXT),
                        ("excel", EXCEL_EXT), ("powerpoint", POWERPOINT_EXT)):
        if ext in group:
            return name
    return None


def is_convertible(path: str | Path) -> bool:
    return Path(path).suffix.lower() in CONVERTIBLE


def dialog_filter() -> str:
    """Filtro do diálogo de arquivos do Windows."""
    every = " ".join(f"*{e}" for e in sorted(CONVERTIBLE | {".pdf"}))
    imgs = " ".join(f"*{e}" for e in sorted(IMAGE_EXT))
    office = " ".join(f"*{e}" for e in sorted(OFFICE_EXT))
    texts = " ".join(f"*{e}" for e in sorted(TEXT_EXT | HTML_EXT))
    return (f"PDF e arquivos para converter ({every});;PDF (*.pdf);;Imagens ({imgs});;"
            f"Word, Excel e PowerPoint ({office});;Texto e HTML ({texts})")


@dataclass
class Result:
    created: list[Path] = field(default_factory=list)   # PDFs gerados (em pasta temporária)
    names: list[str] = field(default_factory=list)      # nome sugerido de cada um
    kinds: list[str] = field(default_factory=list)      # "images", "text", "html", "word"…
    from_images: bool = False                           # há páginas de imagem (podem precisar de OCR)
    simplified: list[str] = field(default_factory=list)  # convertidos sem Office/LibreOffice
    failed: list[tuple[str, str]] = field(default_factory=list)


# --- Imagens ------------------------------------------------------------------

def _register_heif():
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return True
    except Exception:
        return False


def _image_bytes(path: Path) -> bytes:
    """JPEG sem rotação pendente entra como está; o resto vira JPEG/PNG já na orientação certa."""
    import io

    from PIL import Image, ImageOps

    if path.suffix.lower() in (".heic", ".heif"):
        _register_heif()
    with Image.open(path) as im:
        orientation = im.getexif().get(0x0112, 1) if hasattr(im, "getexif") else 1
        frames = getattr(im, "n_frames", 1)
        if path.suffix.lower() in (".jpg", ".jpeg") and orientation in (1, None) and im.mode in ("RGB", "L"):
            return path.read_bytes()
        if frames > 1:
            im.seek(0)
        fixed = ImageOps.exif_transpose(im)
        transparent = fixed.mode in ("RGBA", "LA") or (fixed.mode == "P" and "transparency" in fixed.info)
        if transparent:   # fundo branco no lugar da transparência
            rgba = fixed.convert("RGBA")
            fixed = Image.new("RGB", rgba.size, "white")
            fixed.paste(rgba, mask=rgba.split()[-1])
        elif fixed.mode not in ("RGB", "L"):
            fixed = fixed.convert("RGB")
        buf = io.BytesIO()
        if path.suffix.lower() in (".png", ".gif", ".bmp") or transparent:
            fixed.save(buf, "PNG", optimize=True)    # desenhos e capturas de tela: sem perda
        else:
            fixed.save(buf, "JPEG", quality=92)      # fotos
        return buf.getvalue()


def _tiff_pages(path: Path) -> list[bytes]:
    """TIFF com várias páginas (comum em digitalizações): uma página do PDF para cada."""
    import io

    from PIL import Image, ImageSequence

    out = []
    with Image.open(path) as im:
        for frame in ImageSequence.Iterator(im):
            f = frame.convert("L" if frame.mode in ("1", "L") else "RGB")
            buf = io.BytesIO()
            f.save(buf, "PNG", optimize=True)
            out.append(buf.getvalue())
    return out


def images_to_pdf(paths: list[Path], dest: Path) -> int:
    """Junta as imagens num PDF, uma por página A4 (retrato ou paisagem, conforme a imagem)."""
    import img2pdf

    blobs = []
    for p in paths:
        if p.suffix.lower() in (".tif", ".tiff"):
            blobs.extend(_tiff_pages(p))
        else:
            blobs.append(_image_bytes(p))
    if not blobs:
        raise UserError("Nenhuma imagem para converter.")
    a4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))

    def layout(imgwidthpx, imgheightpx, ndpi):
        page = (a4[1], a4[0]) if imgwidthpx > imgheightpx else a4
        return img2pdf.get_layout_fun(page, fit=img2pdf.FitMode.into, auto_orient=False)(
            imgwidthpx, imgheightpx, ndpi)

    dest.write_bytes(img2pdf.convert(blobs, layout_fun=layout))
    return len(blobs)


# --- Texto e HTML (Qt) ----------------------------------------------------------

def _document_to_pdf(doc, dest: Path) -> None:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

    writer = QPdfWriter(str(dest))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Millimeter)
    writer.setResolution(300)
    writer.setTitle(dest.stem)
    writer.setCreator("Prumo PDF")
    # O QTextDocument mede a fonte a 96 dpi: a página dele tem a área útil do A4 nessa escala.
    # Assim a letra sai no tamanho pedido e o texto ocupa a largura toda entre as margens.
    rect = writer.pageLayout().paintRect(QPageLayout.Point)
    doc.setPageSize(QSizeF(rect.width() * 96 / 72, rect.height() * 96 / 72))
    doc.print_(writer)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def text_to_pdf(path: Path, dest: Path) -> None:
    from PySide6.QtGui import QFont, QTextDocument

    doc = QTextDocument()
    f = QFont()
    f.setFamilies(["Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Courier New"]
                  if path.suffix.lower() in (".csv", ".log") else ["Segoe UI", "Calibri", "Arial", "DejaVu Sans"])
    f.setPointSizeF(10.5)
    doc.setDefaultFont(f)
    doc.setPlainText(_read_text(path))
    _document_to_pdf(doc, dest)


def html_to_pdf(html: str, dest: Path, base: Path | None = None) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QTextDocument

    doc = QTextDocument()
    f = QFont()
    f.setFamilies(["Segoe UI", "Calibri", "Arial", "DejaVu Sans"])
    f.setPointSizeF(11)
    doc.setDefaultFont(f)
    if base is not None:
        doc.setBaseUrl(QUrl.fromLocalFile(str(base) + os.sep))
    doc.setDefaultStyleSheet("table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 4px; }"
                             "h1 { font-size: 18pt; } h2 { font-size: 15pt; } h3 { font-size: 13pt; }")
    doc.setHtml(html)
    _document_to_pdf(doc, dest)


def docx_simplified(path: Path, dest: Path) -> None:
    """Sem Office nem LibreOffice: .docx → HTML (mammoth) → PDF. Mantém texto, títulos, listas e tabelas."""
    import mammoth

    tmp = Path(tempfile.mkdtemp(prefix="prumo_docx_"))
    counter = {"n": 0}

    def save_image(image):
        counter["n"] += 1
        ext = (image.content_type or "image/png").split("/")[-1].replace("jpeg", "jpg")
        f = tmp / f"img{counter['n']}.{ext}"
        with image.open() as src:
            f.write_bytes(src.read())
        return {"src": f.name}

    try:
        with open(path, "rb") as fh:
            res = mammoth.convert_to_html(fh, convert_image=mammoth.images.img_element(save_image))
        html = f"<html><body>{res.value}</body></html>"
        html_to_pdf(html, dest, base=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Office e LibreOffice -------------------------------------------------------------

def _has_progid(progid: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID"):
            return True
    except OSError:
        return False


def office_app_for(path: Path) -> str | None:
    """Programa do Office que converte este tipo, se estiver instalado."""
    ext = path.suffix.lower()
    progid = ("Word.Application" if ext in WORD_EXT else "Excel.Application" if ext in EXCEL_EXT
              else "PowerPoint.Application" if ext in POWERPOINT_EXT else None)
    return progid if progid and _has_progid(progid) else None


def find_libreoffice() -> Path | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return Path(found)
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            c = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if c.exists():
                return c
    return None


_PS = {
    "Word.Application": r"""
$app = New-Object -ComObject Word.Application
$app.Visible = $false; $app.DisplayAlerts = 0
try {{
  $d = $app.Documents.Open('{src}', $false, $true, $false)
  $d.ExportAsFixedFormat('{dst}', 17)
  $d.Close([ref]0)
}} finally {{ $app.Quit() }}
""",
    "Excel.Application": r"""
$app = New-Object -ComObject Excel.Application
$app.Visible = $false; $app.DisplayAlerts = $false
try {{
  $b = $app.Workbooks.Open('{src}', 0, $true)
  $b.ExportAsFixedFormat(0, '{dst}')
  $b.Close($false)
}} finally {{ $app.Quit() }}
""",
    "PowerPoint.Application": r"""
$app = New-Object -ComObject PowerPoint.Application
try {{
  $p = $app.Presentations.Open('{src}', -1, 0, 0)
  $p.SaveAs('{dst}', 32)
  $p.Close()
}} finally {{ $app.Quit() }}
""",
}


def office_to_pdf(progid: str, src: Path, dest: Path, timeout=180) -> None:
    """Usa o Office instalado (a mesma conversão do "Salvar como PDF"), sem abrir janelas."""
    q = lambda p: str(p).replace("'", "''")  # noqa: E731
    script = _PS[progid].format(src=q(src.resolve()), dst=q(dest.resolve()))
    flags = 0x08000000 if sys.platform == "win32" else 0   # sem janela de console
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", script], capture_output=True, text=True, timeout=timeout,
                          creationflags=flags)
    if proc.returncode != 0 or not dest.exists():
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise UserError("O Office não conseguiu converter o arquivo" + (f": {msg[-1]}" if msg else "."))


def libreoffice_to_pdf(soffice: Path, src: Path, dest: Path, timeout=240) -> None:
    out = Path(tempfile.mkdtemp(prefix="prumo_lo_"))
    profile = Path(tempfile.mkdtemp(prefix="prumo_lo_profile_"))
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        subprocess.run([str(soffice), f"-env:UserInstallation={profile.as_uri()}", "--headless",
                        "--convert-to", "pdf", "--outdir", str(out), str(src)],
                       capture_output=True, timeout=timeout, creationflags=flags)
        made = out / (src.stem + ".pdf")
        if not made.exists():
            raise UserError("O LibreOffice não conseguiu converter o arquivo.")
        shutil.move(str(made), str(dest))
    finally:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def office_document_to_pdf(src: Path, dest: Path) -> bool:
    """Converte um arquivo do Office. Devolve True se foi a conversão simplificada (sem Office)."""
    progid = office_app_for(src)
    if progid:
        office_to_pdf(progid, src, dest)
        return False
    soffice = find_libreoffice()
    if soffice:
        libreoffice_to_pdf(soffice, src, dest)
        return False
    if src.suffix.lower() == ".docx":
        docx_simplified(src, dest)
        return True
    app = {"word": "o Word", "excel": "o Excel", "powerpoint": "o PowerPoint"}.get(kind(src), "o Office")
    raise UserError(f"Para converter “{src.name}” é preciso ter {app} ou o LibreOffice (gratuito) instalado "
                    "neste computador. Arquivos .docx, imagens e textos convertem sem eles.")


# --- Conversão de uma lista -------------------------------------------------------------

def convert(paths: list[str | Path], combine_images: bool = False, combined_name: str | None = None,
            work_dir: Path | None = None, progress=None) -> Result:
    """
    Converte os arquivos para PDFs numa pasta temporária (quem chama move para a biblioteca).
    PDFs na lista são ignorados aqui. `progress(i, total, nome)` é chamado antes de cada arquivo.
    """
    work = Path(work_dir or tempfile.mkdtemp(prefix="prumo_conv_"))
    work.mkdir(parents=True, exist_ok=True)
    res = Result()
    files = [Path(p) for p in paths if kind(p) not in (None, "pdf")]
    images = [p for p in files if kind(p) == "image"]
    others = [p for p in files if kind(p) != "image"]
    jobs: list[tuple[str, list[Path]]] = []
    if images and combine_images and len(images) > 1:
        jobs.append(("images", images))
    else:
        jobs.extend(("images", [p]) for p in images)
    jobs.extend((kind(p), [p]) for p in others)
    for n, (k, group) in enumerate(jobs, 1):
        first = group[0]
        name = (combined_name or first.stem) if len(group) > 1 else first.stem
        if progress:
            progress(n, len(jobs), first.name if len(group) == 1 else f"{len(group)} imagens")
        dest = work / f"{n:03d}.pdf"
        try:
            if k == "images":
                images_to_pdf(group, dest)
                res.from_images = True
            elif k == "text":
                text_to_pdf(first, dest)
            elif k == "html":
                html_to_pdf(_read_text(first), dest, base=first.parent)
            else:
                if office_document_to_pdf(first, dest):
                    res.simplified.append(first.name)
            res.created.append(dest)
            res.names.append(name)
            res.kinds.append(k)
        except UserError as exc:
            res.failed.append((first.name, str(exc)))
        except subprocess.TimeoutExpired:
            res.failed.append((first.name, "A conversão demorou demais e foi interrompida."))
        except Exception as exc:  # noqa: BLE001 - um arquivo com problema não impede os outros
            res.failed.append((first.name, f"{type(exc).__name__}: {exc}"))
    return res
