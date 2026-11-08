"""Telas da assinatura digital: assinar um PDF e guardar ou remover certificados (Ajustes)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout

import i18n
import signing
from i18n import raw, tr, trf, trn
from ios_kit import Label, PrimaryButton, SheetOverlay, TileCard, sheet_header

WARNING = ("Depois de assinado, o PDF não pode mais ser alterado: qualquer mudança (destaque, corte, numeração, "
           "páginas) invalida a assinatura. Por isso o Prumo assina uma cópia, “{}”, e o original continua "
           "como está, para você editar se precisar.")
WARNING_AGAIN_ONE = ("Este PDF já tem 1 assinatura. A nova assinatura entra no próprio arquivo, sem mudar o "
                     "conteúdo: a assinatura anterior continua válida. Depois, o PDF continua sem poder ser alterado.")
WARNING_AGAIN = ("Este PDF já tem {} assinaturas. A nova assinatura entra no próprio arquivo, sem mudar o conteúdo: "
                 "as assinaturas anteriores continuam válidas. Depois, o PDF continua sem poder ser alterado.")


def _busy(on: bool):
    if on:
        QApplication.setOverrideCursor(Qt.WaitCursor)
    elif QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def load_certificates(app) -> list:
    _busy(True)
    try:
        return signing.all_certificates()
    finally:
        _busy(False)


def _hwnd(app) -> int | None:
    try:
        return int(app.winId())
    except Exception:  # noqa: BLE001
        return None


ADD_A1_TEXT = ("Digite a senha do arquivo do certificado. O Prumo entrega o certificado ao Windows com a chave "
               "protegida: ela não pode ser copiada para fora deste computador (com chip TPM, fica dentro do chip). "
               "Em seguida, o Windows pede para você criar uma senha para usar a chave; ela será pedida a cada "
               "assinatura. O Prumo não guarda o arquivo nem as senhas.")
ADD_A1_TEXT_FILE = ("Digite a senha do arquivo do certificado. O Prumo só confere a senha agora; ela não fica gravada e "
                    "será pedida a cada assinatura.")


def add_a1_dialog(app):
    """Escolhe o arquivo .pfx/.p12, confere a senha e guarda o certificado para assinar depois."""
    from app_window import alert
    path, _f = QFileDialog.getOpenFileName(app, "Certificado digital A1", "",
                                           "Certificado A1 (*.pfx *.p12);;Todos os arquivos (*)")
    if not path:
        return None
    windows = signing.store_mode() == "windows"
    res = alert(app, "Senha do certificado", ADD_A1_TEXT if windows else ADD_A1_TEXT_FILE,
                [("Cancelar", "cancel"), ("Adicionar", "default")], text="", secret=True)
    if not res or res[0] != 1:
        return None
    out = {}
    if app.attempt(lambda: out.setdefault("c", signing.import_a1(path, res[1], _hwnd(app))),
                   busy="Conferindo o certificado…"):
        c = out["c"]
        app.toast(trf("Certificado adicionado: {} (vencido)" if c.expired else "Certificado adicionado: {}", raw(c.name)))
        if windows:
            _explain_storage(app, c, path)
        return c
    return None


def storage_text(c) -> str:
    """Onde a chave ficou e como ela está protegida (texto para o usuário)."""
    if c.store != "prumo":
        return ""
    where = tr("A chave está no chip de segurança (TPM) deste computador e não pode sair dele."
               if c.hardware else
               "A chave está guardada pelo Windows, marcada para não poder ser copiada. Este computador não tem "
               "chip TPM disponível, que daria uma proteção ainda maior.")
    how = tr("O Windows pede a senha da chave a cada assinatura." if c.protected else
             "O Windows não aceitou pedir uma senha a cada uso desta chave: ela não pode ser copiada, mas um "
             "programa aberto nesta conta do Windows conseguiria usá-la sem senha.")
    return raw(where + " " + how)


def _explain_storage(app, c, pfx_path):
    from app_window import alert
    alert(app, "Certificado guardado no Windows",
          raw(storage_text(c) + "\n\n" + trf(
              "O arquivo original continua em “{}”. Ele é a cópia mais exposta do seu certificado: guarde-o fora do "
              "computador (num pendrive, por exemplo) e apague-o daqui. É com ele que você instala o certificado em "
              "outro computador.", raw(pfx_path))),
          [("OK", "default")])


def sign_dialog(app, item):
    """Assina o PDF. Devolve o PDF assinado (ou None)."""
    if item is None:
        return None
    if item.meta.locked:
        app.toast("PDF com senha não pode ser assinado. Remova a senha antes (“Remover senha”).")
        return None
    certs = load_certificates(app)
    if not certs:
        from app_window import alert
        idx = alert(app, "Nenhum certificado digital",
                    "Para assinar, adicione o seu certificado A1 (arquivo .pfx ou .p12). Certificado A3 (token ou "
                    "cartão): o Prumo não guarda o A3. Instale o programa do token, conecte-o e tente de novo; "
                    "o Prumo encontra o certificado no Windows e liga o token na hora de assinar.",
                    [("Agora não", "cancel"), ("Adicionar A1…", "default")])
        if idx != 1:
            return None
        if add_a1_dialog(app) is None:
            return None
        certs = load_certificates(app)
        if not certs:
            return None
    count = signing.signature_count(item.path)

    ov = SheetOverlay(app, 520)
    sheet_header(ov, "Assinar digitalmente", scroll=True)
    card = TileCard()
    card.lay.setSpacing(8)
    card.lay.addWidget(Label(f"“{item.name}”", 15, 600))
    if count:
        card.lay.addWidget(Label(trn(count, WARNING_AGAIN_ONE, WARNING_AGAIN), 13, 500, "orange"))
    else:
        card.lay.addWidget(Label(trf(WARNING, signing.signed_name(item)), 13, 500, "orange"))
    card.lay.addWidget(Label("Certificado", 13, 600))
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)   # o nome longo não alarga o painel
    combo.setMinimumContentsLength(12)
    for c in certs:
        combo.addItem(raw(c.label + (" · " + tr("VENCIDO") if c.expired else "")), c.id)
    card.lay.addWidget(combo)
    pw = QLineEdit()
    pw.setEchoMode(QLineEdit.Password)
    pw.setPlaceholderText("Senha do certificado A1")
    card.lay.addWidget(pw)
    pin_note = Label("Certificado do Windows (A3 em token ou cartão, ou A1 instalado): o Prumo não guarda nada dele. "
                     "Na hora de assinar, o Windows liga o token e o programa do token pede o PIN.", 12, 400, "secondary")
    card.lay.addWidget(pin_note)
    prumo_note = Label("", 12, 400, "secondary")
    card.lay.addWidget(prumo_note)
    more = Label("", 12, 500, "red")
    card.lay.addWidget(more)
    # um embaixo do outro: lado a lado, os dois exigiam mais largura que o painel (e em outros idiomas, mais ainda)
    card.lay.addWidget(_link_button("Adicionar outro certificado A1…", lambda: ov.done("add")))
    card.lay.addWidget(_link_button("Procurar de novo (token conectado agora)", lambda: ov.done("again")))

    level_card = TileCard()
    level_card.lay.setSpacing(8)
    level_card.lay.addWidget(Label("Proteção do documento", 13, 600))
    level_combo = QComboBox()
    for k, (title, _text) in signing.LEVELS.items():
        level_combo.addItem(title, k)
    level_text = Label("", 12, 400, "secondary")
    level_note = Label("", 12, 500, "orange")
    preferred = int(app.setting("sign_level", signing.DEFAULT_LEVEL) or signing.DEFAULT_LEVEL)
    offered, why = signing.level_for(item.path, preferred)
    fields = signing.signature_field_count(item.path)
    if why == "signed":
        level_combo.hide()
        known = signing.LEVELS.get(offered)
        level_note.setText(
            trf("O nível de proteção foi definido pela primeira assinatura ({}) e não muda mais.",
                tr(known[0]).split(':')[0]) if known else
            tr("O nível de proteção foi definido pela primeira assinatura e não muda mais."))
    else:
        level_combo.setCurrentIndex(max(0, level_combo.findData(offered)))
        if why == "fields":
            level_note.setText(trf("Este PDF tem {} campos de assinatura: o Prumo escolheu o nível 2, para os "
                                   "outros signatários ainda poderem assinar. Você pode mudar para o nível 1 ou 3.",
                                   fields))
    level_card.lay.addWidget(level_combo)
    level_card.lay.addWidget(level_text)
    level_card.lay.addWidget(level_note)
    level_note.setVisible(bool(level_note.text()))
    if why == "signed":
        level_text.hide()

    def show_level():
        level_text.setText(signing.LEVELS.get(level_combo.currentData(), ("", ""))[1])

    level_combo.currentIndexChanged.connect(lambda _i: show_level())
    show_level()

    card2 = TileCard()
    card2.lay.setSpacing(8)
    stamp = QCheckBox("Mostrar a assinatura na página (carimbo)")
    stamp.setChecked(bool(app.setting("sign_stamp", True)))
    card2.lay.addWidget(stamp)
    row = QHBoxLayout()
    page = QComboBox()
    for k, label in signing.PAGES.items():
        page.addItem(label, k)
    page.setCurrentIndex(max(0, page.findData(app.setting("sign_page", "last"))))
    pos = QComboBox()
    for k, label in signing.POSITIONS.items():
        pos.addItem(label, k)
    pos.setCurrentIndex(max(0, pos.findData(app.setting("sign_position", "bottom_left"))))
    row.addWidget(page, 1)
    row.addWidget(pos, 1)
    card2.lay.addLayout(row)
    reason = QLineEdit()
    reason.setPlaceholderText("Motivo (opcional). Ex.: Sou o autor deste documento")
    card2.lay.addWidget(reason)
    card2.lay.addWidget(Label("Formato PAdES, reconhecido pelo Adobe Reader e por outros leitores de PDF. Com "
                              "certificado ICP-Brasil, a assinatura tem a mesma validade jurídica da assinatura "
                              "de próprio punho (MP 2.200-2/2001).", 12, 400, "secondary"))

    wrap = QVBoxLayout()
    wrap.setContentsMargins(16, 4, 16, 16)
    wrap.setSpacing(12)
    wrap.addWidget(card)
    wrap.addWidget(level_card)
    wrap.addWidget(card2)
    btn = PrimaryButton("Assinar", "blue")
    ov.lay.addLayout(wrap)
    ov.pin_footer(btn)      # o botão fica visível mesmo quando a tela rola

    def current():
        cid = combo.currentData()
        return next((c for c in certs if c.id == cid), None)

    def update():
        c = current()
        is_file = c is not None and c.kind == "file"
        pw.setVisible(is_file)
        pin_note.setVisible(c is not None and c.kind == "windows" and c.store != "prumo")
        prumo_note.setText(storage_text(c) if c is not None else "")
        prumo_note.setVisible(c is not None and c.store == "prumo")
        more.setText("Este certificado está vencido: a assinatura não será aceita como válida."
                     if c is not None and c.expired else "")
        page.setEnabled(stamp.isChecked())
        pos.setEnabled(stamp.isChecked())
        ov.focus_widget = pw if is_file else btn

    combo.currentIndexChanged.connect(lambda _i: update())
    stamp.toggled.connect(lambda _v: update())
    update()
    btn.clicked.connect(lambda: ov.done(True))
    pw.returnPressed.connect(lambda: ov.done(True))
    answer = ov.run()
    if answer == "add":
        if add_a1_dialog(app) is not None:
            return sign_dialog(app, item)
        return None
    if answer == "again":
        return sign_dialog(app, item)
    if not answer:
        return None
    c = current()
    if c is None:
        return None
    app.set_setting("sign_stamp", stamp.isChecked())
    app.set_setting("sign_page", page.currentData())
    app.set_setting("sign_position", pos.currentData())
    level = int(level_combo.currentData() or signing.DEFAULT_LEVEL) if why != "signed" else signing.DEFAULT_LEVEL
    if why != "signed" and fields > 1 and level == 1:
        from app_window import alert
        idx = alert(app, "Nível 1 em PDF com vários campos de assinatura?",
                    trf("Este PDF tem {} campos de assinatura. No nível 1, depois da sua assinatura ninguém mais "
                        "poderá assinar os outros campos sem invalidar a sua. Para os outros poderem assinar, use o "
                        "nível 2.", fields),
                    [("Voltar", "cancel"), ("Assinar no nível 1", "destructive")])
        if idx != 1:
            return sign_dialog(app, item)
    options = signing.SignOptions(stamp=stamp.isChecked(), page=page.currentData(), position=pos.currentData(),
                                  reason=reason.text().strip(), level=level)
    out = {}

    move = False
    if c.kind == "file" and signing.store_mode() == "windows":
        from app_window import alert
        idx = alert(app, "Proteger o certificado no Windows?",
                    "Este certificado está guardado como arquivo no Prumo (versões anteriores). Para que ele não "
                    "possa ser copiado para outro computador, o Prumo pode entregá-lo ao Windows agora, com a chave "
                    "protegida, e apagar a cópia do arquivo. O Windows vai pedir para você criar uma senha para "
                    "usar a chave.",
                    [("Agora não", "cancel"), ("Proteger e assinar", "default")])
        move = idx == 1

    def run():
        cert = c
        if move:
            cert = signing.migrate_file_cert(c, pw.text(), _hwnd(app))
            out["moved"] = cert
        signer = (signing.file_signer(cert, pw.text()) if cert.kind == "file"
                  else signing.windows_signer(cert, _hwnd(app)))
        out["item"] = signing.sign_item(app.lib, item, signer, cert.name, options)

    busy = ("Assinando… (se o Windows ou o token pedir a senha ou o PIN, digite-a na janela do Windows)"
            if c.kind == "windows" or move else "Assinando…")
    if not app.attempt(run, busy=busy):
        return None
    result = out.get("item")
    if result is not None:
        app.toast(trf("PDF assinado: {}", result.name), "Abrir", lambda: app.read(result))
    return result


def settings_section(app, c, SectionTitle, small_button):
    """Seção "Assinatura digital" dos Ajustes."""
    c.addWidget(SectionTitle("Assinatura digital"))
    card = TileCard()
    saved = signing.prumo_certificates() + signing.saved_certificates()
    if saved:
        for cert in saved:
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(Label(raw(cert.name), 15, 600))
            col.addWidget(Label(raw(tr(cert.kind_label) + " · " + trf("emitido por {}", _issuer_cn(cert.issuer))
                                    + " · " + trf("válido até {}", i18n.fmt_date(cert.not_after))
                                    + (" · " + tr("VENCIDO") if cert.expired else "")), 12.5, 400, "secondary"))
            if cert.store == "prumo":
                col.addWidget(Label(storage_text(cert), 12.5, 400, "secondary"))
            elif cert.kind == "file" and signing.store_mode() == "windows":
                col.addWidget(Label("Guardado como arquivo (versão anterior): a chave pode ser copiada junto com o "
                                    "arquivo. Proteja-o no Windows.", 12.5, 500, "orange"))
            row.addLayout(col, 1)
            if cert.kind == "file" and signing.store_mode() == "windows":
                row.addWidget(small_button("Proteger no Windows…", lambda _c=False, x=cert: _migrate(app, x)))
            row.addWidget(small_button("Remover", lambda _c=False, x=cert: _remove(app, x), "red"))
            card.lay.addLayout(row)
    else:
        card.lay.addWidget(Label("Nenhum certificado A1 salvo no Prumo.", 15, 600))
    row = QHBoxLayout()
    row.addWidget(small_button("Adicionar certificado A1 (.pfx/.p12)…", lambda: (add_a1_dialog(app), app.current().refresh())))
    row.addStretch(1)
    card.lay.addLayout(row)
    card.lay.addWidget(Label(
        "A1: o Prumo entrega o certificado ao Windows com a chave protegida, que não pode ser copiada para outro "
        "computador (com chip TPM, ela fica dentro do chip). O Prumo não guarda o arquivo .pfx nem as senhas. "
        "Guarde o arquivo original fora do computador: é com ele que se instala o certificado em outro lugar."
        if signing.store_mode() == "windows" else
        "A1: o arquivo do certificado fica guardado só nesta conta do Windows (fora da biblioteca e da nuvem). "
        "A senha não é gravada: o Prumo pede a senha a cada assinatura.",
        13, 400, "secondary"))
    c.addWidget(card)

    c.addWidget(SectionTitle("Certificado A3 (token ou cartão)"))
    card = TileCard()
    card.lay.addWidget(Label("Ligação direta com o token, pelo Windows", 15, 600))
    card.lay.addWidget(Label(
        "Não há nada para carregar ou importar: o Prumo não guarda o A3 (a chave privada nunca sai do token). "
        "Instale o programa do seu token ou cartão e conecte-o. Na hora de assinar, o Prumo procura os "
        "certificados em “Certificados – Usuário Atual > Pessoal” do Windows, que é onde o programa do token os "
        "coloca, e o Windows faz a assinatura com o token. Quem pede o PIN é o programa do token, numa janela "
        "do Windows. A1 instalado no Windows aparece no mesmo lugar.", 13, 400, "secondary"))
    row = QHBoxLayout()
    row.addWidget(small_button("Procurar certificados no Windows", lambda: _scan_windows(app)))
    row.addStretch(1)
    card.lay.addLayout(row)
    c.addWidget(card)

    c.addWidget(SectionTitle("Proteção do PDF assinado"))
    card = TileCard()
    card.lay.addWidget(Label("Nível padrão ao assinar", 15, 600))
    combo = QComboBox()
    for k, (title, _text) in signing.LEVELS.items():
        combo.addItem(title, k)
    combo.setCurrentIndex(max(0, combo.findData(int(app.setting("sign_level", signing.DEFAULT_LEVEL) or 2))))
    text = Label("", 13, 400, "secondary")

    def changed():
        app.set_setting("sign_level", combo.currentData())
        text.setText(signing.LEVELS[combo.currentData()][1])

    combo.currentIndexChanged.connect(lambda _i: changed())
    text.setText(signing.LEVELS[combo.currentData()][1])
    card.lay.addWidget(combo)
    card.lay.addWidget(text)
    card.lay.addWidget(Label(
        "O nível vale para a primeira assinatura do PDF (assinatura de certificação, DocMDP) e depois não muda. "
        "Na hora de assinar, dá para trocar o nível daquele PDF. PDF com mais de um campo de assinatura usa o "
        "nível 2 automaticamente, e o Prumo confirma com você antes de assinar. Nenhum nível impede que outro "
        "programa grave uma alteração no arquivo: o que muda é que a assinatura deixa de valer (ou é marcada "
        "como alterada), e leitores como o Adobe Acrobat avisam. Por isso o Prumo assina uma cópia "
        "(“Nome - assinado”), mantém o original editável e desliga as ferramentas de edição na cópia.",
        13, 400, "secondary"))
    c.addWidget(card)


def _scan_windows(app):
    """Procura certificados com chave privada no Windows (A3 em token e A1 instalado) e mostra o resultado."""
    from app_window import alert
    out = {}
    if not app.attempt(lambda: out.setdefault("c", signing.windows_certificates()), busy="Procurando no Windows…"):
        return
    found = out.get("c") or []
    if found:
        lines = "\n".join(f"• {c.name} · {c.issuer.split('CN=')[-1].split(',')[0]} · "
                          + trf("válido até {}", i18n.fmt_date(c.not_after))
                          + (" · " + tr("VENCIDO") if c.expired else "") for c in found)
        alert(app, "Certificados encontrados no Windows",
              raw(lines + "\n\n" + tr("Eles aparecem na tela de assinar. Se o certificado do token for um deles, o "
                                       "Prumo fala com o token na hora da assinatura e o programa do token pede o PIN.")),
              [("OK", "default")])
    else:
        alert(app, "Nenhum certificado encontrado",
              "Não achei certificado com chave privada em “Certificados – Usuário Atual > Pessoal”. Instale o "
              "programa do token ou do cartão, conecte-o e procure de novo. Se o programa do token só deixa o "
              "certificado acessível dentro dele, o Prumo não consegue usá-lo.",
              [("OK", "default")])


def _link_button(text, fn):
    from PySide6.QtWidgets import QPushButton

    from ios_theme import T, font
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(font(13, 600))
    b.setStyleSheet(f"QPushButton {{ background: transparent; border: none; padding: 2px 0; "
                    f"color: {T.hex('blue')}; text-align: left; }}")
    b.clicked.connect(lambda _c=False: fn())
    return b


def _issuer_cn(issuer: str) -> str:
    for part in issuer.split(","):
        if part.strip().upper().startswith("CN="):
            return part.split("=", 1)[1].strip()
    return issuer


def _migrate(app, cert):
    """Leva um A1 guardado como arquivo (versão anterior) para o Windows."""
    from app_window import alert
    res = alert(app, "Proteger o certificado no Windows",
                trf("Digite a senha do certificado de {}. O Prumo entrega a chave ao Windows, protegida, e apaga a "
                    "cópia do arquivo. Em seguida, o Windows pede para você criar uma senha para usar a chave.",
                    raw(cert.name)),
                [("Cancelar", "cancel"), ("Proteger", "default")], text="", secret=True)
    if not res or res[0] != 1:
        return
    out = {}
    if app.attempt(lambda: out.setdefault("c", signing.migrate_file_cert(cert, res[1], _hwnd(app))),
                   busy="Guardando no Windows…"):
        new = out["c"]
        alert(app, "Certificado guardado no Windows", storage_text(new), [("OK", "default")])
        app.current().refresh()


def _remove(app, cert):
    from app_window import alert
    idx = alert(app, "Remover o certificado?",
                trf("O certificado de {} sai do Prumo e do Windows. O arquivo original (.pfx) que você tem continua "
                    "onde estava, e os PDFs já assinados continuam válidos.", cert.name)
                if cert.store == "prumo" else
                trf("O certificado de {} sai do Prumo. O arquivo original (.pfx) que você tem continua onde "
                    "estava, e os PDFs já assinados continuam válidos.", cert.name),
                [("Cancelar", "cancel"), ("Remover", "destructive")])
    if idx == 1 and app.attempt(lambda: signing.remove_certificate(cert)):
        app.toast("Certificado removido do Prumo.")
        app.current().refresh()
