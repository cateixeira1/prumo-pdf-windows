"""
Prumo PDF - núcleo sem interface.

Funções:
  - analisar cada página de um PDF (texto selecionável, imagens, OCR prévio);
  - combinar PDFs (com um marcador por arquivo);
  - extrair páginas selecionadas para um novo PDF;
  - localizar o Tesseract e os dados de idioma.

Regra de segurança: nenhuma função grava sobre o arquivo de entrada.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "Prumo PDF"
APP_VERSION = "1.2.0"

# --- Critérios de classificação de página -----------------------------------
# São heurísticas, não regras exatas. Ficam aqui para serem ajustadas com
# documentos reais.

# Abaixo disso a página é considerada sem texto (escaneada / foto).
MIN_TEXT_CHARS = 20
# Fração da área da página coberta por imagens a partir da qual a página é
# tratada como "imagem de documento".
SCAN_IMAGE_COVERAGE = 0.5
# Uma página coberta por imagem, mas com pouco texto digital (ex.: rodapé de
# assinatura do PJe ou carimbo lateral do e-SAJ), é "mista": o texto digital
# existe, mas o corpo do documento é imagem e precisa de OCR.
MIXED_MAX_CHARS = 1000

# pdfium (usado por pypdfium2) não é seguro para uso simultâneo em várias
# threads. Todo acesso a pypdfium2 neste processo passa por esta trava.
PDFIUM_LOCK = threading.RLock()


# --- Caminhos ----------------------------------------------------------------

def resource_dir() -> Path:
    """Pasta dos recursos empacotados (ou a raiz do projeto, em desenvolvimento)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def tessdata_dir(max_precision: bool = False) -> Path | None:
    """Pasta com os modelos de idioma que acompanham o aplicativo."""
    name = "tessdata_best" if max_precision else "tessdata"
    d = resource_dir() / name
    if (d / "por.traineddata").exists():
        return d
    return None


def find_tesseract() -> Path | None:
    """Procura o tesseract.exe no PATH, no registro e em Arquivos de Programas."""
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    if os.name != "nt":
        return None
    candidates: list[Path] = []
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Tesseract-OCR") as k:
                    i = 0
                    while True:
                        try:
                            _name, val, _type = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        if isinstance(val, str) and val:
                            candidates.append(Path(val) / "tesseract.exe")
                        i += 1
            except OSError:
                pass
    except ImportError:
        pass
    for env in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
            candidates.append(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    for c in candidates:
        if c.is_file():
            return c
    return None


def unique_path(path: Path) -> Path:
    """Devolve um caminho que ainda não existe: 'x.pdf', 'x (2).pdf', ..."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        cand = path.with_name(f"{stem} ({n}){suffix}")
        if not cand.exists():
            return cand
        n += 1


def same_file(a: str | Path, b: str | Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# --- Análise de páginas ------------------------------------------------------

KIND_DIGITAL = "digital"        # texto selecionável; não passa pelo OCR
KIND_PRIOR_OCR = "ocr_previo"   # já tem camada de OCR invisível; não passa pelo OCR
KIND_SCANNED = "escaneada"      # sem texto; OCR completo
KIND_MIXED = "mista"            # imagem + pouco texto digital; OCR sem rasterizar

KIND_LABELS = {
    KIND_DIGITAL: "Texto digital",
    KIND_PRIOR_OCR: "Já tem OCR",
    KIND_SCANNED: "Escaneada",
    KIND_MIXED: "Imagem + texto digital",
}


@dataclass
class PageInfo:
    number: int               # começa em 1
    chars: int                # caracteres de texto (sem espaços)
    image_coverage: float     # 0.0 a 1.0
    invisible_text: bool      # há texto invisível (camada de OCR anterior)
    kind: str = KIND_DIGITAL

    @property
    def needs_ocr(self) -> bool:
        return self.kind in (KIND_SCANNED, KIND_MIXED)


@dataclass
class DocInfo:
    path: Path
    pages: list[PageInfo] = field(default_factory=list)
    error: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def pages_of(self, *kinds: str) -> list[int]:
        return [p.number for p in self.pages if p.kind in kinds]

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.needs_ocr]


def classify(chars: int, coverage: float, invisible: bool) -> str:
    if chars < MIN_TEXT_CHARS:
        return KIND_SCANNED
    if invisible and coverage >= SCAN_IMAGE_COVERAGE:
        return KIND_PRIOR_OCR
    if coverage >= SCAN_IMAGE_COVERAGE and chars < MIXED_MAX_CHARS:
        return KIND_MIXED
    return KIND_DIGITAL


def _image_coverage(page, pdfium_c) -> float:
    pw, ph = page.get_size()
    page_area = max(pw * ph, 1.0)
    total = 0.0
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
        try:
            getter = getattr(obj, "get_bounds", None) or getattr(obj, "get_pos")
            l, b, r, t = getter()
        except Exception:
            continue
        l, r = max(0.0, min(l, r)), min(pw, max(l, r))
        b, t = max(0.0, min(b, t)), min(ph, max(b, t))
        if r > l and t > b:
            total += (r - l) * (t - b)
    return min(1.0, total / page_area)


def _has_invisible_text(page, pdfium_c) -> bool:
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT], max_depth=4):
        try:
            mode = pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw)
        except Exception:
            continue
        if mode == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
            return True
    return False


def open_error_message(exc: Exception) -> str:
    msg = str(exc).lower()
    if "password" in msg or "senha" in msg:
        return "O PDF está protegido por senha. Remova a senha antes de usar."
    if "format" in msg or "data" in msg:
        return "O arquivo está corrompido ou não é um PDF válido."
    return f"Não foi possível abrir o PDF ({exc})."


def analyze_pdf(path: str | Path) -> DocInfo:
    """Classifica cada página. Não altera o arquivo."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    info = DocInfo(Path(path))
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception as exc:  # senha, arquivo inválido etc.
            info.error = open_error_message(exc)
            return info
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                    finally:
                        textpage.close()
                    chars = sum(1 for ch in text if not ch.isspace())
                    coverage = _image_coverage(page, pdfium_c)
                    invisible = _has_invisible_text(page, pdfium_c) if chars else False
                finally:
                    page.close()
                info.pages.append(
                    PageInfo(i + 1, chars, round(coverage, 3), invisible,
                             classify(chars, coverage, invisible))
                )
        finally:
            pdf.close()
    return info


def page_count(path: str | Path) -> int:
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()


def extract_text(path: str | Path) -> list[str]:
    """Texto de todas as páginas (digital e OCR), uma string por página."""
    import pypdfium2 as pdfium

    out: list[str] = []
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                tp = page.get_textpage()
                out.append(tp.get_text_range())
                tp.close()
                page.close()
        finally:
            pdf.close()
    return out


# --- Seleção de páginas -------------------------------------------------------

_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+|fim|end)$", re.IGNORECASE)


def parse_page_selection(spec: str, total_pages: int) -> list[int]:
    """
    '1, 3-5, 8' -> [1, 3, 4, 5, 8]. Aceita 'fim' como última página ('10-fim').
    Também aceita ';' como separador. Lança ValueError com mensagem em português.
    """
    pages: set[int] = set()
    parts = [p.strip() for p in re.split(r"[;,]", spec) if p.strip()]
    if not parts:
        raise ValueError("Informe ao menos uma página.")
    for part in parts:
        low = part.lower()
        if low in ("fim", "end"):
            pages.add(total_pages)
            continue
        m = _RANGE_RE.match(part)
        if m:
            start = int(m.group(1))
            end = total_pages if m.group(2).lower() in ("fim", "end") else int(m.group(2))
            if start > end:
                raise ValueError(f"Intervalo invertido: {part}")
            pages.update(range(start, end + 1))
        elif part.isdigit():
            pages.add(int(part))
        else:
            raise ValueError(f"Não entendi '{part}'. Use algo como 1, 3-5, 8.")
    bad = sorted(p for p in pages if p < 1 or p > total_pages)
    if bad:
        raise ValueError(
            f"O documento tem {total_pages} página(s); fora do intervalo: "
            f"{format_ranges(bad)}"
        )
    return sorted(pages)


def format_ranges(pages: list[int]) -> str:
    """[1,2,3,5,7,8] -> '1-3, 5, 7-8'"""
    if not pages:
        return ""
    pages = sorted(set(pages))
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if p is not None:
            start = prev = p
    return ", ".join(out)


# --- Combinar e extrair ---------------------------------------------------------

def merge_pdfs(inputs: list[str | Path], output: str | Path, bookmarks: bool = True) -> int:
    """
    Junta os PDFs na ordem dada. Com bookmarks=True cria um marcador por arquivo
    (os marcadores originais de cada arquivo ficam dentro dele).
    Devolve o número de páginas do resultado.
    """
    from pypdf import PdfWriter

    if not inputs:
        raise ValueError("Nenhum arquivo para combinar.")
    if Path(output).exists() and any(same_file(p, output) for p in inputs):
        raise ValueError("O arquivo de saída não pode ser um dos arquivos de entrada.")

    writer = PdfWriter()
    for p in inputs:
        title = Path(p).stem if bookmarks else None
        writer.append(str(p), outline_item=title, import_outline=bookmarks)
    total = len(writer.pages)
    tmp = Path(str(output) + ".part")
    with open(tmp, "wb") as f:
        writer.write(f)
    os.replace(tmp, output)
    return total


def extract_pages(input_path: str | Path, output: str | Path, pages: list[int]) -> int:
    """Cria um PDF só com as páginas indicadas (números começando em 1), na ordem dada."""
    import pikepdf

    if Path(output).exists() and same_file(input_path, output):
        raise ValueError("A saída não pode ser o próprio arquivo de origem.")
    if not pages:
        raise ValueError("Nenhuma página selecionada.")
    with pikepdf.open(str(input_path)) as src:
        n = len(src.pages)
        bad = [p for p in pages if p < 1 or p > n]
        if bad:
            raise ValueError(f"Páginas inexistentes: {format_ranges(bad)}")
        with pikepdf.new() as dst:
            for p in pages:
                dst.pages.append(src.pages[p - 1])
            tmp = Path(str(output) + ".part")
            dst.save(str(tmp), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    os.replace(tmp, output)
    return len(pages)
