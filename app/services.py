"""
Serviços em segundo plano da biblioteca: miniaturas, análise dos PDFs e fila de OCR.
Tudo roda neste computador.
"""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

import core
from library import Library, PDFItem

# Página com confiança média abaixo disso, ou com muitas palavras de baixa confiança,
# é marcada para revisão (mesmo critério da tela de OCR da versão anterior).
REVIEW_CONF = 85.0
REVIEW_LOW_RATIO = 0.10


# --- Miniaturas ---------------------------------------------------------------

def render_page(path: str | Path, page: int, px_width: int) -> QImage | None:
    """Renderiza uma página (começando em 0) com a largura pedida, em pixels."""
    import pypdfium2 as pdfium

    with core.PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            return None
        try:
            if page >= len(pdf):
                return None
            pg = pdf[page]
            try:
                w = pg.get_width() or 1
                bmp = pg.render(scale=max(0.05, px_width / w), rev_byteorder=True)
                pil = bmp.to_pil().convert("RGB")
            finally:
                pg.close()
        finally:
            pdf.close()
    data = pil.tobytes()
    return QImage(data, pil.width, pil.height, pil.width * 3, QImage.Format_RGB888).copy()


class _Emitter(QObject):
    done = Signal(str, object)


class _ThumbJob(QRunnable):
    def __init__(self, key, path, page, px, disk, emitter):
        super().__init__()
        self.key, self.path, self.page, self.px, self.disk, self.emitter = key, path, page, px, disk, emitter

    def run(self):
        img = QImage()
        if self.disk.exists():
            img.load(str(self.disk))
        if img.isNull():
            img = render_page(self.path, self.page, self.px) or QImage()
            if not img.isNull():
                try:
                    img.save(str(self.disk), "PNG")
                except Exception:
                    pass
        self.emitter.done.emit(self.key, img)


class Thumbnails(QObject):
    ready = Signal(str)

    def __init__(self, cache_dir: Path):
        super().__init__()
        self.cache_dir = cache_dir
        self.mem: OrderedDict[str, QImage] = OrderedDict()
        self.pending: set[str] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.emitter = _Emitter()
        self.emitter.done.connect(self._done)

    @staticmethod
    def key(path, version, page, px) -> str:
        return f"{path}|{version}|{page}|{px}"

    def get(self, path: str | Path, version: str, page: int, px: int) -> QImage | None:
        px = max(16, int(px))
        k = self.key(path, version, page, px)
        img = self.mem.get(k)
        if img is not None:
            self.mem.move_to_end(k)
            return img
        if k not in self.pending:
            self.pending.add(k)
            disk = self.cache_dir / (hashlib.sha1(k.encode()).hexdigest() + ".png")
            self.pool.start(_ThumbJob(k, str(path), page, px, disk, self.emitter))
        return None

    def _done(self, key: str, img: QImage):
        self.pending.discard(key)
        if not img.isNull():
            self.mem[key] = img
            while len(self.mem) > 500:
                self.mem.popitem(last=False)
        self.ready.emit(key)


# --- Análise ------------------------------------------------------------------

class _AnalysisThread(QThread):
    result = Signal(str, str, dict)

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def run(self):
        for id, path, sig in self.jobs:
            if self.isInterruptionRequested():
                return
            try:
                r = Library.analyze(path)
            except Exception as exc:
                r = {"error": str(exc), "page_count": None, "status": None, "ocr_pages": [], "text": ""}
            self.result.emit(id, sig, r)


class LibraryHub(QObject):
    """Liga a biblioteca à interface: avisa mudanças e analisa os PDFs novos em segundo plano."""

    changed = Signal()

    def __init__(self, library: Library):
        super().__init__()
        self.lib = library
        self.thumbs = Thumbnails(library.thumbs_dir)
        self._thread: _AnalysisThread | None = None
        self._again = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._emit)
        library.add_listener(self._timer.start)
        self.analyze_pending()

    def _emit(self):
        self.changed.emit()
        self.analyze_pending()

    @property
    def analyzing(self) -> bool:
        return self._thread is not None

    def analyze_pending(self):
        if self._thread is not None:
            self._again = True
            return
        jobs = self.lib.pending_analysis()
        if not jobs:
            return
        t = _AnalysisThread(jobs)
        t.result.connect(self._apply)
        t.finished.connect(self._finished)
        self._thread = t
        t.start()

    def _apply(self, id, sig, result):
        self.lib.apply_analysis(id, sig, result)
        self._timer.start()

    def _finished(self):
        t, self._thread = self._thread, None
        if t is not None:
            t.deleteLater()
        self.lib.finish_analysis()
        if self._again:
            self._again = False
            self.analyze_pending()

    def shutdown(self):
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.wait(3000)
        self.thumbs.pool.waitForDone(2000)


# --- Fila de OCR --------------------------------------------------------------

class OcrJob:
    def __init__(self, item: PDFItem, allow_signed: bool = False):
        self.item_id = item.id
        self.name = item.name
        self.allow_signed = allow_signed
        self.fraction = 0.0
        self.stage = "Aguardando"
        self.conf: dict[int, dict] = {}


class JobCenter(QObject):
    """Faz o OCR de um PDF por vez, num processo separado. O resultado é uma cópia com "- OCR" no nome."""

    progress = Signal()                       # mudou o andamento (banner)
    finished = Signal(str, str, object)       # item_id, status (ok/nothing/error/signed/cancelled), dados

    def __init__(self, hub: LibraryHub, settings_get):
        super().__init__()
        self.hub = hub
        self.settings_get = settings_get
        self.queue: list[OcrJob] = []
        self.current: OcrJob | None = None
        self.runner = None
        self._output: Path | None = None

    def is_busy(self, item_id: str | None = None) -> bool:
        if item_id is None:
            return self.current is not None or bool(self.queue)
        return any(j.item_id == item_id for j in ([self.current] if self.current else []) + self.queue)

    def start(self, item: PDFItem, allow_signed: bool = False) -> bool:
        if self.is_busy(item.id):
            return False
        self.queue.append(OcrJob(item, allow_signed))
        self.progress.emit()
        self._next()
        return True

    def cancel_all(self):
        self.queue.clear()
        if self.runner is not None:
            job = self.current
            self.runner.cancel()
            if job:
                self.finished.emit(job.item_id, "cancelled", None)
        self.current = None
        self.runner = None
        self.progress.emit()

    def _next(self):
        if self.current is not None or not self.queue:
            return
        from ocr_runner import OcrRunner

        job = self.queue.pop(0)
        item = self.hub.lib.item(job.item_id)
        if item is None:
            self._next()
            return
        self.current = job
        self._output = self.hub.lib.temp_path()
        cfg = {
            "input": str(item.path),
            "output": str(self._output),
            "language": self.settings_get("ocr_language", "por"),
            "max_precision": bool(self.settings_get("max_precision", False)),
            "jobs": max(1, (os.cpu_count() or 4) - 1),
            "deskew": True,
            "allow_signed": job.allow_signed,
            "save_txt": False,
        }
        self.runner = OcrRunner(cfg, self)
        self.runner.event.connect(self._event)
        self.runner.finished.connect(self._done)
        job.stage = "Preparando"
        self.runner.start()
        self.progress.emit()

    def _event(self, ev: dict):
        job = self.current
        if job is None:
            return
        t = ev.get("type")
        if t == "stage":
            desc = ev.get("desc") or ""
            if desc.startswith("OCR"):
                job.stage = "Reconhecendo o texto"
            elif desc:
                job.stage = desc
        elif t == "progress" and ev.get("total"):
            job.fraction = min(1.0, float(ev.get("done", 0)) / float(ev["total"]))
        elif t == "page_conf" and ev.get("page"):
            job.conf[int(ev["page"])] = ev
        elif t in ("done", "error"):
            job.result = ev
        self.progress.emit()

    def _done(self, code: int):
        job, self.current, self.runner = self.current, None, None
        if job is None:
            self._next()
            return
        ev = getattr(job, "result", None) or {"type": "error", "message": "O OCR foi interrompido."}
        lib = self.hub.lib
        original = lib.item(job.item_id)
        if ev.get("type") == "error":
            msg = ev.get("message", "Erro desconhecido.")
            status = "signed" if "assinatura digital" in msg else "error"
            self.finished.emit(job.item_id, status, msg)
        elif ev.get("status") == "nothing_to_do":
            if original:
                lib.update(original.id, pending_ocr=False)
            self.finished.emit(job.item_id, "nothing", None)
        elif original is None:
            self.finished.emit(job.item_id, "error", "O PDF original foi movido ou apagado durante o OCR.")
        else:
            review, confs = [], []
            for page, c in sorted(job.conf.items()):
                conf, words, low = float(c.get("conf") or 0), int(c.get("words") or 0), int(c.get("low_words") or 0)
                confs.append(conf)
                if conf < REVIEW_CONF or (words and low / words > REVIEW_LOW_RATIO):
                    review.append(page)
            try:
                result = lib.adopt(self._output, f"{original.name} - OCR", original.folder)
                lib.update_after_ocr(original, result, review, (sum(confs) / len(confs) / 100) if confs else None)
                self.finished.emit(job.item_id, "ok", {"result_id": result.id, "review": review})
            except Exception as exc:
                self.finished.emit(job.item_id, "error", f"Não foi possível salvar o resultado: {exc}")
        if self._output is not None:
            self._output.unlink(missing_ok=True)
        self.progress.emit()
        self._next()
