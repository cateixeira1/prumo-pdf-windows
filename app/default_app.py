"""
Prumo como leitor padrão de PDF. O Windows 10 e o 11 não deixam um programa trocar o padrão por conta própria
(a escolha é do usuário), então o Prumo só pergunta e abre a página certa dos Ajustes do Windows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

REGISTERED_NAME = "Prumo PDF"                 # nome em ...\RegisteredApplications (ver build/PrumoPDF.iss)
STORE_PFN = "ColorSoftware.PrumoPDF_597630k0h63h8"
STORE_APP_ID = "PrumoPDF"


def is_packaged() -> bool:
    """Rodando como pacote MSIX (Microsoft Store)?"""
    exe = str(Path(sys.executable).resolve()).lower()
    return "\\windowsapps\\" in exe or bool(os.environ.get("PRUMO_FORCE_PACKAGED"))


def default_pdf_exe() -> str | None:
    """Caminho do programa que abre .pdf agora (None se não der para saber)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        ASSOCF_NOTRUNCATE = 0x00000020
        ASSOCSTR_EXECUTABLE = 2
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        hr = ctypes.windll.shlwapi.AssocQueryStringW(ASSOCF_NOTRUNCATE, ASSOCSTR_EXECUTABLE, ".pdf", None,
                                                    buf, ctypes.byref(size))
        return buf.value if hr == 0 and buf.value else None
    except Exception:
        return None


def is_default_pdf_app() -> bool | None:
    """True se o Prumo já é o padrão, False se não é, None se não deu para saber."""
    exe = default_pdf_exe()
    if exe is None:
        return None
    return PureWindowsPath(exe).name.lower() == "prumopdf.exe"


def settings_uri() -> str:
    """Página dos Ajustes do Windows com o Prumo (Windows 11 recente); nas versões antigas abre a lista geral."""
    if is_packaged():
        return "ms-settings:defaultapps?registeredAUMID=" + quote(f"{STORE_PFN}!{STORE_APP_ID}", safe="")
    return "ms-settings:defaultapps?registeredAppMachine=" + quote(REGISTERED_NAME, safe="")


def should_offer(setting) -> bool:
    """Pergunta no máximo uma vez por versão do aplicativo, e nunca de novo se o usuário disser que não quer."""
    if os.name != "nt" or os.environ.get("PRUMO_NO_PROMPTS"):
        return False
    if str(setting("default_pdf_prompt", "ask")) == "never":
        return False
    if is_default_pdf_app() is True:
        return False
    import core
    return str(setting("default_pdf_prompt_version", "")) != core.APP_VERSION
