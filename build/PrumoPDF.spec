# -*- mode: python ; coding: utf-8 -*-
# Empacotamento do Prumo PDF com PyInstaller (modo pasta, que abre mais rápido que arquivo único).
# Uso: pyinstaller build/PrumoPDF.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")

datas = [(os.path.join(ROOT, "tessdata"), "tessdata"),
         (os.path.join(ROOT, "assets", "PrumoPDF.ico"), "assets"),
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
        "signing", "sign_ui", "pyhanko", "pyhanko.sign", "pyhanko.sign.signers", "pyhanko.stamp",
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
