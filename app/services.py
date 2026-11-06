"""
Serviços em segundo plano da biblioteca: miniaturas, análise dos PDFs e fila de OCR.
Tudo roda neste computador.
"""

from __future__ import annotations

import hashlib
import os
import time
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

def render_page(path: str | Path, page: int, px_width: int, password: str | None = None) -> QImage | None:
    """
    Renderiza uma página (começando em 0) com a largura pedida, em pixels.

    A página sai do PDFium no formato de 4 bytes por pixel (BGRx) que é o mesmo do Qt (Format_RGB32):
    uma cópia só, e o Qt desenha sem converter a cada pintura (rolar e dar zoom fica mais leve).
    """
    with core.PDFIUM_LOCK:
        try:
            pdf = core.open_for_render(str(path), password)
        except Exception:
            return None
        try:
            if page >= len(pdf):
                return None
            pg = pdf[page]
            try:
                w = pg.get_width() or 1
                bmp = pg.render(scale=max(0.05, px_width / w), prefer_bgrx=True)
                try:
                    img = QImage(bmp.buffer, bmp.width, bmp.height, bmp.stride, QImage.Format_RGB32).copy()
                finally:
                    bmp.close()
            finally:
                pg.close()
        finally:
            pdf.close()
    return img


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
            if not img.isNull():
                _touch(self.disk)
        if img.isNull():
            img = render_page(self.path, self.page, self.px) or QImage()
            if not img.isNull():
                try:
                    img.save(str(self.disk), "PNG")
                except Exception:
                    pass
        self.emitter.done.emit(self.key, img)


def _touch(path: Path) -> None:
    """Marca a miniatura do disco como usada (a limpeza apaga primeiro as que ninguém vê há tempo)."""
    try:
        if time.time() - path.stat().st_mtime > 3 * 86400:
            os.utime(path)
    except OSError:
        pass


def request_priority() -> int:
    """
    Ordem dos desenhos na fila: o que a tela pediu por último vai primeiro (rolar rápido não espera o
    que já passou); dentro da mesma pintura (0,1 s), na ordem pedida, de cima para baixo.
    """
    return int(time.monotonic() * 10) % 2_000_000_000


def px_bucket(px: int) -> int:
    """
    Arredonda a largura pedida para cima, em degraus: ao redimensionar a janela, as miniaturas
    não são desenhadas (nem gravadas no disco) de novo a cada pixel.
    """
    px = max(16, int(px))
    step = 16 if px <= 128 else 32 if px <= 512 else 64
    return (px + step - 1) // step * step


class Thumbnails(QObject):
    """Miniaturas das páginas, na memória (até um limite em bytes que depende do computador) e no disco."""

    ready = Signal(str)
    KEEP_MIN = 128            # nunca menos que isso na memória (o que está na tela não pode sair)

    def __init__(self, cache_dir: Path, budget: int | None = None):
        super().__init__()
        import machine
        self.cache_dir = cache_dir
        self.budget = budget or machine.thumb_cache_bytes()
        self.used = 0
        self.mem: OrderedDict[str, QImage] = OrderedDict()
        self.best: dict[str, QImage] = {}       # página -> última miniatura pronta (qualquer tamanho)
        self.pending: set[str] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(machine.thumb_threads())
        self.emitter = _Emitter()
        self.emitter.done.connect(self._done)

    @staticmethod
    def key(path, version, page, px) -> str:
        return f"{path}|{version}|{page}|{px_bucket(px)}"

    @staticmethod
    def _base(key: str) -> str:
        return key.rsplit("|", 1)[0]

    def get(self, path: str | Path, version: str, page: int, px: int) -> QImage | None:
        """A miniatura pronta; se ainda não houver, pede e devolve a última de outro tamanho (ou None)."""
        k = self.key(path, version, page, px)
        img = self.mem.get(k)
        if img is not None:
            self.mem.move_to_end(k)
            return img
        if k not in self.pending:
            self.pending.add(k)
            disk = self.cache_dir / (hashlib.sha1(k.encode()).hexdigest() + ".png")
            self.pool.start(_ThumbJob(k, str(path), page, px_bucket(px), disk, self.emitter), request_priority())
        return self.best.get(self._base(k))

    def _done(self, key: str, img: QImage):
        self.pending.discard(key)
        if not img.isNull():
            old = self.mem.pop(key, None)
            if old is not None:
                self.used -= old.sizeInBytes()
            self.mem[key] = img
            self.used += img.sizeInBytes()
            self.best[self._base(key)] = img
            while self.used > self.budget and len(self.mem) > self.KEEP_MIN:
                k, gone = self.mem.popitem(last=False)
                self.used -= gone.sizeInBytes()
                if self.best.get(self._base(k)) is gone:
                    del self.best[self._base(k)]
        self.ready.emit(key)


def prune_thumb_cache(folder: Path, budget: int | None = None, max_age_days: int = 90) -> tuple[int, int]:
    """
    Limpa o cache de miniaturas no disco: apaga as que ninguém vê há `max_age_days` dias e, se ainda
    passar do limite (1% do espaço livre, entre 32 e 256 MB), as mais antigas. Devolve (apagadas, bytes).
    """
    import machine
    budget = budget or machine.thumb_disk_bytes(folder)
    files = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.name.endswith(".png") and e.is_file():
                    try:
                        st = e.stat()
                    except OSError:
                        continue
                    files.append((st.st_mtime, st.st_size, e.path))
    except OSError:
        return 0, 0
    files.sort()                                         # as mais antigas primeiro
    limit = time.time() - max_age_days * 86400
    total = sum(f[1] for f in files)
    target = budget * 3 // 4 if total > budget else total   # passou do limite: desce até 3/4 dele
    removed = freed = 0
    for mtime, size, path in files:
        if mtime >= limit and total <= target:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        removed += 1
        freed += size
    return removed, freed


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
        # Limpeza do cache de miniaturas no disco: depois que a janela abriu, em segundo plano.
        QTimer.singleShot(20_000, self._prune_thumbs)
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
        t.start(QThread.Priority.LowPriority)      # analisar PDFs novos não pode disputar com a janela

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

    def _prune_thumbs(self):
        import threading
        threading.Thread(target=prune_thumb_cache, args=(self.lib.thumbs_dir,), daemon=True).start()

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
        import machine
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
            "language": self.settings_get("ocr_language", "") or __import__("ocr_langs").default(),
            "max_precision": bool(self.settings_get("max_precision", False)),
            "jobs": machine.ocr_jobs(bool(self.settings_get("max_precision", False))),
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
                self.finished.emit(job.item_id, "error", __import__("i18n").trf("Não foi possível salvar o resultado: {}", exc))
        if self._output is not None:
            self._output.unlink(missing_ok=True)
        self.progress.emit()
        self._next()
