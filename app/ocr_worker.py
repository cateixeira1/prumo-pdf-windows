"""
Processo separado que executa o OCR de UM arquivo.

A interface inicia este processo (o próprio executável com --ocr-worker) e lê
os eventos que ele grava, uma linha JSON por evento, no arquivo de status.
Rodar o OCR em outro processo mantém a janela responsiva e permite cancelar.

Estratégia por página (definida pela análise em core.analyze_pdf):
  - texto digital ou OCR anterior -> não é tocada;
  - escaneada sem nenhum texto     -> OCR com correção de rotação e inclinação;
  - imagem com algum texto digital -> OCR em modo "redo", que preserva o texto
    digital existente e não rasteriza a página.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _no_console_windows() -> None:
    """No Windows, impede que cada chamada ao tesseract.exe abra uma janela preta."""
    if os.name != "nt":
        return
    import subprocess

    original = subprocess.Popen.__init__

    def patched(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched


class Emitter:
    def __init__(self, status_file: str):
        self.f = open(status_file, "a", encoding="utf-8", buffering=1)

    def __call__(self, event: dict) -> None:
        event.setdefault("t", round(time.time(), 3))
        self.f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.f.flush()


def _friendly_error(exc: BaseException) -> str:
    import ocrmypdf.exceptions as ex

    name = type(exc).__name__
    if isinstance(exc, ex.DigitalSignatureError):
        return ("O PDF tem assinatura digital. Para fazer OCR, marque a opção "
                "'Permitir PDF com assinatura digital' e clique em Iniciar OCR de novo. "
                "O arquivo original continua válido; só a cópia com OCR perde a assinatura.")
    if isinstance(exc, ex.EncryptedPdfError):
        return "O PDF está protegido por senha. Remova a senha antes do OCR."
    if isinstance(exc, ex.MissingDependencyError):
        return ("O Tesseract não foi encontrado. Reinstale o Prumo PDF ou instale o "
                "Tesseract (UB Mannheim) e tente de novo.")
    if isinstance(exc, ex.InputFileError):
        return f"O arquivo não pôde ser lido: {exc}"
    if "language" in str(exc).lower() or "traineddata" in str(exc).lower():
        return "O modelo de idioma português não foi encontrado na pasta do programa."
    return f"{name}: {exc}"


def _run_ocrmypdf(src: Path, dst: Path, pages: list[int], mode: str, job: dict) -> None:
    import ocrmypdf
    from core import format_ranges

    kwargs = dict(
        language=job.get("language", "por"),
        mode=mode,
        pages=format_ranges(pages).replace(" ", ""),
        output_type="pdf",          # PDF comum: não exige Ghostscript
        optimize=1,                 # só otimizações sem perda
        jobs=int(job.get("jobs", 4)),
        use_threads=True,           # o paralelismo real está nos processos do Tesseract
        progress_bar=True,
        plugins=["ocr_plugin"],
        rotate_pages=True,
        invalidate_digital_signatures=bool(job.get("allow_signed")),
    )
    if mode != "redo":
        # "redo" não aceita processamento de imagem, porque não rasteriza a página
        kwargs["deskew"] = bool(job.get("deskew", True))
        if job.get("max_precision"):
            kwargs["oversample"] = 300
    elif job.get("max_precision"):
        kwargs["oversample"] = 300
    ocrmypdf.ocr(str(src), str(dst), **kwargs)


def run_job(job: dict, emit) -> int:
    import ocr_plugin
    from core import (KIND_LABELS, KIND_MIXED, KIND_SCANNED, analyze_pdf,
                      extract_text, format_ranges, tessdata_dir)

    ocr_plugin.EMIT = emit
    src = Path(job["input"])
    out = Path(job["output"])
    t0 = time.time()

    td = tessdata_dir(bool(job.get("max_precision")))
    if td is not None:
        os.environ["TESSDATA_PREFIX"] = str(td)

    emit({"type": "stage", "desc": "Analisando páginas", "total": None})
    info = analyze_pdf(src)
    if info.error:
        emit({"type": "error", "message": info.error})
        return 2

    kinds = {p.number: p.kind for p in info.pages}
    emit({"type": "analysis", "pages": [
        {"page": p.number, "kind": p.kind, "label": KIND_LABELS[p.kind],
         "chars": p.chars, "coverage": p.image_coverage} for p in info.pages]})

    pure_scan = [p.number for p in info.pages if p.kind == KIND_SCANNED and p.chars == 0]
    with_text = [p.number for p in info.pages
                 if (p.kind == KIND_SCANNED and p.chars > 0) or p.kind == KIND_MIXED]
    skipped = [n for n, k in kinds.items() if n not in pure_scan and n not in with_text]

    if not pure_scan and not with_text:
        result = {"type": "done", "status": "nothing_to_do", "output": None,
                  "total_pages": info.page_count, "skipped": skipped, "ocr_pages": [],
                  "elapsed": round(time.time() - t0, 1)}
        if job.get("save_txt"):
            txt = out.with_suffix(".txt")
            _write_txt(txt, extract_text(src))
            result["txt"] = str(txt)
        emit(result)
        return 0

    work = Path(tempfile.mkdtemp(prefix="prumo_ocr_"))
    try:
        current = src
        if pure_scan:
            emit({"type": "stage", "desc": f"OCR das páginas escaneadas ({format_ranges(pure_scan)})",
                  "total": None})
            step = work / "etapa1.pdf"
            _run_ocrmypdf(current, step, pure_scan, "skip", job)
            current = step
        if with_text:
            emit({"type": "stage", "desc": f"OCR das páginas com imagem e carimbo ({format_ranges(with_text)})",
                  "total": None})
            step = work / "etapa2.pdf"
            _run_ocrmypdf(current, step, with_text, "redo", job)
            current = step

        # Conferência: depois do OCR, todas as páginas devem ter texto.
        emit({"type": "stage", "desc": "Conferindo o resultado", "total": None})
        after = analyze_pdf(current)
        still_empty = [p.number for p in after.pages if p.chars == 0]
        chars_after = {p.number: p.chars for p in after.pages}

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = out.with_name(out.name + ".part")
        shutil.copyfile(current, tmp_out)
        os.replace(tmp_out, out)

        result = {"type": "done", "status": "ok", "output": str(out),
                  "total_pages": info.page_count, "skipped": skipped,
                  "ocr_pages": sorted(pure_scan + with_text),
                  "still_empty": still_empty,
                  "chars_after": chars_after,
                  "elapsed": round(time.time() - t0, 1)}
        if job.get("save_txt"):
            txt = out.with_suffix(".txt")
            _write_txt(txt, extract_text(out))
            result["txt"] = str(txt)
        emit(result)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _write_txt(path: Path, pages: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="\r\n" if os.name == "nt" else "\n") as f:
        for i, text in enumerate(pages, start=1):
            f.write(f"===== Página {i} =====\n{text.strip()}\n\n")


def main(job_file: str) -> int:
    _no_console_windows()
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    emit = Emitter(job["status_file"])
    try:
        return run_job(job, emit)
    except BaseException as exc:  # inclui erros do OCRmyPDF e interrupções
        try:
            msg = _friendly_error(exc)
        except Exception:
            msg = str(exc)
        emit({"type": "error", "message": msg, "detail": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
