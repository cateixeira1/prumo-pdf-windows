"""Execução do OCR em processo separado (usado pela biblioteca e pela tela antiga de OCR)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


def worker_command() -> tuple[str, list[str]]:
    """Como iniciar o processo de OCR: o próprio .exe, ou o Python em desenvolvimento."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--ocr-worker"]
    return sys.executable, [str(Path(__file__).with_name("main.py")), "--ocr-worker"]


def kill_tree(proc: QProcess):
    pid = proc.processId()
    if sys.platform == "win32" and pid:
        import winsys
        subprocess.run([winsys.system_exe("taskkill.exe"), "/PID", str(pid), "/T", "/F"],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.kill()


# Pastas e arquivos temporários do Prumo que podem ter conteúdo de PDFs (cópias para desfazer, OCR, conversão).
STALE_PREFIXES = ("prumo_ocr_", "prumo_job_", "prumo_desfazer_", "prumo_src_", "prumo_conv_", "prumo_docx_",
                  "prumo_lo_", "prumo_restore_")


def clean_stale_temp():
    """Remove o que sobrou de execuções interrompidas (mais de 6 horas), para não ficar cópia de PDF esquecida."""
    tmp = Path(tempfile.gettempdir())
    limit = time.time() - 6 * 3600
    for prefix in STALE_PREFIXES:
        for d in tmp.glob(prefix + "*"):
            try:
                if d.stat().st_mtime >= limit:
                    continue
                if d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)
                else:
                    d.unlink()
            except OSError:
                pass


class OcrRunner(QObject):
    """Executa um arquivo no processo separado e repassa os eventos."""

    event = Signal(dict)
    finished = Signal(int)

    def __init__(self, job: dict, parent=None):
        super().__init__(parent)
        self.dir = Path(tempfile.mkdtemp(prefix="prumo_job_"))
        self.status = self.dir / "status.jsonl"
        self.status.touch()
        job = dict(job, status_file=str(self.status))
        job_file = self.dir / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        self._pos = 0
        self._buffer = ""
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.proc.readAll())  # descarta a saída de texto
        self.proc.finished.connect(self._on_finished)
        prog, args = worker_command()
        self.proc.setProgram(prog)
        self.proc.setArguments(args + [str(job_file)])
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)

    def start(self):
        self.proc.start()
        self.timer.start()

    def cancel(self):
        self.timer.stop()
        if self.proc.state() != QProcess.NotRunning:
            kill_tree(self.proc)

    def _poll(self):
        try:
            with open(self.status, "r", encoding="utf-8") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except OSError:
            return
        if not chunk:
            return
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            line = line.strip()
            if line:
                try:
                    self.event.emit(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _on_finished(self, code, _status):
        self._poll()
        self.timer.stop()
        self.finished.emit(code)
        shutil.rmtree(self.dir, ignore_errors=True)
