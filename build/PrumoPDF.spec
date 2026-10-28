# -*- mode: python ; coding: utf-8 -*-
# Empacotamento do Prumo PDF com PyInstaller (modo pasta, que abre mais rápido que arquivo único).
# Uso: pyinstaller build/PrumoPDF.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")

datas = [(os.path.join(ROOT, "tessdata"), "tessdata"),
         (os.path.join(ROOT, "assets", "PrumoPDF.ico"), "assets")]   # ícone da janela e da barra de tarefas
if os.path.isdir(os.path.join(ROOT, "tessdata_best")):
    datas.append((os.path.join(ROOT, "tessdata_best"), "tessdata_best"))
datas += collect_data_files("fpdf")
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
        "screens", "app_window", "demo", "organize", "reader", "convert",
        "mammoth", "pillow_heif", "img2pdf",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
        "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PrumoPDF",
)
