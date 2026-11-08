"""
Versão 1.15.0: segurança.

- Conversão pelo Office com as macros desligadas (AutomationSecurity = 3) e LibreOffice com perfil sem macros.
- Programas do sistema pelo caminho completo; busca no PATH sem a pasta atual; pasta atual segura.
- Nada do PDF fica para trás na pasta do Prumo quando ele sai da biblioteca (miniaturas, texto, versões),
  e "Proteger com senha" oferece apagar o original de vez.
- Certificado A1 entregue ao Windows com a chave não exportável (TPM quando há) e assinatura pelo Windows.
- Acesso controlado a pastas (proteção contra ransomware): comandos e Ajustes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import digital_pdf  # noqa: E402

WINDOWS = os.name == "nt"


def _wait(cond, timeout=60.0):
    from PySide6.QtCore import QEventLoop, QTimer
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(40, loop.quit)
        loop.exec()
    return False


# --- macros ------------------------------------------------------------------------------------

def test_office_scripts_disable_macros_before_opening():
    import convert
    for progid, script in convert._PS.items():
        lock = script.index("$app.AutomationSecurity = 3")
        check = script.index("if ($app.AutomationSecurity -ne 3)")
        opened = min(i for i in (script.find(".Open("), script.find("Documents.Open"), script.find("Workbooks.Open"),
                                 script.find("Presentations.Open")) if i >= 0)
        assert lock < check < opened, f"{progid}: macros desligadas e conferidas antes de abrir o arquivo"
    assert "$app.EnableEvents = $false" in convert._PS["Excel.Application"]


def test_libreoffice_profile_disables_macros():
    import xml.etree.ElementTree as ET

    import convert
    profile = convert.libreoffice_profile()
    try:
        xcu = profile / "user" / "registrymodifications.xcu"
        root = ET.parse(xcu).getroot()
        props = {p.get("{http://openoffice.org/2001/registry}name"): p.find("value").text
                 for item in root for p in item}
        assert props["MacroSecurityLevel"] == "3", "segurança de macros “Muito alta”"
        assert props["DisableMacrosExecution"] == "true"
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def test_libreoffice_still_converts_with_the_locked_profile(tmp_path):
    import convert
    soffice = convert.find_libreoffice()
    if soffice is None:
        pytest.skip("LibreOffice não instalado neste computador")
    src = tmp_path / "carta.txt"                      # um .txt passa pelo LibreOffice como documento de texto
    src.write_text("Carta de teste\n", encoding="utf-8")
    dest = tmp_path / "carta.pdf"
    convert.libreoffice_to_pdf(soffice, src, dest)
    assert dest.exists() and dest.stat().st_size > 500


# --- programas pelo caminho completo ------------------------------------------------------------------

@pytest.mark.skipif(not WINDOWS, reason="pastas do Windows")
def test_system_programs_have_full_paths():
    import winsys
    for exe in (winsys.powershell(), winsys.explorer(), winsys.system_exe("taskkill.exe")):
        assert os.path.isabs(exe), exe
        assert Path(exe).is_file(), exe
        assert Path(exe).resolve().is_relative_to(winsys.windows_dir().resolve())


def test_which_ignores_current_folder_and_relative_path(tmp_path, monkeypatch):
    import winsys
    planted = tmp_path / "plantado"
    planted.mkdir()
    name = "prumo-ferramenta-falsa"
    fake = planted / (name + (".exe" if WINDOWS else ""))
    fake.write_bytes(b"MZ")
    fake.chmod(0o755)
    monkeypatch.chdir(planted)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "plantado", str(tmp_path / "vazio")]))
    assert winsys.which(name) is None, "a pasta atual e caminhos relativos do PATH não contam"
    monkeypatch.setenv("PATH", str(planted))
    assert winsys.which(name) == fake, "pasta absoluta do PATH continua valendo"


def test_safe_cwd_is_program_folder(tmp_path, monkeypatch):
    import winsys
    monkeypatch.chdir(tmp_path)
    winsys.use_safe_cwd()
    assert Path.cwd().resolve() == winsys.program_dir().resolve()


def test_no_bare_program_names_in_subprocess_calls():
    """Nenhum programa do sistema chamado só pelo nome em app/ (a lista vem do código)."""
    import re
    app = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"subprocess\.(?:run|Popen|call|check_output)\(\s*\[\s*\"(powershell|explorer|taskkill)")
    hits = [f"{p.name}: {m.group(0)}" for p in app.glob("*.py") for m in pattern.finditer(p.read_text(encoding="utf-8"))]
    assert hits == []


# --- nada fica para trás ------------------------------------------------------------------------------

def test_thumbs_are_named_per_pdf_and_purged(tmp_path):
    from library import Library, thumb_prefix
    root = tmp_path / "Biblioteca"
    root.mkdir()
    a = digital_pdf(root / "A.pdf", 1)
    b = digital_pdf(root / "B.pdf", 1)
    lib = Library(root, local_dir=tmp_path / "local")
    ia = next(i for i in lib.items if i.name == "A")
    ib = next(i for i in lib.items if i.name == "B")
    for it in (ia, ib):
        for n in range(3):
            (lib.thumbs_dir / f"{thumb_prefix(it.path)}-{n:040d}.png").write_bytes(b"png")
    (lib.versions_dir / f"{ia.id}.pdf").write_bytes(b"%PDF")
    (lib.text_dir / f"{ia.id}.txt").write_text("texto do PDF", encoding="utf-8")
    lib.delete([ia], permanent=True)
    assert not a.exists(), "apagado de vez"
    left = sorted(p.name for p in lib.thumbs_dir.glob("*.png"))
    assert left and all(n.startswith(thumb_prefix(ib.path)) for n in left), "as miniaturas de A sumiram, as de B ficam"
    assert not (lib.versions_dir / f"{ia.id}.pdf").exists()
    assert not (lib.text_dir / f"{ia.id}.txt").exists()
    assert b.exists()


def test_thumbnail_jobs_write_with_prefix(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import services
    from library import thumb_prefix
    pdf = digital_pdf(tmp_path / "p.pdf", 1)
    cache = tmp_path / "thumbs"
    cache.mkdir()
    t = services.Thumbnails(cache)
    t.get(pdf, "v1", 0, 120)
    assert _wait(lambda: not t.pending, 30)
    t.pool.waitForDone(5000)
    files = list(cache.glob("*.png"))
    assert files and all(f.name.startswith(thumb_prefix(pdf) + "-") for f in files)


def test_legacy_thumbs_are_dropped(tmp_path):
    import services
    old = tmp_path / (hashlib.sha1(b"x").hexdigest() + ".png")
    new = tmp_path / ("0123456789abcdef-" + hashlib.sha1(b"y").hexdigest() + ".png")
    other = tmp_path / "outro.png"
    for f in (old, new, other):
        f.write_bytes(b"png")
    assert services.drop_legacy_thumbs(tmp_path) == 1
    assert not old.exists() and new.exists() and other.exists()


def test_stale_temp_includes_undo_and_conversion_copies(tmp_path, monkeypatch):
    import tempfile

    import ocr_runner
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = time.time() - 7 * 3600
    made = []
    for prefix in ("prumo_desfazer_", "prumo_conv_", "prumo_lo_profile_"):
        d = tmp_path / (prefix + "x")
        d.mkdir()
        (d / "copia.pdf").write_bytes(b"%PDF")
        os.utime(d, (old, old))
        made.append(d)
    f = tmp_path / "prumo_src_y.pdf"
    f.write_bytes(b"%PDF")
    os.utime(f, (old, old))
    fresh = tmp_path / "prumo_desfazer_novo"
    fresh.mkdir()
    keep = tmp_path / "prumo_ui"
    keep.mkdir()
    ocr_runner.clean_stale_temp()
    assert not any(d.exists() for d in made) and not f.exists()
    assert fresh.exists(), "o que é recente (Prumo aberto) fica"
    assert keep.exists(), "ícones da interface não são apagados"


def _gui_window(tmp):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import ios_theme
    ios_theme.T.setup("light")
    from app_window import MainWindow
    from library import Library
    lib_root = tmp / "Biblioteca"
    lib_root.mkdir()
    digital_pdf(lib_root / "Laudo.pdf", 2)
    digital_pdf(lib_root / "Contrato.pdf", 2)
    w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.IniFormat), Library(lib_root, local_dir=tmp / "local"))
    w.resize(1000, 760)
    w.show()
    return w


def _answer_protect(w, fate_title, seen):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit, QRadioButton

    from ios_kit import PrimaryButton, SheetOverlay

    def step():
        ov = next((o for o in w.findChildren(SheetOverlay) if o.isVisible()), None)
        if ov is None:
            QTimer.singleShot(100, step)
            return
        for e in ov.findChildren(QLineEdit):
            e.setText("Sigilo#2026")
        radios = ov.findChildren(QRadioButton)
        seen.extend(r.text() for r in radios)
        next(r for r in radios if r.text() == fate_title).setChecked(True)
        next(b for b in ov.findChildren(PrimaryButton) if b.title == "Proteger").click()
    QTimer.singleShot(300, step)


def test_protect_dialog_erase_and_keep(tmp_path):
    import screens
    from library import thumb_prefix
    w = _gui_window(tmp_path)
    try:
        assert _wait(lambda: len(w.lib.items) == 2 and all(i.meta.signature for i in w.lib.items))
        laudo = next(i for i in w.lib.items if i.name == "Laudo")
        thumbs = [w.lib.thumbs_dir / f"{thumb_prefix(laudo.path)}-{n:040d}.png" for n in range(2)]
        for t in thumbs:
            t.write_bytes(b"png")
        seen = []
        _answer_protect(w, "Apagar de vez (não vai para a Lixeira)", seen)
        w.open_document(laudo.id)
        screens.protect_dialog(w, laudo)
        assert "Mandar para a Lixeira (dá para recuperar)" in seen
        assert _wait(lambda: any(i.name == "Laudo - protegido" for i in w.lib.items))
        assert not laudo.path.exists(), "original apagado de vez"
        assert not any(t.exists() for t in thumbs), "as miniaturas do original também"
        assert w.setting("protect_original", "") == "erase", "a escolha fica lembrada"
        contrato = next(i for i in w.lib.items if i.name == "Contrato")
        _answer_protect(w, "Manter (fica o original sem senha e a cópia com senha)", [])
        screens.protect_dialog(w, contrato)
        assert _wait(lambda: any(i.name == "Contrato - protegido" for i in w.lib.items))
        assert contrato.path.exists(), "manter: o original continua"
    finally:
        w.hub.shutdown()
        w.close()


def test_protect_note_mentions_cloud_trash(tmp_path, monkeypatch):
    import backup
    import screens
    monkeypatch.setattr(backup, "cloud_of", lambda *a, **k: "OneDrive")
    note = screens.protect_fate_note("erase", tmp_path)
    assert "OneDrive" in note and "lixeira da nuvem" in note
    monkeypatch.setattr(backup, "cloud_of", lambda *a, **k: None)
    assert "nuvem" not in screens.protect_fate_note("trash", tmp_path)


# --- certificado A1 no Windows ---------------------------------------------------------------------

def _make_pfx(name: str, password: str) -> bytes:
    import demo
    return demo.demo_pfx(f"{name}:12345678909", password)


@pytest.fixture
def windows_store(tmp_path, monkeypatch):
    if not WINDOWS:
        pytest.skip("certificados do Windows só existem no Windows")
    monkeypatch.setenv("PRUMO_CERT_DIR", str(tmp_path / "certs"))
    monkeypatch.setenv("PRUMO_A1_STORE", "windows")
    monkeypatch.setenv("PRUMO_CERT_NO_UI", "1")       # sem janela de senha do Windows (ninguém clica no CI)
    import signing
    made = []
    yield made
    for info in made:
        try:
            signing.remove_certificate(info)
        except Exception:  # noqa: BLE001
            pass


def test_a1_goes_to_windows_not_exportable(tmp_path, windows_store):
    import signing
    import wincert
    pfx = tmp_path / "maria.pfx"
    pfx.write_bytes(_make_pfx("MARIA DE TESTE", "senha123"))
    with pytest.raises(signing.UserError):
        signing.import_a1(pfx, "errada")
    info = signing.import_a1(pfx, "senha123")
    windows_store.append(info)
    record = signing._windows_dir() / f"{info.thumbprint}.json"
    report = (f"A1 no Windows: provedor={info.provider} hardware={info.hardware} protegido={info.protected}\n"
              f"registro: {record.read_text(encoding='utf-8')}\n")
    print(report)
    if os.environ.get("OUT"):                                   # no CI: fica em logs/ (há TPM no computador do CI?)
        logs = Path(os.environ["OUT"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "a1_windows.txt").write_text(report, encoding="utf-8")
    assert info.store == "prumo" and info.kind == "windows"
    assert not list(signing.cert_dir().glob("*.pfx")), "o Prumo não guarda o arquivo .pfx"
    assert b"PRIVATE" not in record.read_bytes() and len(record.read_bytes()) < 20000, "só a parte pública"
    state = wincert.key_state(info.provider, info.key_name)
    assert state is not None and state["exportable"] is False, "o Windows recusa exportar a chave"
    assert state["hardware"] == info.hardware
    # aparece em "Pessoal" ligado à chave (o caminho do A3 também o enxerga) e uma vez só na lista
    ours = [c for c in signing.all_certificates() if c.thumbprint.upper() == info.thumbprint]
    assert len(ours) == 1 and ours[0].store == "prumo"
    listed = {c.thumbprint.upper() for c in signing.windows_certificates()}
    assert info.thumbprint in listed
    # adicionar de novo não duplica
    again = signing.import_a1(pfx, "senha123")
    assert again.thumbprint == info.thumbprint
    assert len(list(signing._windows_dir().glob("*.json"))) == 1


def test_a1_in_windows_signs_valid_pdf(tmp_path, windows_store):
    import signing
    from test_v110 import validate
    pfx = tmp_path / "joao.pfx"
    pfx.write_bytes(_make_pfx("JOAO DA SILVA", "senha123"))
    info = signing.import_a1(pfx, "senha123")
    windows_store.append(info)
    src = digital_pdf(tmp_path / "Contrato.pdf", 2)
    out = tmp_path / "Contrato - assinado.pdf"
    signing.sign_file(src, out, signing.windows_signer(info), info.name, signing.SignOptions())
    (status,) = validate(out, info.der)
    assert status.intact and status.valid, status.pretty_print_details()
    assert status.signing_cert.sha1.hex().upper() == info.thumbprint


def test_remove_deletes_key_and_certificate(tmp_path, windows_store):
    import signing
    import wincert
    pfx = tmp_path / "ana.pfx"
    pfx.write_bytes(_make_pfx("ANA SOUZA", "senha123"))
    info = signing.import_a1(pfx, "senha123")
    signing.remove_certificate(info)
    assert wincert.key_state(info.provider, info.key_name) is None, "a chave sai do Windows"
    assert info.thumbprint not in {c.thumbprint.upper() for c in signing.windows_certificates()}
    assert signing.prumo_certificates() == []


def test_old_file_certificate_migrates(tmp_path, windows_store, monkeypatch):
    import signing
    pfx = tmp_path / "antigo.pfx"
    pfx.write_bytes(_make_pfx("CARLOS ANTIGO", "senha123"))
    monkeypatch.setenv("PRUMO_A1_STORE", "file")
    old = signing.import_a1(pfx, "senha123")
    assert old.kind == "file" and old.path.exists()
    monkeypatch.setenv("PRUMO_A1_STORE", "windows")
    new = signing.migrate_file_cert(old, "senha123")
    windows_store.append(new)
    assert new.store == "prumo"
    assert not old.path.exists(), "a cópia do arquivo foi apagada"
    assert signing.saved_certificates() == []


def test_kind_labels():
    import signing
    base = dict(id="x", name="N", subject="", issuer="", not_before=None, not_after=None)
    assert signing.CertInfo(kind="file", **base).kind_label == "A1 salvo no Prumo"
    assert signing.CertInfo(kind="windows", store="prumo", hardware=True, **base).kind_label == "A1 no Windows, no chip TPM"
    assert signing.CertInfo(kind="windows", store="prumo", **base).kind_label == "A1 no Windows"
    assert signing.CertInfo(kind="windows", **base).kind_label == "Windows (A1 instalado ou A3)"


def test_storage_mode_defaults(monkeypatch):
    import signing
    monkeypatch.delenv("PRUMO_A1_STORE", raising=False)
    assert signing.store_mode() == ("windows" if WINDOWS else "file")


# --- proteção contra ransomware ------------------------------------------------------------------

def test_cfa_script_adds_without_replacing():
    import protection
    s = protection.script(r"C:\Users\Ana\Documents\Prumo PDF's", r"C:\Program Files\Prumo PDF\PrumoPDF.exe", enable=True)
    assert "Add-MpPreference -ControlledFolderAccessProtectedFolders 'C:\\Users\\Ana\\Documents\\Prumo PDF''s'" in s
    assert "Add-MpPreference -ControlledFolderAccessAllowedApplications 'C:\\Program Files\\Prumo PDF\\PrumoPDF.exe'" in s
    assert "Set-MpPreference -EnableControlledFolderAccess Enabled" in s
    assert "Set-MpPreference -ControlledFolderAccess" not in s, "Set-MpPreference trocaria a lista inteira"
    assert "Enabled" not in protection.script("C:\\x", "C:\\y.exe", enable=False)


def test_cfa_store_path_uses_wildcard():
    import protection
    exe = r"C:\Program Files\WindowsApps\ColorSoftware.PrumoPDF_1.15.0.0_x64__597630k0h63h8\PrumoPDF.exe"
    got = protection.prumo_exe(exe)
    assert got == r"C:\Program Files\WindowsApps\ColorSoftware.PrumoPDF_*\PrumoPDF.exe"
    plain = r"C:\Program Files\Prumo PDF\PrumoPDF.exe"
    assert protection.prumo_exe(plain) == plain


def test_cfa_never_allows_python_in_development():
    import protection
    if getattr(sys, "frozen", False):
        pytest.skip("só vale para o Python solto")
    assert protection.protect_library("C:\\x", enable=False) is False
    assert protection.allow_prumo() is False


def test_cfa_state_reads_or_unknown():
    import protection
    st = protection.state()
    print("Acesso controlado a pastas no computador do teste:", st)
    assert st in (None, "on", "off", "audit", "disk")
