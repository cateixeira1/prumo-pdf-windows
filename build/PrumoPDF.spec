# -*- mode: python ; coding: utf-8 -*-
# Empacotamento do Prumo PDF com PyInstaller (modo pasta, que abre mais rápido que arquivo único).
# Uso: pyinstaller build/PrumoPDF.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")

datas = [(os.path.join(ROOT, "tessdata"), "tessdata"),
         (os.path.join(ROOT, "assets", "PrumoPDF.ico"), "assets"),
         (os.path.join(APP, "locales"), "locales"),               # traduções da interface
         (os.path.join(ROOT, "models", "uvdoc.onnx"), "models")]   # correção de páginas curvas (UVDoc, MIT)   # ícone da janela e da barra de tarefas
if os.path.isdir(os.path.join(ROOT, "tessdata_best")):
    datas.append((os.path.join(ROOT, "tessdata_best"), "tessdata_best"))
datas += collect_data_files("fpdf")
datas += collect_data_files("tzdata")          # fusos horários (o Windows não tem a base do Python)
datas += collect_data_files("pyhanko")
datas += collect_data_files("pyhanko_certvalidator")
datas += collect_data_files("mammoth")         # estilos usados na conversão de .docx          # fontes e dados usados pelo OCRmyPDF ao montar o texto

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=collect_dynamic_libs("pillow_heif"),
    datas=datas,
    hiddenimports=[
        "ocr_worker", "ocr_plugin", "core", "ui_common",
        "page_ocr", "page_merge", "page_extract",
        "library", "pdfops", "services", "ocr_runner", "ios_theme", "ios_kit",
        "screens", "app_window", "demo", "organize", "reader", "reader_text", "convert", "backup", "dewarp", "onnxruntime", "security",
        "mammoth", "pillow_heif", "img2pdf",
        "annotations", "summary", "page_tools", "page_view", "rubberband", "reader_history", "reader_select",
        "signing", "sign_ui", "machine", "compress", "winsys", "protection", "pyhanko", "pyhanko.sign", "pyhanko.sign.signers", "pyhanko.stamp",
        "pyhanko.pdf_utils.incremental_writer", "pyhanko.pdf_utils.font.basic", "pyhanko_certvalidator",
        "tzlocal", "tzdata",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
        "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf",
    ],
    noarchive=False,
)

# --- Cortes sem perda de função (conferidos pelo relatório de tamanho do CI) ---
# 1) opengl32sw.dll (20 MB): OpenGL por software do Qt. O Prumo só usa widgets comuns (raster), sem OpenGL.
# 2) PIL/_avif: leitor de AVIF do Pillow (8 MB). O Prumo não aceita .avif (ver IMAGE_EXT em convert.py);
#    HEIC/HEIF continuam pelo pillow-heif.
# 3) Traduções do próprio Qt (7 MB, 30+ idiomas): ficam só as dos idiomas do Prumo (botões padrão de diálogos).
_QT_LANGS = ("pt", "en", "es", "fr", "de", "ja", "zh", "nb", "nn", "sv", "da", "fi")   # nn: o Qt não traz bokmål


def _drop_binary(entry):
    name = os.path.basename(entry[0]).lower()
    return name == "opengl32sw.dll" or name.startswith("_avif.")


def _drop_data(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "pyside6/translations/" not in dest or not dest.endswith(".qm"):
        return False
    stem = os.path.basename(dest)[:-3]                    # qtbase_pt_br, qt_fr, qtmultimedia_de ...
    parts = stem.split("_", 1)
    if parts[0] not in ("qt", "qtbase") or len(parts) < 2:
        return True                                        # módulos que o Prumo não usa (multimedia, webengine...)
    return parts[1].split("_")[0] not in _QT_LANGS


a.binaries = [b for b in a.binaries if not _drop_binary(b)]
a.datas = [d for d in a.datas if not _drop_data(d)]

pyz = PYZ(a.pure)

# Informações de versão do PrumoPDF.exe (aparecem em Propriedades > Detalhes no Windows).
import re as _re
_ver = _re.search(r'APP_VERSION = "([0-9.]+)"', open(os.path.join(APP, "core.py"), encoding="utf-8").read()).group(1)
_nums = tuple(int(x) for x in (_ver.split(".") + ["0", "0", "0"])[:4])
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[StringFileInfo([StringTable("041604B0", [
        StringStruct("CompanyName", "Prumo PDF"),
        StringStruct("FileDescription", "Prumo PDF"),
        StringStruct("FileVersion", _ver),
        StringStruct("ProductName", "Prumo PDF"),
        StringStruct("ProductVersion", _ver),
        StringStruct("OriginalFilename", "PrumoPDF.exe"),
        StringStruct("LegalCopyright", "Prumo PDF"),
    ])]), VarFileInfo([VarStruct("Translation", [0x0416, 1200])])])

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PrumoPDF",
    debug=False,
    strip=False,
    upx=False,
    console=False,                 # aplicativo de janela, sem console
    icon=os.path.join(ROOT, "assets", "PrumoPDF.ico"),
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PrumoPDF",
)
