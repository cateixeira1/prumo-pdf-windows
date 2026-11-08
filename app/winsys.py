"""
Programas do Windows chamados pelo Prumo, sempre pelo caminho completo.

Quando um programa é chamado só pelo nome ("powershell"), o Windows procura primeiro na pasta do
Prumo e depois na pasta atual, antes da pasta do sistema (documentação do CreateProcess). Um
"powershell.exe" falso deixado na pasta atual seria executado no lugar do verdadeiro. Por isso:

- os programas do sistema são chamados pelo caminho da pasta do Windows (GetSystemDirectory e
  GetWindowsDirectory, não variáveis de ambiente, que qualquer programa pode mudar);
- programas de terceiros (LibreOffice, Tesseract) são procurados só nas pastas absolutas do PATH,
  sem a pasta atual (o shutil.which do Python, no Windows, olha a pasta atual primeiro);
- a pasta atual do Prumo vira a pasta do próprio programa (em Arquivos de Programas, onde um
  programa comum não grava), depois de os caminhos recebidos ao abrir já estarem completos.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def windows_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(520)
            n = ctypes.windll.kernel32.GetWindowsDirectoryW(buf, 520)
            if 0 < n < 520:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    return Path(os.environ.get("SystemRoot") or r"C:\Windows")


@lru_cache(maxsize=None)
def system_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(520)
            n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, 520)
            if 0 < n < 520:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    return windows_dir() / "System32"


def powershell() -> str:
    """O PowerShell do Windows (5.1), que existe em todo Windows 10 e 11."""
    p = system_dir() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(p) if os.name != "nt" or p.is_file() else "powershell.exe"


def explorer() -> str:
    p = windows_dir() / "explorer.exe"
    return str(p) if os.name != "nt" or p.is_file() else "explorer.exe"


def system_exe(name: str) -> str:
    """Um programa da pasta System32 (taskkill.exe, por exemplo)."""
    p = system_dir() / name
    return str(p) if os.name != "nt" or p.is_file() else name


def which(name: str) -> Path | None:
    """
    Como o shutil.which, mas só nas pastas absolutas do PATH: nunca a pasta atual, nem "." ou
    caminhos relativos que alguém tenha posto no PATH.
    """
    exts = [""]
    if os.name == "nt" and not Path(name).suffix:
        exts = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = d.strip().strip('"')
        if not d or not os.path.isabs(d):
            continue
        for e in exts:
            c = Path(d) / (name + e)
            if c.is_file() and (os.name == "nt" or os.access(c, os.X_OK)):
                return c
    return None


def program_dir() -> Path:
    """Pasta do programa: a do .exe instalado, ou a pasta app/ em desenvolvimento."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def use_safe_cwd() -> None:
    """Muda a pasta atual para a do programa (chamar depois de completar os caminhos recebidos)."""
    try:
        os.chdir(program_dir())
    except OSError:
        pass
