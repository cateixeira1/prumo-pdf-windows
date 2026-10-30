"""Telas da assinatura digital: assinar um PDF e guardar ou remover certificados (Ajustes)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout

import signing
from ios_kit import Label, PrimaryButton, SheetOverlay, TileCard, sheet_header

WARNING = ("Depois de assinado, o PDF não pode mais ser alterado: qualquer mudança (destaque, corte, numeração, "
           "páginas) invalida a assinatura. Por isso o Prumo assina uma cópia, “{name}”, e o original continua "
           "como está, para você editar se precisar.")
WARNING_AGAIN = ("Este PDF já tem {n}. A nova assinatura entra no próprio arquivo, sem mudar o conteúdo: as "
                 "assinaturas anteriores continuam válidas. Depois, o PDF continua sem poder ser alterado.")


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


def add_a1_dialog(app):
    """Escolhe o arquivo .pfx/.p12, confere a senha e guarda o certificado para assinar depois."""
    from app_window import alert
    path, _f = QFileDialog.getOpenFileName(app, "Certificado digital A1", "",
                                           "Certificado A1 (*.pfx *.p12);;Todos os arquivos (*)")
    if not path:
        return None
    res = alert(app, "Senha do certificado",
                "Digite a senha do arquivo do certificado. O Prumo só confere a senha agora; ela não fica gravada e "
                "será pedida a cada assinatura.",
                [("Cancelar", "cancel"), ("Adicionar", "default")], text="", secret=True)
    if not res or res[0] != 1:
        return None
    out = {}
    if app.attempt(lambda: out.setdefault("c", signing.import_a1(path, res[1])), busy="Conferindo o certificado…"):
        c = out["c"]
        app.toast(f"Certificado adicionado: {c.name}" + (" (vencido)" if c.expired else ""))
        return c
    return None


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
    sheet_header(ov, "Assinar digitalmente")
    card = TileCard()
    card.lay.setSpacing(8)
    card.lay.addWidget(Label(f"“{item.name}”", 15, 600))
    if count:
        n = "1 assinatura" if count == 1 else f"{count} assinaturas"
        card.lay.addWidget(Label(WARNING_AGAIN.format(n=n), 13, 500, "orange"))
    else:
        card.lay.addWidget(Label(WARNING.format(name=signing.signed_name(item)), 13, 500, "orange"))
    card.lay.addWidget(Label("Certificado", 13, 600))
    combo = QComboBox()
    for c in certs:
        combo.addItem(c.label + (" · VENCIDO" if c.expired else ""), c.id)
    card.lay.addWidget(combo)
    pw = QLineEdit()
    pw.setEchoMode(QLineEdit.Password)
    pw.setPlaceholderText("Senha do certificado A1")
    card.lay.addWidget(pw)
    pin_note = Label("Certificado do Windows (A3 em token ou cartão, ou A1 instalado): o Prumo não guarda nada dele. "
                     "Na hora de assinar, o Windows liga o token e o programa do token pede o PIN.", 12, 400, "secondary")
    card.lay.addWidget(pin_note)
    more = Label("", 12, 500, "red")
    card.lay.addWidget(more)
    add = QHBoxLayout()
    add.addWidget(_link_button("Adicionar outro certificado A1…", lambda: ov.done("add")))
    add.addWidget(_link_button("Procurar de novo (token conectado agora)", lambda: ov.done("again")))
    add.addStretch(1)
    card.lay.addLayout(add)

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
            "O nível de proteção foi definido pela primeira assinatura" +
            (f" ({known[0].split(':')[0].lower()}) e não muda mais." if known else " e não muda mais."))
    else:
        level_combo.setCurrentIndex(max(0, level_combo.findData(offered)))
        if why == "fields":
            level_note.setText(f"Este PDF tem {fields} campos de assinatura: o Prumo escolheu o nível 2, para os "
                               "outros signatários ainda poderem assinar. Você pode mudar para o nível 1 ou 3.")
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
    wrap.addWidget(btn)
    ov.lay.addLayout(wrap)

    def current():
        cid = combo.currentData()
        return next((c for c in certs if c.id == cid), None)

    def update():
        c = current()
        is_file = c is not None and c.kind == "file"
        pw.setVisible(is_file)
        pin_note.setVisible(c is not None and c.kind == "windows")
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
                    f"Este PDF tem {fields} campos de assinatura. No nível 1, depois da sua assinatura ninguém mais "
                    "poderá assinar os outros campos sem invalidar a sua. Para os outros poderem assinar, use o nível 2.",
                    [("Voltar", "cancel"), ("Assinar no nível 1", "destructive")])
        if idx != 1:
            return sign_dialog(app, item)
    options = signing.SignOptions(stamp=stamp.isChecked(), page=page.currentData(), position=pos.currentData(),
                                  reason=reason.text().strip(), level=level)
    out = {}

    def run():
        signer = signing.file_signer(c, pw.text()) if c.kind == "file" else signing.windows_signer(c)
        out["item"] = signing.sign_item(app.lib, item, signer, c.name, options)

    busy = "Assinando… (se o token pedir o PIN, digite-o na janela do Windows)" if c.kind == "windows" else "Assinando…"
    if not app.attempt(run, busy=busy):
        return None
    result = out.get("item")
    if result is not None:
        app.toast(f"PDF assinado: {result.name}", "Abrir", lambda: app.read(result))
    return result


def settings_section(app, c, SectionTitle, small_button):
    """Seção "Assinatura digital" dos Ajustes."""
    c.addWidget(SectionTitle("Assinatura digital"))
    card = TileCard()
    saved = signing.saved_certificates()
    if saved:
        for cert in saved:
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(Label(cert.name, 15, 600))
            col.addWidget(Label(f"A1 salvo no Prumo · emitido por {_issuer_cn(cert.issuer)} · válido até "
                                f"{cert.not_after.astimezone().strftime('%d/%m/%Y')}"
                                + (" · VENCIDO" if cert.expired else ""), 12.5, 400, "secondary"))
            row.addLayout(col, 1)
            row.addWidget(small_button("Remover", lambda _c=False, x=cert: _remove(app, x), "red"))
            card.lay.addLayout(row)
    else:
        card.lay.addWidget(Label("Nenhum certificado A1 salvo no Prumo.", 15, 600))
    row = QHBoxLayout()
    row.addWidget(small_button("Adicionar certificado A1 (.pfx/.p12)…", lambda: (add_a1_dialog(app), app.current().refresh())))
    row.addStretch(1)
    card.lay.addLayout(row)
    card.lay.addWidget(Label(
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
        lines = "\n".join(f"• {c.name} · {c.issuer.split('CN=')[-1].split(',')[0]} · válido até "
                          f"{c.not_after.astimezone().strftime('%d/%m/%Y')}" + (" · VENCIDO" if c.expired else "")
                          for c in found)
        alert(app, "Certificados encontrados no Windows",
              lines + "\n\nEles aparecem na tela de assinar. Se o certificado do token for um deles, o Prumo "
                      "fala com o token na hora da assinatura e o programa do token pede o PIN.",
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


def _remove(app, cert):
    from app_window import alert
    idx = alert(app, "Remover o certificado?",
                f"O certificado de {cert.name} sai do Prumo. O arquivo original (.pfx) que você tem continua onde "
                "estava, e os PDFs já assinados continuam válidos.",
                [("Cancelar", "cancel"), ("Remover", "destructive")])
    if idx == 1 and app.attempt(lambda: signing.remove_certificate(cert)):
        app.toast("Certificado removido do Prumo.")
        app.current().refresh()
