"""
Proteção contra ransomware: o "Acesso controlado a pastas" do Microsoft Defender.

Com ele ligado, programas não confiáveis não conseguem alterar nem apagar arquivos nas pastas protegidas
(documentação da Microsoft: protege contra mudanças, não contra leitura). Vem desligado. Ligar, incluir uma
pasta e permitir um programa exigem administrador; por isso o Prumo abre o PowerShell com o pedido de
permissão do Windows (UAC), e o usuário decide ali.

Comandos (documentação "Customize controlled folder access"):
    Add-MpPreference -ControlledFolderAccessProtectedFolders <pasta>
    Add-MpPreference -ControlledFolderAccessAllowedApplications <programa>
    Set-MpPreference -EnableControlledFolderAccess Enabled
Add-MpPreference acrescenta sem apagar o que já existe (Set-MpPreference substituiria a lista).

Páginas da Segurança do Windows (artigo de suporte da Microsoft "Ransomware protection in Windows Security").
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

SECURITY_PAGE = "windowsdefender://ransomwareprotection/"
ALLOW_APP_PAGE = "windowsdefender://allowappthroughfolder"
# EnableControlledFolderAccess: 0 desligado, 1 ligado, 2 auditoria, 3 só disco, 4 auditoria só disco
STATES = {0: "off", 1: "on", 2: "audit", 3: "disk", 4: "audit"}


def available() -> bool:
    return os.name == "nt"


def state(timeout: int = 30) -> str | None:
    """"on", "off", "audit", "disk" ou None (sem Microsoft Defender ativo, ou não deu para saber)."""
    if not available():
        return None
    import winsys
    try:
        r = subprocess.run([winsys.powershell(), "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-MpPreference).EnableControlledFolderAccess"],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out.isdigit():
        return None
    return STATES.get(int(out))


def prumo_exe(exe: str | None = None) -> str:
    """
    O programa a permitir. Na versão da Microsoft Store, a pasta muda a cada atualização
    (...\\WindowsApps\\ColorSoftware.PrumoPDF_1.15.0.0_x64__...\\): usa "*" no lugar da versão, que a regra aceita.
    """
    from pathlib import PureWindowsPath
    p = PureWindowsPath(exe or str(Path(sys.executable).resolve()))
    parts = list(p.parts)
    for i, part in enumerate(parts):
        if part.lower() == "windowsapps" and i + 1 < len(parts) and "_" in parts[i + 1]:
            parts[i + 1] = parts[i + 1].split("_", 1)[0] + "_*"
            return str(PureWindowsPath(*parts))
    return str(p)


def _q(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def script(library_root: str | Path, exe: str, enable: bool) -> str:
    lines = ["$ErrorActionPreference = 'Stop'",
             f"Add-MpPreference -ControlledFolderAccessProtectedFolders {_q(Path(library_root))}",
             f"Add-MpPreference -ControlledFolderAccessAllowedApplications {_q(exe)}"]
    if enable:
        lines.append("Set-MpPreference -EnableControlledFolderAccess Enabled")
    return "\n".join(lines)


def allow_script(exe: str) -> str:
    return "\n".join(["$ErrorActionPreference = 'Stop'",
                      f"Add-MpPreference -ControlledFolderAccessAllowedApplications {_q(exe)}"])


def run_elevated(ps_script: str, hwnd: int | None = None, timeout_ms: int = 180_000) -> bool | None:
    """
    Roda o script no PowerShell como administrador (o Windows mostra o pedido de permissão).
    True: deu certo. False: o comando falhou. None: o usuário não deu a permissão.
    """
    if not available():
        return False
    import ctypes
    from ctypes import wintypes as W

    import winsys

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("fMask", W.ULONG), ("hwnd", W.HWND), ("lpVerb", W.LPCWSTR),
                    ("lpFile", W.LPCWSTR), ("lpParameters", W.LPCWSTR), ("lpDirectory", W.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", W.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", W.LPCWSTR), ("hkeyClass", W.HKEY), ("dwHotKey", W.DWORD), ("hIcon", W.HANDLE),
                    ("hProcess", W.HANDLE)]

    encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode()
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040                       # SEE_MASK_NOCLOSEPROCESS
    info.hwnd = hwnd or None
    info.lpVerb = "runas"
    info.lpFile = winsys.powershell()
    info.lpParameters = f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"
    info.lpDirectory = str(winsys.system_dir())
    info.nShow = 0                                # SW_HIDE
    shell32 = ctypes.WinDLL("shell32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = W.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return None if ctypes.get_last_error() == 1223 else False      # 1223: ERROR_CANCELLED (recusou o UAC)
    try:
        kernel32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        kernel32.WaitForSingleObject.restype = W.DWORD
        if kernel32.WaitForSingleObject(info.hProcess, timeout_ms) != 0:
            return False
        code = W.DWORD(1)
        kernel32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value == 0
    finally:
        kernel32.CloseHandle.argtypes = [W.HANDLE]
        kernel32.CloseHandle(info.hProcess)


def _installed() -> bool:
    """Só o programa instalado pode ser permitido: em desenvolvimento, o "programa" seria o python.exe."""
    return bool(getattr(sys, "frozen", False))


def protect_library(library_root: str | Path, enable: bool, hwnd: int | None = None) -> bool | None:
    if not _installed():
        return False
    return run_elevated(script(library_root, prumo_exe(), enable), hwnd)


def allow_prumo(hwnd: int | None = None) -> bool | None:
    if not _installed():
        return False
    return run_elevated(allow_script(prumo_exe()), hwnd)
