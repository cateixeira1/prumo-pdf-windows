"""
Dados de demonstração para conferir as telas (mesmos exemplos das capturas do iPhone).
Só roda com o argumento --demo; o app instalado não usa nada daqui.

    python main.py --demo PASTA --screen home --shot tela.png [--dark] [--size 1100x780]
"""

from __future__ import annotations

import io
import shutil
import time
from pathlib import Path

PARAS = [
    "{title}",
    "A autora, devidamente qualificada nos autos, vem, respeitosamente, à presença de Vossa Excelência, "
    "propor a presente ação em face do hospital réu, pelos fatos e fundamentos a seguir expostos.",
    "Após a cirurgia, a paciente apresentou febre persistente e dor abdominal intensa, sem que a equipe "
    "adotasse as providências diagnósticas necessárias. A reavaliação ocorreu 36 horas depois, com sinais de sepse.",
    "A demora no diagnóstico configura falha na prestação do serviço, nos termos do art. 14 do Código de "
    "Defesa do Consumidor.",
]


def _font():
    for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return p
    return None


def digital_pdf(path: Path, title: str, pages: int):
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    f = _font()
    if f:
        pdf.add_font("B", "", f)
        pdf.set_font("B", size=11)
    else:
        pdf.set_font("Helvetica", size=11)
    for n in range(pages):
        pdf.add_page()
        for i, p in enumerate(PARAS):
            pdf.set_font_size(14 if i == 0 else 11)
            pdf.multi_cell(0, 6, p.format(title=title))
            pdf.ln(3)
        pdf.cell(0, 8, f"{n + 1}")
    pdf.output(str(path))


def scanned_pdf(path: Path, pages: int):
    import img2pdf
    import pypdfium2 as pdfium

    tmp = path.with_suffix(".src.pdf")
    digital_pdf(tmp, "PROCURAÇÃO AD JUDICIA", pages)
    doc = pdfium.PdfDocument(str(tmp))
    imgs = []
    for i in range(len(doc)):
        im = doc[i].render(scale=150 / 72).to_pil().convert("L").rotate(0.6, expand=True, fillcolor=255)
        b = io.BytesIO()
        im.save(b, "JPEG", quality=75)
        imgs.append(b.getvalue())
    doc.close()
    tmp.unlink()
    path.write_bytes(img2pdf.convert(imgs))


def seed(root: Path):
    from library import Library

    if root.exists():
        shutil.rmtree(root)
    lib = Library(root, local_dir=root.parent / (root.name + "_local"))
    for f in ("Processos", "Laudos e prontuários", "Clientes", "Contratos"):
        lib.create_folder(f)
    lib.create_folder("Indenização - Hospital", "Processos")
    docs = [
        ("digital", "PETIÇÃO INICIAL", 14, "Petição inicial - indenização", "Processos/Indenização - Hospital", {"favorite": True}),
        ("digital", "CONTESTAÇÃO", 22, "Contestação do hospital", "Processos/Indenização - Hospital", {}),
        ("digital", "DECISÃO", 3, "Decisão - tutela de urgência", "Processos", {}),
        ("scan", "", 6, "Prontuário médico", "Laudos e prontuários", {"pending_ocr": True}),
        ("digital", "LAUDO PERICIAL", 9, "Laudo pericial", "Laudos e prontuários", {}),
        ("scan", "", 2, "Procuração assinada", "Clientes", {}),
        ("scan", "", 3, "Documentos pessoais", "Clientes", {}),
        ("digital", "CONTRATO DE HONORÁRIOS", 5, "Contrato de honorários", "Contratos", {"favorite": True}),
        ("scan", "", 2, time.strftime("Escaneado %d-%m-%Y %Hh%M", time.localtime(time.time() - 3600)), "", {"pending_ocr": True}),
    ]
    for kind, title, pages, name, folder, meta in docs:
        dest = lib.unique_path(folder, name)
        if kind == "digital":
            digital_pdf(dest, title, pages)
        else:
            scanned_pdf(dest, pages)
        lib.register(dest, **meta)
    # analisa já, para as capturas mostrarem os números
    for id, path, sig in lib.pending_analysis():
        lib.apply_analysis(id, sig, Library.analyze(path))
    lib.finish_analysis()
    return lib


def apply_screen(win, screen: str):
    from screens import (DocumentGridScreen, DocumentScreen, FoldersScreen, MergeScreen, PagePickerScreen,
                         SettingsScreen, split_dialog)
    from PySide6.QtCore import QTimer

    lib = win.lib
    by = {i.name: i for i in lib.items}
    pet = by.get("Petição inicial - indenização")
    pront = by.get("Prontuário médico")
    if screen == "all":
        win.push(DocumentGridScreen(win, list_id="all"))
    elif screen == "pending":
        win.push(DocumentGridScreen(win, list_id="pending"))
    elif screen == "folders":
        win.push(FoldersScreen(win))
    elif screen == "folder":
        win.push(FoldersScreen(win))
        win.push(DocumentGridScreen(win, folder="Processos"))
    elif screen == "detail":
        win.push(DocumentScreen(win, pet.id))
    elif screen == "detail_scan":
        win.push(DocumentScreen(win, pront.id))
    elif screen == "picker":
        win.push(DocumentScreen(win, pet.id))
        p = PagePickerScreen(win, pet.id, "extract")
        win.push(p)
        p.field.setText("2, 5-9")
        p._typed("2, 5-9")
    elif screen == "split":
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: split_dialog(win, pet))
    elif screen == "merge":
        win.push(MergeScreen(win, preselection=[i.id for i in lib.items if i.folder.startswith("Processos")]))
    elif screen == "settings":
        win.push(SettingsScreen(win))
    elif screen == "search":
        win.current().search.setText("sepse")
        win.current().refresh()
    elif screen == "select":
        s = DocumentGridScreen(win, list_id="all")
        win.push(s)
        s.set_selecting(True)
        for it in lib.items[:2]:
            s._toggle(it)
    elif screen == "ocr":
        win.push(DocumentScreen(win, pront.id))
        win.start_ocr(pront)
    elif screen == "delete":
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: win.actions.delete([pet]))
    elif screen == "share":
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: win.actions.share([pet]))
    elif screen == "move":
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: win.actions.move([pet]))
    elif screen == "rename":
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: win.actions.rename(pet))
    elif screen == "reader":
        from reader import ReaderScreen
        r = ReaderScreen(win, pet.id)
        win.push(r)

        def select_some():
            if r.text is not None and r.text.char_count(0) > 140:
                r.view.select_range((0, 40), (0, 140))
                r.selection_done()          # a barra de seleção, com as cores abertas
                r.selbar._open_popup()
        QTimer.singleShot(500, select_some)
    elif screen == "readertext":
        from reader import TextReaderScreen
        t = TextReaderScreen(win, pet.id)
        win.push(t)

        def mark_some():
            c = t.browser.textCursor()
            if len(t.segs) > 1:
                a = t.segs[1][0]
                c.setPosition(a + 2)
                c.setPosition(a + 60, c.MoveMode.KeepAnchor)
                t.browser.setTextCursor(c)
                t.highlight_selection("green")
                c = t.browser.textCursor()
                b = t.segs[2][0] if len(t.segs) > 2 else a
                c.setPosition(b)
                c.setPosition(b + 70, c.MoveMode.KeepAnchor)
                t.browser.setTextCursor(c)
                t.selection_done()
        QTimer.singleShot(500, mark_some)
    elif screen == "sign":
        import os
        import tempfile
        os.environ["PRUMO_CERT_DIR"] = tempfile.mkdtemp(prefix="prumo_cert_demo_")
        import signing
        pfx = Path(os.environ["PRUMO_CERT_DIR"]) / "demo.pfx"
        pfx.write_bytes(demo_pfx("ANA DE SOUZA", "demo"))
        signing.import_a1(pfx, "demo")
        pfx.unlink()
        import sign_ui
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: sign_ui.sign_dialog(win, pet))
    elif screen == "crop":
        import page_tools
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: page_tools.crop_dialog(win, pet))
    elif screen == "number":
        import page_tools
        win.push(DocumentScreen(win, pet.id))
        QTimer.singleShot(300, lambda: page_tools.number_dialog(win, pet))
    elif screen == "lock":
        win.lock.show_lock()


def demo_pfx(name: str, password: str) -> bytes:
    """Certificado de teste (autoassinado), só para as capturas de tela e os testes."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Teste"),
                         x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"demo", key, cert, None,
                                                 serialization.BestAvailableEncryption(password.encode()))
